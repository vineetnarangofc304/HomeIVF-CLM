"""Gmail OAuth connect/callback + status/test endpoints."""
import secrets
import warnings
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from core.db import db
from core.security import require_roles
from core.utils import now_utc_str
from core import gmail_send as gm

router = APIRouter(tags=["gmail"])


@router.get("/admin/gmail/auth-url")
async def gmail_auth_url(user: dict = Depends(require_roles("admin"))):
    flow = gm.make_flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    await db.oauth_states.delete_many({"provider": "gmail"})
    await db.oauth_states.insert_one({"provider": "gmail", "state": state, "user_id": user["id"], "created_at": now_utc_str()})
    return {"url": url}


@router.get("/oauth/gmail/callback")
async def gmail_callback(code: str = Query(None), state: str = Query(None), error: str = Query(None)):
    base = gm.redirect_uri().split("/api/")[0]
    if error or not code:
        return RedirectResponse(f"{base}/admin?tab=Email&gmail=error")
    st = await db.oauth_states.find_one({"provider": "gmail", "state": state})
    if not st:
        return RedirectResponse(f"{base}/admin?tab=Email&gmail=badstate")
    await db.oauth_states.delete_one({"_id": st["_id"]})
    flow = gm.make_flow()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            flow.fetch_token(code=code)
    except Exception:
        return RedirectResponse(f"{base}/admin?tab=Email&gmail=error")
    creds = flow.credentials

    email = None
    try:
        from googleapiclient.discovery import build
        oa = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        email = oa.userinfo().get().execute().get("email")
    except Exception:
        pass

    update = {
        "key": "gmail", "access_token": creds.token, "email": email,
        "expires_at": creds.expiry.replace(tzinfo=timezone.utc).isoformat() if creds.expiry else None,
        "connected_at": now_utc_str(),
    }
    if creds.refresh_token:
        update["refresh_token"] = creds.refresh_token
    await db.settings.update_one({"key": "gmail"}, {"$set": update}, upsert=True)
    return RedirectResponse(f"{base}/admin?tab=Email&gmail=connected")


@router.get("/admin/gmail/status")
async def gmail_status(user: dict = Depends(require_roles("admin", "manager"))):
    cfg = await gm.get_config()
    return {"connected": bool(cfg and cfg.get("refresh_token")), "email": cfg.get("email") if cfg else None,
            "connected_at": cfg.get("connected_at") if cfg else None}


@router.post("/admin/gmail/disconnect")
async def gmail_disconnect(user: dict = Depends(require_roles("admin"))):
    await db.settings.delete_one({"key": "gmail"})
    return {"ok": True}


class TestEmail(BaseModel):
    to: str
    subject: str = "HomeIVF CRM — Test Email"
    body: str = "This is a test email sent from HomeIVF CRM via Gmail. If you received this, live email is working."


@router.post("/admin/gmail/send-test")
async def gmail_send_test(body: TestEmail, user: dict = Depends(require_roles("admin"))):
    if not await gm.is_connected():
        raise HTTPException(status_code=400, detail="Gmail not connected")
    res = await gm.send_email(body.to.strip(), body.subject, body.body)
    if not res.get("ok"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return res
