"""Meta (Facebook) Lead Ads integration — capture Page lead-form submissions.

Flow: Meta verifies our webhook (GET hub.challenge), then POSTs leadgen events.
We validate X-Hub-Signature-256 with the App Secret, fetch each lead's full
field_data from the Graph API (v25.0) using the Page Access Token, map the
Facebook fields → CRM lead fields per the admin-configured mapping, and create
the lead (round-robin assigned, automations fired) — exactly like webhook leads.

Config lives in settings key="facebook" (managed in Admin → Facebook). Built
ready-to-connect: until creds are entered, the webhook simply 503s gracefully.
"""
import re
import hmac
import hashlib
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from core.db import db
from core.security import require_roles
from core.utils import log_message, next_id, now_utc_str, run_automations, to_ist_str

router = APIRouter(tags=["facebook"])

GRAPH_VERSION = "v25.0"

# Default Facebook-field → CRM-field mapping (used when admin hasn't overridden a field).
DEFAULT_MAP = {
    "full_name": "contact_name", "name": "contact_name",
    "first_name": "contact_name", "email": "email_from",
    "phone_number": "phone", "phone": "phone",
    "city": "city", "state": "state_name", "province": "state_name",
    "gender": "gender", "company_name": "company_name",
}


async def _fb_settings():
    return await db.settings.find_one({"key": "facebook"}, {"_id": 0}) or {}


def _verify_signature(app_secret: str, body: bytes, header: Optional[str]) -> bool:
    if not app_secret or not header:
        return False
    try:
        scheme, sig = header.split("=", 1)
    except ValueError:
        return False
    if scheme != "sha256":
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


async def _map_and_create_lead(field_data: list, settings: dict, raw: dict, source_label="Facebook Lead Ads"):
    mapping = settings.get("field_mapping") or {}
    custom_defs = await db.custom_fields.find({"active": True}, {"_id": 0}).to_list(300)
    custom_keys = {d["key"] for d in custom_defs}

    data, extras = {}, {}
    for f in field_data or []:
        fb_name = str(f.get("name", "")).strip()
        values = f.get("values") or []
        val = str(values[0]).strip() if values else ""
        if not fb_name or val == "":
            continue
        target = mapping.get(fb_name) or DEFAULT_MAP.get(fb_name.lower())
        if not target:
            # keep unmapped answers under custom (visible in Q&A card)
            extras["x_custom_" + re.sub(r"[^a-z0-9]+", "_", fb_name.lower()).strip("_")[:50]] = val
            continue
        if target in custom_keys or target.startswith("x_custom_"):
            extras[target] = val
        else:
            data[target] = val

    lid = await next_id("lead")
    now = now_utc_str()
    # round-robin assignment (same rules as web lead capture)
    user_id = None
    assign = await db.settings.find_one({"key": "assignment"})
    if assign and assign.get("enabled") and assign.get("user_ids"):
        ids = assign["user_ids"]
        ptr = assign.get("pointer", 0) % len(ids)
        user_id = ids[ptr]
        await db.settings.update_one({"key": "assignment"}, {"$set": {"pointer": (ptr + 1) % len(ids)}})

    doc = {
        "id": lid, "active": True, "stage_id": 1, "type": "lead", "priority": "0",
        "name": data.get("contact_name") or data.get("name") or data.get("phone") or "Facebook Lead",
        "tags": settings.get("tag_ids") or [],
        "lead_stage": settings.get("lead_stage_default"),
        "source_lead": settings.get("source_default") or "Meta Lead Ads",
        "ads_platform": "Facebook",
        "user_id": user_id,
        "create_date": now, "create_date_ist": to_ist_str(now), "write_date": now,
        "custom": extras, "facebook_lead": True,
        "facebook_leadgen_id": raw.get("leadgen_id") or raw.get("id"),
        "facebook_form_id": raw.get("form_id"),
        "phone_digits": re.sub(r"\D", "", data.get("phone") or "")[-10:],
        **{k: v for k, v in data.items() if k != "name"},
    }
    await db.leads.insert_one(doc)
    await log_message(lid, f"Lead captured via {source_label} (Facebook Page lead form)")
    await run_automations("on_create", doc)
    doc.pop("_id", None)
    return doc


# ---- Meta webhook verification (GET) ----
@router.get("/webhooks/facebook")
async def fb_verify(request: Request):
    s = await _fb_settings()
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") and p.get("hub.verify_token") == s.get("verify_token") and p.get("hub.challenge"):
        return PlainTextResponse(content=p.get("hub.challenge"), status_code=200)
    raise HTTPException(status_code=403, detail="Verification failed")


# ---- Meta leadgen notifications (POST) ----
@router.post("/webhooks/facebook")
async def fb_webhook(request: Request):
    s = await _fb_settings()
    if not s.get("app_secret") or not s.get("page_access_token"):
        raise HTTPException(status_code=503, detail="Facebook integration not configured")
    body = await request.body()
    if not _verify_signature(s["app_secret"], body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Invalid signature")
    import json
    try:
        payload = json.loads(body.decode())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    version = s.get("graph_api_version") or GRAPH_VERSION
    created = 0
    async with httpx.AsyncClient(timeout=15) as client:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "leadgen":
                    continue
                value = change.get("value", {})
                leadgen_id = value.get("leadgen_id")
                if not leadgen_id:
                    continue
                try:
                    resp = await client.get(
                        f"https://graph.facebook.com/{version}/{leadgen_id}",
                        params={"access_token": s["page_access_token"]},
                    )
                    lead = resp.json()
                except Exception:
                    continue
                if lead.get("field_data"):
                    await _map_and_create_lead(lead["field_data"], s, lead)
                    created += 1
    return {"status": "ok", "created": created}


# ---- Admin: simulate a lead (lets you test mapping end-to-end without Meta) ----
class FbTestBody(BaseModel):
    field_data: list  # [{name, values:[...]}]
    form_id: Optional[str] = None
    leadgen_id: Optional[str] = None


@router.post("/admin/facebook/test")
async def fb_test_lead(body: FbTestBody, user: dict = Depends(require_roles("admin", "manager"))):
    s = await _fb_settings()
    lead = await _map_and_create_lead(
        body.field_data, s,
        {"leadgen_id": body.leadgen_id or "TEST", "form_id": body.form_id},
        source_label="Facebook Lead Ads (test)",
    )
    return {"ok": True, "lead_id": lead["id"], "lead": lead}


# ---- Admin: subscribe the Page to leadgen (one-time, needs valid creds) ----
@router.post("/admin/facebook/subscribe")
async def fb_subscribe(user: dict = Depends(require_roles("admin"))):
    s = await _fb_settings()
    if not s.get("page_id") or not s.get("page_access_token"):
        raise HTTPException(status_code=400, detail="Page ID and Page Access Token required")
    version = s.get("graph_api_version") or GRAPH_VERSION
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://graph.facebook.com/{version}/{s['page_id']}/subscribed_apps",
                params={"subscribed_fields": "leadgen", "access_token": s["page_access_token"]},
            )
            data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Facebook request failed: {e}")
    if resp.status_code >= 400 or data.get("error"):
        raise HTTPException(status_code=400, detail=str(data.get("error", data)))
    return {"ok": True, "response": data}


@router.get("/admin/facebook/status")
async def fb_status(user: dict = Depends(require_roles("admin", "manager"))):
    s = await _fb_settings()
    return {
        "configured": bool(s.get("app_secret") and s.get("page_access_token")),
        "has_verify_token": bool(s.get("verify_token")),
        "page_id": s.get("page_id"),
        "leads_captured": await db.leads.count_documents({"facebook_lead": True}),
        "field_mapping": s.get("field_mapping") or {},
        "graph_api_version": s.get("graph_api_version") or GRAPH_VERSION,
    }
