"""Case 5 — WhatsApp template message tracking API.

Every outbound template message is stored in `wa_tracking` and updated from Meta
status webhooks. These endpoints power the template summary box, the message-list
page and the individual message detail page (with lifecycle status).
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from core.db import db
from core.security import get_current_user
from core.utils import WA_STATUS_FLOW

router = APIRouter(prefix="/wa", tags=["wa-tracking"])


@router.get("/template/{template_id}/summary")
async def template_summary(template_id: int, user: dict = Depends(get_current_user)):
    total = await db.wa_tracking.count_documents({"template_id": template_id})
    rows = await db.wa_tracking.aggregate([
        {"$match": {"template_id": template_id}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]).to_list(50)
    by_status = {r["_id"]: r["count"] for r in rows}
    return {"template_id": template_id, "total": total, "by_status": by_status}


@router.get("/template/{template_id}/messages")
async def template_messages(template_id: int, page: int = Query(1, ge=1),
                            limit: int = Query(50, ge=1, le=200), user: dict = Depends(get_current_user)):
    q = {"template_id": template_id}
    total = await db.wa_tracking.count_documents(q)
    items = await db.wa_tracking.find(q, {"_id": 0}).sort("id", -1).skip((page - 1) * limit).limit(limit).to_list(limit)
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/message/{track_id}")
async def message_detail(track_id: int, user: dict = Depends(get_current_user)):
    doc = await db.wa_tracking.find_one({"id": track_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Message not found")
    lead = await db.leads.find_one({"id": doc.get("lead_id")}, {"_id": 0, "id": 1, "name": 1, "contact_name": 1})
    doc["lead"] = lead
    doc["flow"] = WA_STATUS_FLOW
    return doc


@router.get("/lead/{lead_id}/messages")
async def lead_messages(lead_id: int, user: dict = Depends(get_current_user)):
    return await db.wa_tracking.find({"lead_id": lead_id}, {"_id": 0}).sort("id", -1).limit(50).to_list(50)
