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
from core.utils import log_message, next_id, now_utc_str, run_automations, to_ist_str, ist_date_parts, check_duplicate, ensure_catalog

router = APIRouter(tags=["facebook"])

GRAPH_VERSION = "v25.0"

# Default Facebook-field → CRM-field mapping (used when admin hasn't overridden a field).
DEFAULT_MAP = {
    "full_name": "contact_name", "name": "contact_name",
    "email": "email_from",
    "phone_number": "phone", "phone": "phone",
    "city": "city", "state": "state_name", "province": "state_name",
    "gender": "gender", "company_name": "company_name",
}


async def _fb_settings():
    return await db.settings.find_one({"key": "facebook"}, {"_id": 0}) or {}


async def _log_webhook(status: str, detail: str, leadgen_id: str = None, extra: dict = None):
    """Persist every inbound Meta webhook delivery + its outcome so 'webhooks.delivery.rejected'
    and silent Graph-fetch failures become visible in Admin → Facebook diagnostics."""
    doc = {"at": now_utc_str(), "status": status, "detail": detail, "leadgen_id": leadgen_id}
    if extra:
        doc.update(extra)
    try:
        await db.fb_webhook_log.insert_one(doc)
        # keep only the most recent 200 entries
        count = await db.fb_webhook_log.count_documents({})
        if count > 200:
            old = await db.fb_webhook_log.find({}, {"_id": 1}).sort("_id", 1).limit(count - 200).to_list(count)
            if old:
                await db.fb_webhook_log.delete_many({"_id": {"$in": [o["_id"] for o in old]}})
    except Exception:
        pass


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
            nkey = re.sub(r"[^a-z0-9]+", "_", fb_name.lower()).strip("_")
            _name_exclude = ("company", "form", "page", "user", "product", "brand", "clinic", "business")
            if "name" in nkey and not any(x in nkey for x in _name_exclude):
                continue  # a person-name field; handled by name derivation, don't clutter the Q&A card
            # keep unmapped answers under custom (visible in Q&A card)
            extras["x_custom_" + nkey[:50]] = val
            continue
        if target in custom_keys or target.startswith("x_custom_"):
            extras[target] = val
        else:
            data[target] = val

    lid = await next_id("lead")
    now = now_utc_str()
    # ensure the source shows up in the Source dropdown/filters
    source_val = settings.get("source_default") or "Meta Lead Ads"
    await ensure_catalog("source_lead", source_val)
    # normalize display name: keep contact_name and name in sync
    if data.get("name") and not data.get("contact_name"):
        data["contact_name"] = data["name"]
    elif data.get("contact_name") and not data.get("name"):
        data["name"] = data["contact_name"]
    # Fallback: derive the name if it wasn't mapped. Facebook forms name the field
    # differently (full_name / first_name+last_name / localized keys), so scan field_data
    # for any name-like field and combine first+last when needed.
    if not data.get("contact_name") and not data.get("name"):
        full = first = last = None
        for f in field_data or []:
            key = re.sub(r"[^a-z0-9]+", "_", str(f.get("name", "")).strip().lower()).strip("_")
            vals = f.get("values") or []
            v = str(vals[0]).strip() if vals else ""
            if not v:
                continue
            if key in ("full_name", "fullname", "name", "your_name", "yourname", "naam", "contact_name"):
                full = full or v
            elif key in ("first_name", "firstname", "given_name", "givenname"):
                first = first or v
            elif key in ("last_name", "lastname", "surname", "family_name", "familyname"):
                last = last or v
        derived = full or " ".join([p for p in [first, last] if p]).strip()
        if not derived:
            # Last-resort: any field whose key contains 'name' (e.g. 'what_is_your_name'),
            # excluding non-person name fields.
            exclude = ("company", "form", "page", "user", "product", "brand", "clinic", "business")
            for f in field_data or []:
                key = re.sub(r"[^a-z0-9]+", "_", str(f.get("name", "")).strip().lower()).strip("_")
                vals = f.get("values") or []
                v = str(vals[0]).strip() if vals else ""
                if v and "name" in key and not any(x in key for x in exclude):
                    derived = v
                    break
        if derived:
            data["contact_name"] = derived
            data["name"] = derived
    # round-robin assignment (same rules as web lead capture)
    user_id = None
    assign = await db.settings.find_one({"key": "assignment"})
    if assign and assign.get("enabled") and assign.get("user_ids"):
        ids = assign["user_ids"]
        ptr = assign.get("pointer", 0) % len(ids)
        user_id = ids[ptr]
        await db.settings.update_one({"key": "assignment"}, {"$set": {"pointer": (ptr + 1) % len(ids)}})
    if user_id is None:
        # Fallback so Facebook leads are never orphaned/invisible: callers only see leads
        # assigned to them, so round-robin unassigned FB leads across active caller users
        # (they then appear in the team's Lead report exactly like every other lead).
        callers = await db.users.find({"active": True, "role": "caller"}, {"_id": 0, "id": 1}).sort("id", 1).to_list(500)
        if callers:
            cids = [c["id"] for c in callers]
            ptr = await next_id("fb_assign_pointer")
            user_id = cids[(ptr - 1) % len(cids)]

    doc = {
        "id": lid, "active": True, "stage_id": 1, "type": "lead", "priority": "0",
        "name": data.get("contact_name") or data.get("name") or data.get("phone") or "Facebook Lead",
        "tags": settings.get("tag_ids") or [],
        "lead_stage": settings.get("lead_stage_default"),
        "source_lead": settings.get("source_default") or "Meta Lead Ads",
        "ads_platform": "Facebook",
        # Meta ad attribution (Attribution card): Campaign / Ad Set / Ad
        "campaign_name": raw.get("campaign_name"),
        "ads_campaign_name": raw.get("adset_name"),
        "ads_name": raw.get("ad_name"),
        "fb_campaign_id": raw.get("campaign_id"),
        "fb_adset_id": raw.get("adset_id"),
        "fb_ad_id": raw.get("ad_id"),
        "fb_form_name": raw.get("form_name"),
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
    doc.update(ist_date_parts(doc["create_date_ist"]))
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
    body = await request.body()
    sig_header = request.headers.get("X-Hub-Signature-256")
    if not s.get("app_secret") or not s.get("page_access_token"):
        await _log_webhook("rejected", "Facebook integration not configured (missing app_secret or page_access_token) → returned 503")
        raise HTTPException(status_code=503, detail="Facebook integration not configured")
    if not _verify_signature(s["app_secret"], body, sig_header):
        await _log_webhook(
            "rejected",
            "Signature verification FAILED → returned 401. The saved App Secret does not match the app "
            "that delivered this webhook. Ensure the App Secret in Settings belongs to the SAME Meta app "
            "whose 'page' webhook points to this CRM's callback URL.",
            extra={"received_signature": (sig_header or "")[:24]},
        )
        raise HTTPException(status_code=401, detail="Invalid signature")
    import json
    try:
        payload = json.loads(body.decode())
    except Exception:
        await _log_webhook("rejected", "Invalid JSON body → returned 400")
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
                    await _log_webhook("skipped", "leadgen change had no leadgen_id")
                    continue
                try:
                    resp = await client.get(
                        f"https://graph.facebook.com/{version}/{leadgen_id}",
                        params={
                            "access_token": s["page_access_token"],
                            "fields": "id,created_time,field_data,ad_id,ad_name,adset_id,adset_name,campaign_id,campaign_name,form_id,platform,is_organic",
                        },
                    )
                    lead = resp.json()
                except Exception as e:
                    await _log_webhook("error", f"Graph API request failed while fetching lead: {e}", leadgen_id)
                    continue
                if lead.get("error"):
                    err = lead["error"]
                    await _log_webhook(
                        "error",
                        f"Graph API error fetching the lead: {err.get('message')} — This usually means the saved Page "
                        f"Access Token is missing the leads_retrieval permission, is expired, or was generated under a "
                        f"different Meta app than the configured App ID. Open Admin → Facebook → Check connection to see which.",
                        leadgen_id, extra={"graph_error_code": err.get("code")},
                    )
                    continue
                # form_name is NOT a field on the leadgen node — fetch it separately from the form id.
                if lead.get("form_id"):
                    try:
                        fr = await client.get(f"https://graph.facebook.com/{version}/{lead['form_id']}",
                                               params={"access_token": s["page_access_token"], "fields": "name"})
                        fd = fr.json()
                        if fd.get("name"):
                            lead["form_name"] = fd["name"]
                    except Exception:
                        pass
                if lead.get("field_data"):
                    new_lead = await _map_and_create_lead(lead["field_data"], s, lead)
                    fkeys = [f.get("name") for f in lead.get("field_data", [])]
                    await _log_webhook("created",
                                       f"Lead created in CRM (#{new_lead['id']}) — name '{new_lead.get('name')}'. Form fields: {fkeys}",
                                       leadgen_id, extra={"crm_lead_id": new_lead["id"], "field_keys": fkeys})
                    created += 1
                else:
                    await _log_webhook("skipped", "Graph response had no field_data (nothing to import)", leadgen_id)
    return {"status": "ok", "created": created}


@router.get("/admin/facebook/webhook-log")
async def fb_webhook_log(user: dict = Depends(require_roles("admin", "manager"))):
    """Recent inbound Meta webhook deliveries + outcomes (created / rejected / error / skipped)."""
    logs = await db.fb_webhook_log.find({}, {"_id": 0}).sort("at", -1).to_list(50)
    return {"count": len(logs), "logs": logs}


@router.get("/admin/facebook/recent-leads")
async def fb_recent_leads(user: dict = Depends(require_roles("admin", "manager"))):
    """The most recently CAPTURED Facebook leads — a direct, unfiltered view so admins can
    always find Meta leads regardless of date sorting, assignment or caller-role visibility."""
    proj = {"_id": 0, "id": 1, "name": 1, "contact_name": 1, "phone": 1, "email_from": 1,
            "source_lead": 1, "fb_form_name": 1, "user_id": 1, "create_date": 1,
            "create_date_ist": 1, "active": 1}
    leads = await db.leads.find({"facebook_lead": True}, proj).sort("id", -1).to_list(25)
    total = await db.leads.count_documents({"facebook_lead": True})
    users = {u["id"]: u["name"] for u in await db.users.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)}
    for l in leads:
        l["assigned_to"] = users.get(l.get("user_id")) if l.get("user_id") else "Unassigned"
    return {"total": total, "leads": leads}


# ---- Admin: simulate a lead (lets you test mapping end-to-end without Meta) ----
class FbTestBody(BaseModel):
    field_data: list  # [{name, values:[...]}]
    form_id: Optional[str] = None
    leadgen_id: Optional[str] = None
    campaign_name: Optional[str] = None
    adset_name: Optional[str] = None
    ad_name: Optional[str] = None
    form_name: Optional[str] = None


@router.post("/admin/facebook/test")
async def fb_test_lead(body: FbTestBody, user: dict = Depends(require_roles("admin", "manager"))):
    s = await _fb_settings()
    lead = await _map_and_create_lead(
        body.field_data, s,
        {"leadgen_id": body.leadgen_id or "TEST", "form_id": body.form_id,
         "campaign_name": body.campaign_name, "adset_name": body.adset_name,
         "ad_name": body.ad_name, "form_name": body.form_name},
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
        "recent_webhook_deliveries": await db.fb_webhook_log.find({}, {"_id": 0}).sort("at", -1).to_list(10),
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

        # 1b. Inspect the token itself (debug_token): which APP owns it + does it have leads_retrieval?
        # This is the #1 cause of "Object ... does not exist / missing permissions" when FETCHING a lead:
        # the Page Access Token was generated under a DIFFERENT Meta app than the one configured here,
        # or the token is missing the leads_retrieval scope.
        app_id_cfg, app_secret_cfg = s.get("app_id"), s.get("app_secret")
        if app_id_cfg and app_secret_cfg:
            try:
                rdt = await client.get(f"https://graph.facebook.com/{version}/debug_token",
                                       params={"input_token": token, "access_token": f"{app_id_cfg}|{app_secret_cfg}"})
                dt = (rdt.json() or {}).get("data") or {}
            except Exception as e:
                dt = {}
                out["checks"].append({"name": "Token inspection", "ok": False, "detail": f"Could not inspect token: {e}"})
            if dt:
                token_app_id = str(dt.get("app_id") or "")
                scopes = dt.get("scopes") or []
                # App match
                if token_app_id and token_app_id != str(app_id_cfg):
                    out["checks"].append({"name": "Token ↔ App match", "ok": False,
                        "detail": f"The saved Page Access Token belongs to Meta app {token_app_id}, but the configured App ID is {app_id_cfg}. "
                                  f"Lead retrieval fails because the token is from a different app. Generate the Page Access Token under the SAME app ({app_id_cfg}) and save it."})
                    out["next_step"] = (f"Generate a Page Access Token in Meta with the 'Meta App' set to your CRM app ({app_id_cfg}) "
                                        f"— NOT a different app — with leads_retrieval + pages_manage_metadata, then paste it into Page Access Token and Save.")
                else:
                    out["checks"].append({"name": "Token ↔ App match", "ok": True,
                        "detail": f"Token belongs to the configured app ({app_id_cfg}) ✓"})
                # leads_retrieval scope
                has_leads_retrieval = "leads_retrieval" in scopes
                out["checks"].append({"name": "leads_retrieval permission", "ok": has_leads_retrieval,
                    "detail": "Token has leads_retrieval ✓" if has_leads_retrieval
                    else "Token is MISSING the leads_retrieval permission — the CRM cannot read lead form answers. Regenerate the Page Access Token WITH leads_retrieval and save it."})
                if not has_leads_retrieval and not out.get("next_step"):
                    out["next_step"] = ("Regenerate the Page Access Token in Meta and ADD the 'leads_retrieval' permission "
                                        "(also keep pages_manage_metadata), then paste it into Page Access Token and Save.")

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
