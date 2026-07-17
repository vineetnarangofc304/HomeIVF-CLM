import asyncio
import os
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt
from fastapi import HTTPException, Request

from core.db import db

JWT_ALGORITHM = "HS256"


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


async def hash_password_async(password: str) -> str:
    # bcrypt is CPU-bound (~100-300ms) and BLOCKS the single-worker event loop;
    # run it in a thread so a login / password change never stalls (503 / slow)
    # every other concurrent request on the pod.
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(plain: str, hashed: str) -> bool:
    return await asyncio.to_thread(verify_password, plain, hashed)


def create_access_token(user_id: int, email: str, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        "type": "access",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def set_auth_cookies(response, access_token: str, refresh_token: str = None):
    # SameSite=None so the cookie is sent on cross-site XHR (the frontend custom
    # domain calls the backend on a different domain). Requires Secure (set).
    response.set_cookie(
        key="access_token", value=access_token, httponly=True, secure=True,
        samesite="none", max_age=86400, path="/",
    )
    if refresh_token:
        response.set_cookie(
            key="refresh_token", value=refresh_token, httponly=True, secure=True,
            samesite="none", max_age=604800, path="/",
        )


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"id": int(payload["sub"])}, {"_id": 0, "password_hash": 0})
        if not user or not user.get("active", True):
            raise HTTPException(status_code=401, detail="User not found or inactive")
        from core.permissions import effective_permissions
        user["permissions"] = await effective_permissions(user["role"])
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_roles(*roles):
    async def checker(request: Request) -> dict:
        user = await get_current_user(request)
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker


def require_permission(perm: str):
    async def checker(request: Request) -> dict:
        user = await get_current_user(request)
        if not (user.get("permissions") or {}).get(perm, False):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker


def ensure_lead_edit(lead: dict, user: dict):
    """Record-level access control: everyone can VIEW any lead, but a caller may
    only MUTATE a lead assigned to them. Admins & managers are unrestricted.
    Raises 403 'Access Denied' otherwise. Call after fetching the lead."""
    if user.get("role") == "caller" and lead.get("user_id") != user.get("id"):
        raise HTTPException(
            status_code=403,
            detail="Access Denied — this lead is assigned to another caller. Only the assigned caller can make changes.",
        )
