import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user, require_roles
from core.utils import log_message, next_id, now_utc_str, run_automations, to_ist_str, today_ist

router = APIRouter(prefix="/leads", tags=["leads"])

LIST_PROJECTION = {
    "_id": 0, "id": 1, "name": 1, "contact_name": 1, "phone": 1, "email_from": 1,
    "city": 1, "state_name": 1, "lead_stage": 1, "stage_id": 1, "tags": 1, "user_id": 1,
    "create_date": 1, "create_date_ist": 1, "follow_up_date": 1, "follow_up_tag": 1,
    "source_lead": 1, "campaign_name": 1, "ads_platform": 1, "priority": 1, "active": 1,
    "probability": 1, "appointment_date": 1, "lost_reason_id": 1,
}

EDITABLE_FIELDS = {
    "name", "contact_name", "phone", "mobile", "email_from", "city", "state_name",
    "stage_id", "lead_stage", "tags", "user_id", "follow_up_date", "follow_up_tag",
    "appointment_date", "source_lead", "campaign_name", "ads_platform", "ads_campaign_name",
    "ads_name", "description", "priority", "gender", "age", "male_age", "female_age",
    "spouse_name", "spouse_age", "spouse_alternate_no", "query", "remark", "pre_conditions",
    "doctor_name", "lost_reason_id", "custom",
}

TRACKED = ["stage_id", "lead_stage", "user_id", "tags", "follow_up_date", "follow_up_tag", "lost_reason_id"]


def build_query(
    search=None, stage_id=None, lead_stage=None, tags=None, user_id=None,
    source_lead=None, campaign_name=None, ads_platform=None, city=None, state_name=None,
    active="true", date_from=None, date_to=None, follow_up=None, priority=None,
    current_user=None,
):
    q = {}
    if active == "true":
        q["active"] = True
    elif active == "false":
        q["active"] = False
    if search:
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        digits = re.sub(r"\D", "", search)
        ors = [{"name": rx}, {"contact_name": rx}, {"email_from": rx}]
        if digits and len(digits) >= 4:
            ors.append({"phone_digits": {"$regex": digits}})
        else:
            ors.append({"phone": rx})
        q["$or"] = ors
    if stage_id:
        q["stage_id"] = int(stage_id)
    if lead_stage == "__none__":
        q["lead_stage"] = {"$in": [None, False, ""]}
    elif lead_stage:
        q["lead_stage"] = {"$in": lead_stage.split(",")} if "," in lead_stage else lead_stage
    if tags:
        q["tags"] = {"$in": [int(t) for t in tags.split(",") if t]}
    if user_id == "none":
        q["user_id"] = {"$in": [None, False]}
    elif user_id:
        q["user_id"] = int(user_id)
    if source_lead:
        q["source_lead"] = source_lead
    if campaign_name:
        q["campaign_name"] = {"$regex": re.escape(campaign_name), "$options": "i"}
    if ads_platform:
        q["ads_platform"] = {"$regex": re.escape(ads_platform), "$options": "i"}
    if city:
        q["city"] = {"$regex": re.escape(city), "$options": "i"}
    if state_name:
        q["state_name"] = {"$regex": re.escape(state_name), "$options": "i"}
    if priority:
        q["priority"] = priority
    if date_from:
        q.setdefault("create_date_ist", {})["$gte"] = date_from
    if date_to:
        q.setdefault("create_date_ist", {})["$lte"] = date_to + " 23:59:59"
    today = today_ist()
    if follow_up == "today":
        q["follow_up_date"] = today
    elif follow_up == "overdue":
        q["follow_up_date"] = {"$lt": today, "$gt": ""}
    elif follow_up == "upcoming":
        q["follow_up_date"] = {"$gt": today}
    elif follow_up == "set":
        q["follow_up_date"] = {"$gt": ""}
    # callers only see their own leads
    if current_user and current_user.get("role") == "caller":
        q["user_id"] = current_user["id"]
    return q


def query_params_dep(
    search: Optional[str] = None, stage_id: Optional[str] = None,
    lead_stage: Optional[str] = None, tags: Optional[str] = None,
    user_id: Optional[str] = None, source_lead: Optional[str] = None,
    campaign_name: Optional[str] = None, ads_platform: Optional[str] = None,
    city: Optional[str] = None, state_name: Optional[str] = None,
    active: str = "true", date_from: Optional[str] = None, date_to: Optional[str] = None,
    follow_up: Optional[str] = None, priority: Optional[str] = None,
):
    return dict(
        search=search, stage_id=stage_id, lead_stage=lead_stage, tags=tags, user_id=user_id,
        source_lead=source_lead, campaign_name=campaign_name, ads_platform=ads_platform,
        city=city, state_name=state_name, active=active, date_from=date_from, date_to=date_to,
        follow_up=follow_up, priority=priority,
    )


@router.get("")
async def list_leads(
    params: dict = Depends(query_params_dep),
    page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
    sort: str = "create_date", order: str = "desc",
    user: dict = Depends(get_current_user),
):
    q = build_query(**params, current_user=user)
    sort_dir = -1 if order == "desc" else 1
    total = await db.leads.count_documents(q)
    cursor = db.leads.find(q, LIST_PROJECTION).sort([(sort, sort_dir), ("id", -1)]).skip((page - 1) * limit).limit(limit)
    items = await cursor.to_list(limit)
    return {"items": items, "total": total, "page": page, "limit": limit}


GROUP_FIELDS = {
    "user_id": "$user_id", "lead_stage": "$lead_stage", "stage_id": "$stage_id",
    "source_lead": "$source_lead", "follow_up_tag": "$follow_up_tag",
    "ads_platform": "$ads_platform", "campaign_name": "$campaign_name",
    "city": "$city", "state_name": "$state_name", "priority": "$priority",
    "create_date:day": {"$substrCP": ["$create_date_ist", 0, 10]},
    "create_date:month": {"$substrCP": ["$create_date_ist", 0, 7]},
}


@router.get("/group_counts")
async def group_counts(
    group_by: str = "lead_stage",
    params: dict = Depends(query_params_dep),
    user: dict = Depends(get_current_user),
):
    q = build_query(**params, current_user=user)
    pipeline = [{"$match": q}]
    if group_by == "tags":
        pipeline += [{"$unwind": {"path": "$tags", "preserveNullAndEmptyArrays": True}},
                     {"$group": {"_id": "$tags", "count": {"$sum": 1}}}]
    elif group_by in GROUP_FIELDS:
        pipeline += [{"$group": {"_id": GROUP_FIELDS[group_by], "count": {"$sum": 1}}}]
    else:
        raise HTTPException(status_code=400, detail="Unsupported group_by")
    pipeline += [{"$sort": {"count": -1}}, {"$limit": 200}]
    rows = await db.leads.aggregate(pipeline).to_list(200)
    return [{"key": r["_id"], "count": r["count"]} for r in rows]


@router.get("/{lead_id}")
async def get_lead(lead_id: int, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


class LeadCreate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email_from: Optional[str] = None
    city: Optional[str] = None
    state_name: Optional[str] = None
    user_id: Optional[int] = None
    lead_stage: Optional[str] = None
    tags: Optional[list] = None
    source_lead: Optional[str] = None
    description: Optional[str] = None
    follow_up_date: Optional[str] = None
    follow_up_tag: Optional[str] = None
    gender: Optional[str] = None
    male_age: Optional[str] = None
    female_age: Optional[str] = None
    query: Optional[str] = None


@router.post("")
async def create_lead(body: LeadCreate, user: dict = Depends(get_current_user)):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not data.get("name"):
        data["name"] = data.get("contact_name") or data.get("phone") or "New Lead"
    lid = await next_id("lead")
    now = now_utc_str()
    doc = {
        "id": lid, "active": True, "stage_id": 1, "type": "lead", "priority": "0",
        "tags": data.pop("tags", []), "create_date": now, "create_date_ist": to_ist_str(now),
        "write_date": now, "create_uid": user["id"], "custom": {},
        "phone_digits": re.sub(r"\D", "", data.get("phone") or "")[-10:],
        **data,
    }
    await db.leads.insert_one(doc)
    await log_message(lid, f"Lead created by {user['name']}", author=user)
    await run_automations("on_create", doc)
    doc.pop("_id", None)
    return doc


class LeadUpdate(BaseModel):
    updates: dict


async def _track_changes(lead, updates, user):
    parts = []
    for f in TRACKED:
        if f in updates and updates[f] != lead.get(f):
            old, new = lead.get(f), updates[f]
            if f == "tags":
                old_set, new_set = set(old or []), set(new or [])
                added, removed = new_set - old_set, old_set - new_set
                names = {t["id"]: t["name"] for t in await db.catalogs.find({"type": "tag"}, {"_id": 0}).to_list(500)}
                if added:
                    parts.append("Tags added: " + ", ".join(names.get(t, str(t)) for t in added))
                if removed:
                    parts.append("Tags removed: " + ", ".join(names.get(t, str(t)) for t in removed))
            elif f == "user_id":
                users = {u["id"]: u["name"] for u in await db.users.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)}
                parts.append(f"Assigned: {users.get(old, old or 'None')} → {users.get(new, new or 'None')}")
            elif f == "stage_id":
                stages = {s["id"]: s["name"] for s in await db.catalogs.find({"type": "stage"}, {"_id": 0}).to_list(50)}
                parts.append(f"Pipeline stage: {stages.get(old, old or 'None')} → {stages.get(new, new or 'None')}")
            else:
                parts.append(f"{f.replace('_', ' ').title()}: {old or 'None'} → {new or 'None'}")
    if parts:
        await log_message(lead["id"], "<br/>".join(parts), author=user)


@router.patch("/{lead_id}")
async def update_lead(lead_id: int, body: LeadUpdate, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    updates = {k: v for k, v in body.updates.items() if k in EDITABLE_FIELDS}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    if "custom" in updates and isinstance(updates["custom"], dict):
        merged = dict(lead.get("custom") or {})
        merged.update(updates["custom"])
        updates["custom"] = merged
    if "phone" in updates:
        updates["phone_digits"] = re.sub(r"\D", "", updates.get("phone") or "")[-10:]
    await _track_changes(lead, updates, user)
    updates["write_date"] = now_utc_str()
    updates["write_uid"] = user["id"]
    await db.leads.update_one({"id": lead_id}, {"$set": updates})
    new_lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if "stage_id" in updates and updates["stage_id"] != lead.get("stage_id"):
        await run_automations("on_stage_set", new_lead)
    if "tags" in updates:
        added = list(set(updates["tags"] or []) - set(lead.get("tags") or []))
        if added:
            await run_automations("on_tag_set", new_lead, {"added_tags": added})
    return new_lead


class LostBody(BaseModel):
    lost_reason_id: Optional[int] = None
    note: Optional[str] = None


@router.post("/{lead_id}/lost")
async def mark_lost(lead_id: int, body: LostBody, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    await db.leads.update_one({"id": lead_id}, {"$set": {
        "active": False, "lost_reason_id": body.lost_reason_id,
        "date_closed": now_utc_str(), "probability": 0,
    }})
    reason = ""
    if body.lost_reason_id:
        r = await db.catalogs.find_one({"type": "lost_reason", "id": body.lost_reason_id})
        reason = f" — Reason: {r['name']}" if r else ""
    await log_message(lead_id, f"Lead marked as Lost{reason}{('<br/>' + body.note) if body.note else ''}", author=user)
    return {"ok": True}


@router.post("/{lead_id}/restore")
async def restore_lead(lead_id: int, user: dict = Depends(get_current_user)):
    await db.leads.update_one({"id": lead_id}, {"$set": {"active": True, "lost_reason_id": None}})
    await log_message(lead_id, "Lead restored", author=user)
    return {"ok": True}


class BulkBody(BaseModel):
    ids: list
    action: str
    payload: dict = {}


@router.post("/bulk")
async def bulk_action(body: BulkBody, user: dict = Depends(require_roles("admin", "manager"))):
    ids = [int(i) for i in body.ids]
    q = {"id": {"$in": ids}}
    p = body.payload
    if body.action == "assign":
        await db.leads.update_many(q, {"$set": {"user_id": int(p["user_id"])}})
    elif body.action == "add_tags":
        await db.leads.update_many(q, {"$addToSet": {"tags": {"$each": [int(t) for t in p["tags"]]}}})
    elif body.action == "remove_tags":
        await db.leads.update_many(q, {"$pull": {"tags": {"$in": [int(t) for t in p["tags"]]}}})
    elif body.action == "set_stage":
        await db.leads.update_many(q, {"$set": {"stage_id": int(p["stage_id"])}})
    elif body.action == "set_lead_stage":
        await db.leads.update_many(q, {"$set": {"lead_stage": p["lead_stage"]}})
    elif body.action == "archive":
        await db.leads.update_many(q, {"$set": {"active": False}})
    elif body.action == "restore":
        await db.leads.update_many(q, {"$set": {"active": True}})
    elif body.action == "set_follow_up":
        await db.leads.update_many(q, {"$set": {"follow_up_date": p.get("follow_up_date"), "follow_up_tag": p.get("follow_up_tag")}})
    else:
        raise HTTPException(status_code=400, detail="Unknown action")
    return {"ok": True, "count": len(ids)}
