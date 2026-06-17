"""WhatsApp Cloud API webhook (inbound) + admin endpoints (introspection / test)."""
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from core import whatsapp_cloud as wac
from core.db import db
from core.security import require_roles
from core.utils import log_message, next_id, now_utc_str

router = APIRouter(tags=["whatsapp-cloud"])


# ---- Inbound webhook verification ----
@router.get("/webhooks/whatsapp")
async def wa_verify(request: Request):
    c = await wac.get_config()
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") and p.get("hub.verify_token") == c.get("verify_token") and p.get("hub.challenge"):
        return PlainTextResponse(content=p.get("hub.challenge"), status_code=200)
    raise HTTPException(status_code=403, detail="Verification failed")


# ---- Inbound messages ----
@router.post("/webhooks/whatsapp")
async def wa_webhook(request: Request):
    c = await wac.get_config()
    if not c.get("app_secret"):
        raise HTTPException(status_code=503, detail="WhatsApp not configured")
    body = await request.body()
    if not wac.verify_signature(c["app_secret"], body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        payload = json.loads(body.decode())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    stored = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for m in value.get("messages", []):
                frm = m.get("from")
                text = (m.get("text") or {}).get("body") or f"[{m.get('type')}]"
                now = now_utc_str()
                digits = re.sub(r"\D", "", frm or "")[-10:]
                # mirror into existing WhatsApp thread for this number, if any
                ch = await db.wa_channels.find_one({"phone_digits": {"$regex": digits + "$"}}) if len(digits) >= 8 else None
                if ch:
                    await db.wa_messages.insert_one({
                        "id": await next_id("wa_message"), "channel_id": ch["id"], "body": text,
                        "author_name": ch.get("name") or frm, "date": now,
                        "message_type": "comment", "direction": "inbound", "status": "received",
                        "wamid": m.get("id"),
                    })
                    await db.wa_channels.update_one({"id": ch["id"]}, {"$set": {"last_message_date": now}})
                # log to a matching lead's chatter
                if len(digits) >= 8:
                    lead = await db.leads.find_one({"phone_digits": digits}, {"id": 1}, sort=[("write_date", -1)])
                    if lead:
                        await log_message(lead["id"], f"💬 Inbound WhatsApp from {frm}: {text[:500]}", subtype="comment")
                stored += 1
    return {"status": "ok", "stored": stored}


# ---- Admin introspection / test ----
@router.get("/admin/whatsapp/status")
async def wa_status(user: dict = Depends(require_roles("admin", "manager"))):
    c = await wac.get_config()
    return {
        "configured": bool(c.get("access_token") and c.get("phone_number_id")),
        "waba_id": c.get("waba_id"),
        "phone_number_id": c.get("phone_number_id"),
        "has_verify_token": bool(c.get("verify_token")),
        "graph_api_version": c.get("graph_api_version") or wac.GRAPH_VERSION,
    }


@router.post("/admin/whatsapp/phone-numbers")
async def wa_phone_numbers(user: dict = Depends(require_roles("admin", "manager"))):
    data = await wac.list_phone_numbers()
    if data.get("error"):
        raise HTTPException(status_code=400, detail=data["error"].get("message", str(data["error"])))
    return data


@router.post("/admin/whatsapp/templates")
async def wa_templates(user: dict = Depends(require_roles("admin", "manager"))):
    data = await wac.list_templates()
    if data.get("error"):
        raise HTTPException(status_code=400, detail=data["error"].get("message", str(data["error"])))
    return data


class WaTestBody(BaseModel):
    to: str
    body: str = "Hello from HomeIVF CRM 👋"


@router.post("/admin/whatsapp/send-test")
async def wa_send_test(b: WaTestBody, user: dict = Depends(require_roles("admin", "manager"))):
    res = await wac.send_text(b.to, b.body)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "send failed"))
    return res
