import re
import uuid
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request, Header
from fastapi.responses import Response
from pymongo.errors import PyMongoError
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user, get_jwt_secret, JWT_ALGORITHM
from core.storage import put_object, get_object, APP_NAME
from core.utils import next_id, now_utc_str, log_message, ensure_catalog, run_automations
from core import whatsapp_cloud as wac

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


def _media_kind(ctype: str) -> str:
    ct = (ctype or "").lower()
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("video/"):
        return "video"
    if ct.startswith("audio/"):
        return "audio"
    return "document"


@router.post("/media/upload")
async def upload_wa_media(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Upload an attachment: stores a CRM-viewable copy + uploads to Meta for sending."""
    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 25MB)")
    ctype = file.content_type or "application/octet-stream"
    kind = _media_kind(ctype)
    ext = (file.filename.rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "bin")
    path = f"{APP_NAME}/wa/{uuid.uuid4()}.{ext}"
    try:
        result = await put_object(path, data, ctype)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upload failed: {e}")
    media_id = None
    if await wac.is_configured():
        up = await wac.upload_media(data, ctype)
        media_id = up.get("id") if up.get("ok") else None
    return {"ok": True, "storage_path": result["path"], "media_id": media_id,
            "media_type": kind, "media_name": file.filename, "content_type": ctype,
            "media_url": f"/api/whatsapp/media?path={result['path']}"}


@router.get("/media")
async def serve_wa_media(path: str, request: Request, auth: Optional[str] = Query(None),
                         authorization: Optional[str] = Header(None)):
    token = request.cookies.get("access_token") or auth
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not path.startswith(f"{APP_NAME}/wa/"):
        raise HTTPException(status_code=400, detail="Invalid media path")
    try:
        content, ctype = await get_object(path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Fetch failed: {e}")
    return Response(content=content, media_type=ctype, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/channels")
async def list_channels(search: Optional[str] = None, filter: str = Query("all"),
                        page: int = Query(1, ge=1), limit: int = Query(30, le=100),
                        user: dict = Depends(get_current_user)):
    q = {}
    # Case 1 — callers see only chats for leads assigned to them; admin & manager see all.
    if user.get("role") == "caller":
        q["owner_id"] = user["id"]
    if search:
        digits = re.sub(r"\D", "", search)
        ors = [{"name": {"$regex": re.escape(search), "$options": "i"}}]
        if digits and len(digits) >= 4:
            ors.append({"phone_digits": {"$regex": digits}})
        q["$or"] = ors
    if filter == "unread":
        q["unread_count"] = {"$gt": 0}
    elif filter == "interested":
        q["category"] = "interested"
    total = await db.wa_channels.count_documents(q)
    items = await db.wa_channels.find(q, {"_id": 0}).sort([("last_message_date", -1)]).skip((page - 1) * limit).limit(limit).to_list(limit)
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/unread-summary")
async def unread_summary(user: dict = Depends(get_current_user)):
    """Powers the floating 'new WhatsApp message' notification panel."""
    # Case 1 — callers only get unread counts for chats they own.
    scope = {"unread_count": {"$gt": 0}}
    if user.get("role") == "caller":
        scope["owner_id"] = user["id"]
    # Fail-fast: polled every ~30s by all callers. If Atlas is slow, abort quickly and return
    # zeros so the poll releases its pooled connection instead of piling up (pool-exhaustion guard).
    try:
        total = await db.wa_channels.aggregate([
            {"$match": scope},
            {"$group": {"_id": None, "n": {"$sum": "$unread_count"}, "chats": {"$sum": 1}}},
        ], maxTimeMS=4000).to_list(1)
        total_unread = total[0]["n"] if total else 0
        chats = total[0]["chats"] if total else 0
        recent = await db.wa_channels.find(scope, {"_id": 0, "id": 1, "name": 1, "last_message_date": 1, "unread_count": 1}).sort("last_message_date", -1).limit(8).max_time_ms(4000).to_list(8)
    except PyMongoError:
        return {"total_unread": 0, "unread_chats": 0, "recent": []}
    return {"total_unread": total_unread, "unread_chats": chats, "recent": recent}


@router.get("/channels/{channel_id}/messages")
async def channel_messages(channel_id: int, search: Optional[str] = None, starred: Optional[bool] = None,
                           page: int = Query(1, ge=1), limit: int = Query(50, le=200),
                           user: dict = Depends(get_current_user)):
    q = {"channel_id": channel_id}
    if search:
        q["body"] = {"$regex": re.escape(search), "$options": "i"}
    if starred:
        q["starred"] = True
    total = await db.wa_messages.count_documents(q)
    items = await db.wa_messages.find(q, {"_id": 0}).sort([("date", -1), ("id", -1)]).skip((page - 1) * limit).limit(limit).to_list(limit)
    items.reverse()
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.post("/channels/{channel_id}/read")
async def mark_read(channel_id: int, user: dict = Depends(get_current_user)):
    await db.wa_channels.update_one({"id": channel_id}, {"$set": {"unread_count": 0}})
    return {"ok": True}


class CategoryBody(BaseModel):
    category: Optional[str] = None  # "interested" | None


@router.post("/channels/{channel_id}/category")
async def set_category(channel_id: int, body: CategoryBody, user: dict = Depends(get_current_user)):
    ch = await db.wa_channels.find_one({"id": channel_id})
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    cat = (body.category or "").strip() or None
    await db.wa_channels.update_one({"id": channel_id}, {"$set": {"category": cat}})
    # Moving to "Interested Customer" tags the linked lead + advances stage so it flows into the pipeline/reports.
    if cat == "interested":
        digits = re.sub(r"\D", "", ch.get("phone_digits") or "")[-10:]
        if len(digits) >= 8:
            lead = await db.leads.find_one({"phone_digits": digits}, sort=[("write_date", -1)])
            if lead:
                tag = await ensure_catalog("tag", "Interested")
                tags = set(lead.get("tags") or [])
                if tag.get("id"):
                    tags.add(tag["id"])
                await db.leads.update_one({"id": lead["id"]}, {"$set": {"tags": list(tags), "lead_stage": "Contacted", "write_date": now_utc_str()}})
                await log_message(lead["id"], "⭐ Marked as <b>Interested Customer</b> from WhatsApp chat", author=user, subtype="comment")
                lead["tags"] = list(tags)
                if tag.get("id"):
                    await run_automations("on_tag_set", lead, extra={"added_tags": [tag["id"]]})
    return {"ok": True, "category": cat}


class MsgAction(BaseModel):
    emoji: Optional[str] = None


@router.post("/messages/{message_id}/star")
async def toggle_star(message_id: int, user: dict = Depends(get_current_user)):
    m = await db.wa_messages.find_one({"id": message_id}, {"_id": 0, "starred": 1})
    if m is None:
        raise HTTPException(status_code=404, detail="Message not found")
    new_val = not m.get("starred")
    await db.wa_messages.update_one({"id": message_id}, {"$set": {"starred": new_val}})
    return {"ok": True, "starred": new_val}


@router.post("/messages/{message_id}/pin")
async def toggle_pin(message_id: int, user: dict = Depends(get_current_user)):
    m = await db.wa_messages.find_one({"id": message_id}, {"_id": 0, "pinned": 1, "channel_id": 1})
    if m is None:
        raise HTTPException(status_code=404, detail="Message not found")
    new_val = not m.get("pinned")
    await db.wa_messages.update_one({"id": message_id}, {"$set": {"pinned": new_val}})
    return {"ok": True, "pinned": new_val}


@router.post("/messages/{message_id}/react")
async def react_message(message_id: int, body: MsgAction, user: dict = Depends(get_current_user)):
    m = await db.wa_messages.find_one({"id": message_id})
    if not m:
        raise HTTPException(status_code=404, detail="Message not found")
    emoji = (body.emoji or "").strip()
    await db.wa_messages.update_one({"id": message_id}, {"$set": {"reaction": emoji or None}})
    # If configured & we have the customer number + wamid, send the reaction to Meta.
    ch = await db.wa_channels.find_one({"id": m.get("channel_id")}, {"_id": 0, "phone_digits": 1})
    if ch and ch.get("phone_digits") and m.get("wamid") and await wac.is_configured():
        try:
            await wac.send_reaction(ch["phone_digits"], m["wamid"], emoji)
        except Exception:
            pass
    return {"ok": True, "reaction": emoji or None}


class SendBody(BaseModel):
    body: str = ""
    reply_to: Optional[int] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None  # image | video | document
    media_id: Optional[str] = None
    media_name: Optional[str] = None


@router.post("/channels/{channel_id}/send")
async def send_message(channel_id: int, body: SendBody, user: dict = Depends(get_current_user)):
    ch = await db.wa_channels.find_one({"id": channel_id})
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    mid = await next_id("wa_message")
    now = now_utc_str()
    status = "pending_api_credentials"
    wamid = None
    err = None
    reply_snip = None
    if body.reply_to:
        r = await db.wa_messages.find_one({"id": body.reply_to}, {"_id": 0, "body": 1, "author_name": 1})
        if r:
            reply_snip = {"author": r.get("author_name"), "body": (r.get("body") or "")[:120]}
    if await wac.is_configured() and ch.get("phone_digits"):
        if body.media_url or body.media_id:
            res = await wac.send_media(ch["phone_digits"], body.media_type or "document",
                                       media_id=body.media_id, caption=body.body or "", filename=body.media_name or "")
        else:
            res = await wac.send_text(ch["phone_digits"], body.body)
        if res.get("ok"):
            status, wamid = "sent", res.get("wamid")
        else:
            status = "failed"
            err = res.get("error")
    msg = {
        "id": mid, "channel_id": channel_id, "body": body.body,
        "author_name": user["name"], "date": now, "message_type": "comment",
        "direction": "outbound", "status": status, "wamid": wamid, "error": err,
        "reply_to": reply_snip, "media_url": body.media_url, "media_type": body.media_type,
        "media_name": body.media_name,
    }
    await db.wa_messages.insert_one(msg)
    await db.wa_channels.update_one({"id": channel_id}, {"$set": {"last_message_date": now}})
    if status == "pending_api_credentials":
        await db.outbound_queue.insert_one({
            "channel": "whatsapp", "wa_channel_id": channel_id, "body": body.body,
            "status": status, "created_at": now, "user_id": user["id"],
        })
    msg.pop("_id", None)
    if status == "failed":
        raise HTTPException(status_code=400, detail=err or "WhatsApp send failed. Free-text replies are only allowed within 24 hours of the customer's last message — send an approved template instead.")
    return msg


@router.get("/lead/{lead_id}")
async def channels_for_lead(lead_id: int, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0, "phone_digits": 1})
    if not lead or not lead.get("phone_digits"):
        return []
    digits = lead["phone_digits"]
    if len(digits) < 8:
        return []
    items = await db.wa_channels.find({"phone_digits": {"$regex": digits + "$"}}, {"_id": 0}).limit(5).to_list(5)
    return items
