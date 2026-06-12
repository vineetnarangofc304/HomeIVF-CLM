import re
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.db import db
from core.security import require_roles
from core.utils import log_message, next_id, now_utc_str, run_automations, to_ist_str

router = APIRouter(tags=["webhooks"])

FIELD_ALIASES = {
    "name": ["name", "full_name", "fullname", "lead_name"],
    "contact_name": ["contact_name", "name", "full_name", "fullname"],
    "phone": ["phone", "phone_number", "mobile", "contact", "whatsapp"],
    "email_from": ["email", "email_from", "email_address"],
    "city": ["city"],
    "state_name": ["state", "state_name", "region"],
    "gender": ["gender", "sex", "your_gender"],
    "male_age": ["male_age"],
    "female_age": ["female_age"],
    "query": ["query", "message", "question"],
    "campaign_name": ["campaign_name", "campaign", "utm_campaign"],
    "ads_platform": ["ads_platform", "platform", "utm_source"],
    "ads_name": ["ads_name", "ad_name"],
    "ads_campaign_name": ["ads_campaign_name", "adset_name"],
}


@router.post("/webhook/lead/{token}")
async def webhook_lead(token: str, request: Request):
    hook = await db.webhooks.find_one({"token": token, "active": True})
    if not hook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    try:
        payload = await request.json()
    except Exception:
        form = await request.form()
        payload = dict(form)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")

    lower = {str(k).strip().lower().replace(" ", "_"): v for k, v in payload.items()}
    data = {}
    for field, aliases in FIELD_ALIASES.items():
        for a in aliases:
            if a in lower and lower[a] not in (None, ""):
                data[field] = str(lower[a]).strip()
                break
    extras = {k: v for k, v in lower.items() if v not in (None, "")}
    # map admin-defined custom fields (Case 4: form/ads field mapping)
    defs = await db.custom_fields.find({"active": True}).to_list(300)
    for d in defs:
        for alias in [d["key"], d["label"]] + (d.get("aliases") or []):
            a = str(alias).strip().lower().replace(" ", "_")
            if a in lower and lower[a] not in (None, ""):
                extras[d["key"]] = str(lower[a]).strip()
                break

    lid = await next_id("lead")
    now = now_utc_str()
    user_id = None
    settings = await db.settings.find_one({"key": "assignment"})
    if hook.get("assign_round_robin") and settings and settings.get("enabled") and settings.get("user_ids"):
        ids = settings["user_ids"]
        ptr = settings.get("pointer", 0) % len(ids)
        user_id = ids[ptr]
        await db.settings.update_one({"key": "assignment"}, {"$set": {"pointer": (ptr + 1) % len(ids)}})

    doc = {
        "id": lid, "active": True, "stage_id": 1, "type": "lead", "priority": "0",
        "name": data.get("name") or data.get("contact_name") or data.get("phone") or "Web Lead",
        "tags": hook.get("tag_ids") or [],
        "lead_stage": hook.get("lead_stage_default"),
        "source_lead": hook.get("source_default") or "website",
        "user_id": user_id,
        "create_date": now, "create_date_ist": to_ist_str(now), "write_date": now,
        "custom": extras, "webhook_id": hook["id"],
        "phone_digits": re.sub(r"\D", "", data.get("phone") or "")[-10:],
        **{k: v for k, v in data.items() if k != "name"},
    }
    await db.leads.insert_one(doc)
    await db.webhooks.update_one({"id": hook["id"]}, {"$inc": {"hits": 1}})
    await log_message(lid, f"Lead captured via webhook '{hook['name']}'")
    await run_automations("on_create", doc)
    return {"ok": True, "lead_id": lid}


class WebhookCreate(BaseModel):
    name: str
    source_default: Optional[str] = "website"
    lead_stage_default: Optional[str] = None
    tag_ids: Optional[list] = None
    assign_round_robin: bool = True


@router.get("/webhooks")
async def list_webhooks(user: dict = Depends(require_roles("admin", "manager"))):
    return await db.webhooks.find({}, {"_id": 0}).sort("id", 1).to_list(100)


@router.post("/webhooks")
async def create_webhook(body: WebhookCreate, user: dict = Depends(require_roles("admin"))):
    wid = await next_id("webhook")
    doc = {
        "id": wid, "name": body.name, "token": secrets.token_urlsafe(16),
        "source_default": body.source_default, "lead_stage_default": body.lead_stage_default,
        "tag_ids": body.tag_ids or [], "assign_round_robin": body.assign_round_robin,
        "active": True, "hits": 0, "created_at": now_utc_str(),
    }
    await db.webhooks.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/webhooks/{wid}")
async def update_webhook(wid: int, body: dict, user: dict = Depends(require_roles("admin"))):
    allowed = {"name", "source_default", "lead_stage_default", "tag_ids", "assign_round_robin", "active"}
    updates = {k: v for k, v in body.items() if k in allowed}
    res = await db.webhooks.update_one({"id": wid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return await db.webhooks.find_one({"id": wid}, {"_id": 0})


@router.delete("/webhooks/{wid}")
async def delete_webhook(wid: int, user: dict = Depends(require_roles("admin"))):
    await db.webhooks.delete_one({"id": wid})
    return {"ok": True}
