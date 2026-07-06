"""Case 14 — Email / WhatsApp marketing: create campaigns and send in bulk to a filtered audience."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import require_permission
from core.utils import next_id, now_utc_str, log_message
from core import whatsapp_cloud as wac
from routes.leads import build_query

router = APIRouter(prefix="/marketing", tags=["marketing"])

MAX_SEND = 5000
AUDIENCE_KEYS = ["search", "lead_stage", "tags", "user_id", "source_lead", "campaign_name",
                 "ads_platform", "city", "state_name", "follow_up_tag", "priority", "active"]


def _audience_query(audience: dict, user: dict) -> dict:
    params = {k: None for k in [
        "search", "stage_id", "lead_stage", "tags", "user_id", "source_lead", "campaign_name",
        "ads_platform", "city", "state_name", "date_from", "date_to", "follow_up", "priority",
        "follow_up_tag", "lost_reason_id"]}
    params["active"] = audience.get("active", "true")
    for k in AUDIENCE_KEYS:
        if k != "active" and audience.get(k) not in (None, ""):
            params[k] = audience[k]
    return build_query(**params, current_user=user)


class CampaignBody(BaseModel):
    name: str
    channel: str  # whatsapp | email
    template_id: Optional[int] = None
    audience: dict = {}


@router.get("/campaigns")
async def list_campaigns(user: dict = Depends(require_permission("marketing"))):
    return await db.campaigns.find({}, {"_id": 0}).sort("id", -1).to_list(200)


@router.post("/campaigns")
async def create_campaign(body: CampaignBody, user: dict = Depends(require_permission("marketing"))):
    if body.channel not in ("whatsapp", "email"):
        raise HTTPException(status_code=400, detail="Invalid channel")
    cid = await next_id("campaign")
    doc = {"id": cid, "name": body.name.strip(), "channel": body.channel,
           "template_id": body.template_id, "audience": body.audience or {},
           "status": "draft", "total": 0, "sent": 0, "failed": 0, "queued": 0,
           "created_by": user["name"], "created_at": now_utc_str()}
    await db.campaigns.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/campaigns/{cid}")
async def delete_campaign(cid: int, user: dict = Depends(require_permission("marketing"))):
    await db.campaigns.delete_one({"id": cid})
    return {"ok": True}


@router.post("/campaigns/{cid}/audience-count")
async def audience_count(cid: int, user: dict = Depends(require_permission("marketing"))):
    camp = await db.campaigns.find_one({"id": cid}, {"_id": 0})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    q = _audience_query(camp.get("audience") or {}, user)
    field = "phone_digits" if camp["channel"] == "whatsapp" else "email_from"
    q[field] = {"$nin": [None, "", False]}
    return {"count": await db.leads.count_documents(q)}


@router.post("/campaigns/{cid}/send")
async def send_campaign(cid: int, user: dict = Depends(require_permission("marketing"))):
    camp = await db.campaigns.find_one({"id": cid}, {"_id": 0})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if camp.get("status") == "sending":
        raise HTTPException(status_code=409, detail="Campaign is already sending")
    template = None
    if camp.get("template_id"):
        coll = db.templates_whatsapp if camp["channel"] == "whatsapp" else db.templates_email
        template = await coll.find_one({"id": int(camp["template_id"])}, {"_id": 0})
    if not template:
        raise HTTPException(status_code=400, detail="Select a valid template first")

    q = _audience_query(camp.get("audience") or {}, user)
    field = "phone_digits" if camp["channel"] == "whatsapp" else "email_from"
    q[field] = {"$nin": [None, "", False]}
    await db.campaigns.update_one({"id": cid}, {"$set": {"status": "sending", "started_at": now_utc_str()}})

    wa_live = await wac.is_configured() if camp["channel"] == "whatsapp" else False
    email_live = False
    if camp["channel"] == "email":
        from core import gmail_send as gm
        email_live = await gm.is_connected()
    sent = failed = queued = total = 0
    cursor = db.leads.find(q, {"_id": 0}).limit(MAX_SEND)
    async for lead in cursor:
        total += 1
        if camp["channel"] == "whatsapp":
            if wa_live:
                res = await wac.send_lead_template(lead, template)
                if res.get("ok"):
                    sent += 1
                else:
                    failed += 1
                    queued += 1
                    await db.outbound_queue.insert_one({"channel": "whatsapp", "lead_id": lead["id"],
                        "template_id": template["id"], "status": "failed", "campaign_id": cid,
                        "error": res.get("error"), "created_at": now_utc_str()})
            else:
                queued += 1
                await db.outbound_queue.insert_one({"channel": "whatsapp", "lead_id": lead["id"],
                    "template_id": template["id"], "status": "pending_api_credentials",
                    "campaign_id": cid, "created_at": now_utc_str()})
        else:
            to = (lead.get("email_from") or "").strip()
            name = lead.get("contact_name") or "there"
            body_txt = (template.get("body") or "").replace("{{1}}", name)
            subject = template.get("subject") or camp["name"]
            if email_live and to:
                from core import gmail_send as gm
                res = await gm.send_email(to, subject, body_txt, html=True)
                if res.get("ok"):
                    sent += 1
                else:
                    failed += 1
                    await db.outbound_queue.insert_one({"channel": "email", "lead_id": lead["id"],
                        "to": to, "subject": subject, "body": body_txt, "status": "failed",
                        "error": res.get("error"), "template_id": template["id"], "campaign_id": cid,
                        "created_at": now_utc_str()})
            else:
                queued += 1
                await db.outbound_queue.insert_one({"channel": "email", "lead_id": lead["id"],
                    "to": to, "subject": subject, "body": body_txt, "template_id": template["id"],
                    "status": "pending_api_credentials", "campaign_id": cid, "created_at": now_utc_str()})

    status = "sent" if (sent and not queued and not failed) else ("partial" if sent else "queued")
    await db.campaigns.update_one({"id": cid}, {"$set": {
        "status": status, "total": total, "sent": sent, "failed": failed, "queued": queued,
        "finished_at": now_utc_str()}})
    return {"ok": True, "total": total, "sent": sent, "failed": failed, "queued": queued, "status": status,
            "live": wa_live or email_live}
