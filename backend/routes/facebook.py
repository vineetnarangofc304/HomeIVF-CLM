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
from core.utils import log_message, next_id, now_utc_str, run_automations, to_ist_str, check_duplicate

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
    dup = await check_duplicate(doc["phone_digits"])
    doc["is_duplicate"] = dup["is_duplicate"]
    doc["duplicate_of"] = dup["duplicate_of"]
    await db.leads.insert_one(doc)
    await log_message(lid, f"Lead captured via {source_label} (Facebook Page lead form)")
    if dup["is_duplicate"]:
        await log_message(lid, f"⚠️ Possible duplicate — same phone as lead #{dup['duplicate_of']}", subtype="comment")
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


class FbRegisterBody(BaseModel):
    callback_url: str


@router.post("/admin/facebook/register-webhook")
async def fb_register_webhook(body: FbRegisterBody, user: dict = Depends(require_roles("admin"))):
    """Register the app-level `page`/leadgen webhook with Meta so lead events are
    delivered to THIS CRM's callback URL. Meta verifies the callback (GET hub.challenge)
    against the saved verify_token before accepting. Uses the app access token."""
    s = await _fb_settings()
    app_id, app_secret, verify_token = s.get("app_id"), s.get("app_secret"), s.get("verify_token")
    if not (app_id and app_secret and verify_token):
        raise HTTPException(status_code=400, detail="Save App ID, App Secret and Verify Token first.")
    callback_url = (body.callback_url or "").strip()
    if not callback_url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Callback URL must be an https:// URL.")
    version = s.get("graph_api_version") or GRAPH_VERSION
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"https://graph.facebook.com/{version}/{app_id}/subscriptions",
                params={
                    "object": "page",
                    "callback_url": callback_url,
                    "fields": "leadgen",
                    "verify_token": verify_token,
                    "access_token": f"{app_id}|{app_secret}",
                },
            )
            data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Facebook request failed: {e}")
    if resp.status_code >= 400 or data.get("error"):
        raise HTTPException(status_code=400, detail=str(data.get("error", data)))
    return {"ok": True, "callback_url": callback_url, "response": data}


@router.get("/admin/facebook/diagnose")
async def fb_diagnose(user: dict = Depends(require_roles("admin", "manager"))):
    """Live diagnostic: checks token validity + whether the Page is actually
    subscribed to leadgen with our app. Pinpoints why leads aren't arriving."""
    s = await _fb_settings()
    version = s.get("graph_api_version") or GRAPH_VERSION
    out = {
        "configured": bool(s.get("app_secret") and s.get("page_access_token")),
        "verify_token_set": bool(s.get("verify_token")),
        "page_id_set": bool(s.get("page_id")),
        "leads_captured": await db.leads.count_documents({"facebook_lead": True}),
        "checks": [],
        "next_step": None,
    }
    token = s.get("page_access_token")
    if not token:
        out["checks"].append({"name": "Page Access Token", "ok": False, "detail": "No Page Access Token saved."})
        out["next_step"] = "Enter your Page Access Token (with leads_retrieval + pages_manage_metadata) and save."
        return out

    async with httpx.AsyncClient(timeout=15) as client:
        # 1. Token valid + what it points to
        try:
            r = await client.get(f"https://graph.facebook.com/{version}/me",
                                 params={"access_token": token, "fields": "id,name"})
            d = r.json()
        except Exception as e:
            out["checks"].append({"name": "Access Token", "ok": False, "detail": f"Request failed: {e}"})
            return out
        if d.get("error"):
            out["checks"].append({"name": "Access Token", "ok": False, "detail": d["error"].get("message")})
            out["next_step"] = "Token is invalid/expired. Generate a long-lived Page Access Token in Meta and save it."
            return out
        out["checks"].append({"name": "Access Token", "ok": True, "detail": f"Valid — points to '{d.get('name')}' (id {d.get('id')})"})
        token_points_to = str(d.get("id"))

        # 2. Page subscribed to leadgen?
        page_id = s.get("page_id")
        if not page_id:
            out["checks"].append({"name": "Page subscription", "ok": False, "detail": "No Page ID saved."})
            out["next_step"] = "Enter your Facebook Page ID and click 'Subscribe Page to leadgen'."
            return out
        if token_points_to and page_id and token_points_to != page_id:
            out["checks"].append({"name": "Token ↔ Page match", "ok": False,
                "detail": f"Your token belongs to id {token_points_to} but Page ID is {page_id}. Use the Page's own access token."})
        try:
            r2 = await client.get(f"https://graph.facebook.com/{version}/{page_id}/subscribed_apps",
                                  params={"access_token": token})
            d2 = r2.json()
        except Exception as e:
            out["checks"].append({"name": "Page subscription", "ok": False, "detail": f"Request failed: {e}"})
            return out
        if d2.get("error"):
            out["checks"].append({"name": "Page subscription", "ok": False, "detail": d2["error"].get("message")})
            out["next_step"] = "Token likely lacks pages_manage_metadata / leads_retrieval permission. Fix scopes, then click 'Subscribe Page to leadgen'."
            return out
        apps = d2.get("data") or []
        leadgen_subscribed = any("leadgen" in (a.get("subscribed_fields") or []) for a in apps)
        out["checks"].append({
            "name": "Page subscribed to leadgen", "ok": leadgen_subscribed,
            "detail": "Page is subscribed to leadgen ✓" if leadgen_subscribed
            else f"Page is NOT subscribed to leadgen (found {len(apps)} app subscription(s)).",
        })
        if not leadgen_subscribed:
            out["next_step"] = "Click 'Subscribe Page to leadgen' below, then submit a Meta test lead."
        else:
            # 3. App-level page webhook callback registered?
            app_id, app_secret = s.get("app_id"), s.get("app_secret")
            if app_id and app_secret:
                try:
                    r3 = await client.get(f"https://graph.facebook.com/{version}/{app_id}/subscriptions",
                                          params={"access_token": f"{app_id}|{app_secret}"})
                    d3 = r3.json()
                    page_sub = next((x for x in (d3.get("data") or []) if x.get("object") == "page"), None)
                    has_leadgen_field = bool(page_sub) and any(
                        (f.get("name") if isinstance(f, dict) else f) == "leadgen" for f in (page_sub.get("fields") or [])
                    )
                    if page_sub and has_leadgen_field:
                        out["checks"].append({"name": "App leadgen webhook", "ok": True,
                            "detail": f"Registered → {page_sub.get('callback_url')}"})
                        out["next_step"] = ("Connection looks good. Submit a Meta test lead (Lead Ads Testing Tool) — "
                                            "it should appear in the CRM within seconds.")
                    else:
                        out["checks"].append({"name": "App leadgen webhook", "ok": False,
                            "detail": "No 'page' webhook with the leadgen field is registered on your Meta app — leads have nowhere to be delivered."})
                        out["next_step"] = "Click 'Register leadgen webhook with Meta' below to point the webhook at this CRM."
                except Exception as e:
                    out["checks"].append({"name": "App leadgen webhook", "ok": False, "detail": f"Could not check: {e}"})
            else:
                out["next_step"] = ("Page is subscribed. Also ensure the app-level 'page' webhook points to the callback URL "
                                    "above (use 'Register leadgen webhook with Meta').")
    return out


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
