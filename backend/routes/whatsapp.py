import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user
from core.utils import next_id, now_utc_str

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


@router.get("/channels")
async def list_channels(search: Optional[str] = None, page: int = Query(1, ge=1), limit: int = Query(30, le=100),
                        user: dict = Depends(get_current_user)):
    q = {}
    if search:
        digits = re.sub(r"\D", "", search)
        ors = [{"name": {"$regex": re.escape(search), "$options": "i"}}]
        if digits and len(digits) >= 4:
            ors.append({"phone_digits": {"$regex": digits}})
        q["$or"] = ors
    total = await db.wa_channels.count_documents(q)
    items = await db.wa_channels.find(q, {"_id": 0}).sort("last_message_date", -1).skip((page - 1) * limit).limit(limit).to_list(limit)
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/channels/{channel_id}/messages")
async def channel_messages(channel_id: int, page: int = Query(1, ge=1), limit: int = Query(50, le=200),
                           user: dict = Depends(get_current_user)):
    q = {"channel_id": channel_id}
    total = await db.wa_messages.count_documents(q)
    items = await db.wa_messages.find(q, {"_id": 0}).sort([("date", -1), ("id", -1)]).skip((page - 1) * limit).limit(limit).to_list(limit)
    items.reverse()
    return {"items": items, "total": total, "page": page, "limit": limit}


class SendBody(BaseModel):
    body: str


@router.post("/channels/{channel_id}/send")
async def send_message(channel_id: int, body: SendBody, user: dict = Depends(get_current_user)):
    ch = await db.wa_channels.find_one({"id": channel_id})
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    mid = await next_id("wa_message")
    now = now_utc_str()
    msg = {
        "id": mid, "channel_id": channel_id, "body": body.body,
        "author_name": user["name"], "date": now, "message_type": "comment",
        "direction": "outbound", "status": "pending_api_credentials",
    }
    await db.wa_messages.insert_one(msg)
    await db.wa_channels.update_one({"id": channel_id}, {"$set": {"last_message_date": now}})
    await db.outbound_queue.insert_one({
        "channel": "whatsapp", "wa_channel_id": channel_id, "body": body.body,
        "status": "pending_api_credentials", "created_at": now, "user_id": user["id"],
    })
    msg.pop("_id", None)
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
