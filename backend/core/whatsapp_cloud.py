"""WhatsApp Business Cloud API (Meta Graph API) service.

Live sending of template + session text messages, plus inbound webhook signature
verification and phone-number/template introspection. Config lives in settings
key="whatsapp_cloud" (managed in Admin → WhatsApp). No secrets in source.
"""
import re
import hmac
import hashlib
from typing import Optional

import httpx

from core.db import db

GRAPH_VERSION = "v25.0"


async def get_config() -> dict:
    return await db.settings.find_one({"key": "whatsapp_cloud"}, {"_id": 0}) or {}


async def is_configured() -> bool:
    c = await get_config()
    return bool(c.get("access_token") and c.get("phone_number_id"))


def norm_msisdn(to: Optional[str]) -> str:
    return re.sub(r"\D", "", str(to or ""))


def verify_signature(app_secret: str, body: bytes, header: Optional[str]) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


async def _post_message(payload: dict) -> dict:
    c = await get_config()
    if not c.get("access_token") or not c.get("phone_number_id"):
        return {"ok": False, "error": "WhatsApp Cloud API not configured"}
    ver = c.get("graph_api_version") or GRAPH_VERSION
    url = f"https://graph.facebook.com/{ver}/{c['phone_number_id']}/messages"
    headers = {"Authorization": f"Bearer {c['access_token']}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=20) as cl:
            r = await cl.post(url, headers=headers, json=payload)
        data = r.json()
    except Exception as e:
        return {"ok": False, "error": f"request failed: {e}"}
    if r.status_code >= 400 or data.get("error"):
        return {"ok": False, "error": (data.get("error") or {}).get("message", str(data)), "raw": data}
    wamid = (data.get("messages") or [{}])[0].get("id")
    return {"ok": True, "wamid": wamid, "raw": data}


async def send_text(to: str, body: str) -> dict:
    return await _post_message({
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": norm_msisdn(to), "type": "text",
        "text": {"preview_url": False, "body": body},
    })


async def send_template(to: str, template_name: str, language: str = "en", body_params: Optional[list] = None) -> dict:
    template = {"name": template_name, "language": {"code": language or "en"}}
    if body_params:
        template["components"] = [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in body_params]}]
    return await _post_message({
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": norm_msisdn(to), "type": "template", "template": template,
    })


async def send_lead_template(lead: dict, template: dict) -> dict:
    """Send a templates_whatsapp record to a lead via Cloud API.
    Uses the approved Cloud template name (wa_template_name) when set, else falls
    back to a free-form session text using the rendered body."""
    phone = lead.get("phone") or lead.get("mobile")
    if not phone:
        return {"ok": False, "error": "lead has no phone"}
    name = lead.get("contact_name") or lead.get("name") or ""
    body = (template.get("body") or "").replace("{{1}}", name)
    wa_name = template.get("wa_template_name")
    if wa_name:
        params = [name] if "{{1}}" in (template.get("body") or "") else None
        return await send_template(phone, wa_name, template.get("lang") or "en", params)
    return await send_text(phone, body)


async def _graph_get(path: str, params: dict = None) -> dict:
    c = await get_config()
    if not c.get("access_token"):
        return {"error": {"message": "not configured"}}
    ver = c.get("graph_api_version") or GRAPH_VERSION
    url = f"https://graph.facebook.com/{ver}/{path}"
    p = {"access_token": c["access_token"], **(params or {})}
    try:
        async with httpx.AsyncClient(timeout=20) as cl:
            r = await cl.get(url, params=p)
        return r.json()
    except Exception as e:
        return {"error": {"message": str(e)}}


async def _graph_post(path: str, data: dict = None) -> dict:
    c = await get_config()
    if not c.get("access_token"):
        return {"error": {"message": "not configured"}}
    ver = c.get("graph_api_version") or GRAPH_VERSION
    url = f"https://graph.facebook.com/{ver}/{path}"
    try:
        async with httpx.AsyncClient(timeout=20) as cl:
            r = await cl.post(url, params={"access_token": c["access_token"]}, json=(data or {}))
        return r.json()
    except Exception as e:
        return {"error": {"message": str(e)}}


async def subscribe_waba() -> dict:
    """Subscribe the app to this WABA's webhooks so Meta delivers message + status
    events (sent/delivered/read/failed). Required for delivery-status tracking."""
    c = await get_config()
    if not c.get("waba_id"):
        return {"error": {"message": "WABA ID required"}}
    return await _graph_post(f"{c['waba_id']}/subscribed_apps")


async def get_subscribed_apps() -> dict:
    c = await get_config()
    if not c.get("waba_id"):
        return {"error": {"message": "WABA ID required"}}
    return await _graph_get(f"{c['waba_id']}/subscribed_apps")


async def check_app_subscriptions() -> dict:
    """Read the Meta app's webhook subscriptions (uses an app access token).
    Reveals the callback URL + subscribed fields for whatsapp_business_account —
    i.e. whether Meta is pointed at THIS CRM and the 'messages' field is on
    (which carries delivery/read status events)."""
    c = await get_config()
    app_id, app_secret = c.get("app_id"), c.get("app_secret")
    if not app_id or not app_secret:
        return {"error": {"message": "App ID and App Secret required"}}
    ver = c.get("graph_api_version") or GRAPH_VERSION
    url = f"https://graph.facebook.com/{ver}/{app_id}/subscriptions"
    try:
        async with httpx.AsyncClient(timeout=20) as cl:
            r = await cl.get(url, params={"access_token": f"{app_id}|{app_secret}"})
        return r.json()
    except Exception as e:
        return {"error": {"message": str(e)}}


async def list_phone_numbers() -> dict:
    c = await get_config()
    if not c.get("waba_id"):
        return {"error": {"message": "WABA ID required"}}
    return await _graph_get(f"{c['waba_id']}/phone_numbers", {"fields": "id,display_phone_number,verified_name,quality_rating"})


async def list_templates() -> dict:
    c = await get_config()
    if not c.get("waba_id"):
        return {"error": {"message": "WABA ID required"}}
    return await _graph_get(f"{c['waba_id']}/message_templates", {"fields": "name,status,language,category", "limit": 100})
