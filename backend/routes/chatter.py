from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user
from core.utils import log_message, next_id, now_utc_str, today_ist

router = APIRouter(tags=["chatter"])


@router.get("/leads/{lead_id}/messages")
async def list_messages(lead_id: int, page: int = Query(1, ge=1), limit: int = Query(30, ge=1, le=100),
                        user: dict = Depends(get_current_user)):
    q = {"lead_id": lead_id}
    total = await db.messages.count_documents(q)
    items = await db.messages.find(q, {"_id": 0}).sort([("date", -1), ("id", -1)]).skip((page - 1) * limit).limit(limit).to_list(limit)
    return {"items": items, "total": total, "page": page, "limit": limit}


class MessageBody(BaseModel):
    body: str
    subtype: str = "note"  # note | comment


@router.post("/leads/{lead_id}/messages")
async def post_message(lead_id: int, body: MessageBody, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    msg = await log_message(lead_id, body.body, author=user, subtype=body.subtype if body.subtype in ("note", "comment") else "note")
    return msg


class ActivityCreate(BaseModel):
    type_name: str = "Call"
    summary: Optional[str] = None
    note: Optional[str] = None
    date_deadline: str
    user_id: Optional[int] = None


@router.get("/leads/{lead_id}/activities")
async def lead_activities(lead_id: int, user: dict = Depends(get_current_user)):
    items = await db.activities.find({"lead_id": lead_id, "state": "scheduled"}, {"_id": 0}).sort("date_deadline", 1).to_list(100)
    return items


@router.post("/leads/{lead_id}/activities")
async def create_activity(lead_id: int, body: ActivityCreate, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    aid = await next_id("activity")
    doc = {
        "id": aid, "lead_id": lead_id, "lead_name": lead.get("name"),
        "type_name": body.type_name, "summary": body.summary, "note": body.note,
        "date_deadline": body.date_deadline, "user_id": body.user_id or user["id"],
        "state": "scheduled", "created_at": now_utc_str(), "create_uid": user["id"],
    }
    await db.activities.insert_one(doc)
    await log_message(lead_id, f"Activity scheduled: {body.type_name} on {body.date_deadline}" + (f" — {body.summary}" if body.summary else ""), author=user)
    doc.pop("_id", None)
    return doc


class ActivityDone(BaseModel):
    feedback: Optional[str] = None


@router.post("/activities/{activity_id}/done")
async def mark_done(activity_id: int, body: ActivityDone, user: dict = Depends(get_current_user)):
    act = await db.activities.find_one({"id": activity_id})
    if not act:
        raise HTTPException(status_code=404, detail="Activity not found")
    await db.activities.update_one({"id": activity_id}, {"$set": {"state": "done", "done_date": now_utc_str(), "feedback": body.feedback}})
    await log_message(act["lead_id"], f"Activity done: {act['type_name']}" + (f" — {body.feedback}" if body.feedback else ""), author=user)
    return {"ok": True}


@router.post("/activities/{activity_id}/cancel")
async def cancel_activity(activity_id: int, user: dict = Depends(get_current_user)):
    act = await db.activities.find_one({"id": activity_id})
    if not act:
        raise HTTPException(status_code=404, detail="Activity not found")
    await db.activities.update_one({"id": activity_id}, {"$set": {"state": "canceled"}})
    return {"ok": True}


@router.get("/activities")
async def my_activities(scope: str = "my", when: str = "all", page: int = 1, limit: int = Query(50, le=200),
                        user: dict = Depends(get_current_user)):
    q = {"state": "scheduled"}
    if scope == "my" or user["role"] == "caller":
        q["user_id"] = user["id"]
    today = today_ist()
    if when == "today":
        q["date_deadline"] = today
    elif when == "overdue":
        q["date_deadline"] = {"$lt": today}
    elif when == "upcoming":
        q["date_deadline"] = {"$gt": today}
    total = await db.activities.count_documents(q)
    items = await db.activities.find(q, {"_id": 0}).sort("date_deadline", 1).skip((page - 1) * limit).limit(limit).to_list(limit)
    return {"items": items, "total": total}
