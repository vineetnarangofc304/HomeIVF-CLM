"""Gmail API email sending via Google OAuth 2.0 (Case 14/17 — live email)."""
import os

# Google returns scopes in a different order and adds the `email` alias to the
# granted set, which makes oauthlib raise "Scope has changed" during token
# exchange. Relaxing these flags lets the token exchange succeed. Must be set
# before oauthlib performs the exchange (module import time is safe).
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
os.environ.setdefault("OAUTHLIB_IGNORE_SCOPE_CHANGE", "1")

import base64
import warnings
from datetime import datetime, timezone
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from core.db import db

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


def _client_config():
    return {
        "web": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def redirect_uri() -> str:
    return os.environ["GMAIL_REDIRECT_URI"]


def make_flow(redirect: str | None = None) -> Flow:
    return Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect or redirect_uri())


async def get_config() -> dict | None:
    return await db.settings.find_one({"key": "gmail"}, {"_id": 0})


async def is_connected() -> bool:
    cfg = await get_config()
    return bool(cfg and cfg.get("refresh_token"))


async def _creds() -> Credentials:
    cfg = await get_config()
    if not cfg or not cfg.get("refresh_token"):
        raise RuntimeError("Gmail not connected")
    creds = Credentials(
        token=cfg.get("access_token"),
        refresh_token=cfg["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    creds.refresh(GoogleRequest())
    await db.settings.update_one({"key": "gmail"}, {"$set": {
        "access_token": creds.token,
        "expires_at": creds.expiry.replace(tzinfo=timezone.utc).isoformat() if creds.expiry else None,
    }})
    return creds


async def send_email(to: str, subject: str, body: str, html: bool = False) -> dict:
    try:
        creds = await _creds()
        cfg = await get_config()
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        msg = MIMEText(body or "", "html" if html else "plain", "utf-8")
        msg["to"] = to
        msg["from"] = cfg.get("email") or "me"
        msg["subject"] = subject or "(no subject)"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"ok": True, "id": sent.get("id")}
    except Exception as e:
        return {"ok": False, "error": str(e)}
