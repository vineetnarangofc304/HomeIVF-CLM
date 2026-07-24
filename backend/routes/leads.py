import asyncio
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.errors import PyMongoError

IST = timezone(timedelta(hours=5, minutes=30))
from pydantic import BaseModel

from core.db import db, db_analytics
from core.security import get_current_user, require_roles, ensure_lead_edit
from core.utils import log_message, log_audit, next_id, now_utc_str, run_automations, to_ist_str, ist_date_parts, today_ist, check_duplicate, record_wa_outbound, search_norm, sync_channel_owner
from core import whatsapp_cloud as wac

router = APIRouter(prefix="/leads", tags=["leads"])

LIST_PROJECTION = {
    "_id": 0, "id": 1, "name": 1, "contact_name": 1, "phone": 1, "email_from": 1,
    "city": 1, "state_name": 1, "lead_stage": 1, "stage_id": 1, "tags": 1, "user_id": 1,
    "create_date": 1, "create_date_ist": 1, "follow_up_date": 1, "follow_up_time": 1, "follow_up_tag": 1,
    "follow_up_status": 1, "alternate_number": 1,
    "source_lead": 1, "campaign_name": 1, "ads_platform": 1, "priority": 1, "active": 1,
    "probability": 1, "appointment_date": 1, "lost_reason_id": 1, "is_duplicate": 1, "duplicate_of": 1,
    "ozonetel_lead": 1, "in_pipeline": 1, "conversion_page": 1,
}

EDITABLE_FIELDS = {
    "name", "contact_name", "phone", "mobile", "alternate_number", "email_from", "city", "state_name",
    "country", "street",
    "stage_id", "lead_stage", "tags", "user_id", "follow_up_date", "follow_up_time", "follow_up_tag",
    "appointment_date", "appointment_time", "source_lead", "campaign_name", "ads_platform", "ads_campaign_name",
    "ads_name", "description", "priority", "gender", "age", "male_age", "female_age",
    "spouse_name", "spouse_age", "spouse_alternate_no", "query", "remark", "pre_conditions",
    "doctor_name", "lost_reason_id", "custom", "conversion_page",
    "source_id", "medium_id", "campaign_id",
}

TRACKED = ["stage_id", "lead_stage", "user_id", "tags", "follow_up_date", "follow_up_tag", "lost_reason_id",
           "name", "contact_name", "phone", "alternate_number", "email_from", "city", "state_name", "priority"]


def build_query(
    search=None, stage_id=None, lead_stage=None, tags=None, user_id=None,
    source_lead=None, campaign_name=None, ads_platform=None, city=None, state_name=None,
    active="true", date_from=None, date_to=None, follow_up=None, priority=None,
    follow_up_tag=None, lost_reason_id=None, bucket=None, duplicate=None, scope=None,
    current_user=None,
):
    q = {}
    # When SEARCHING (Case 1 — find ANY customer by number/name), do NOT restrict to a single
    # bucket: a caller must be able to pull up a customer whether they are a pipeline lead OR a
    # raw (un-promoted) Ozonetel lead. The bucket tabs only scope the DEFAULT (non-search) list.
    if not search:
        if bucket == "ozonetel":
            # Raw (un-promoted) Ozonetel leads carry pipeline=False — uses the same indexed
            # {active,pipeline,create_date,id} plan as the pipeline tab (was an unindexed scan).
            q["pipeline"] = False
        elif bucket == "pipeline":
            # Indexed & sort-friendly: everything EXCEPT raw (un-promoted) Ozonetel leads,
            # which carry pipeline=False. Leads without the field (pre-backfill) still match
            # via $ne, so nothing vanishes during the one-time backfill window. This replaces
            # the old $or/$ne filter that couldn't use the sort-covering index → blocking
            # in-memory SORT over ~100k docs → slow / 500 ("Sort exceeded memory limit").
            q["pipeline"] = {"$ne": False}
    if active == "true":
        q["active"] = True
    elif active == "false":
        q["active"] = False
    if search:
        s = search.strip()
        digits = re.sub(r"\D", "", s)
        non_phone = re.sub(r"[\d\s+\-()]", "", s)
        if digits and len(digits) >= 4 and non_phone == "":
            # Pure phone query → hit ONLY the indexed phone_digits (exact for a full
            # 10-digit number, else prefix). No name-regex branches, so it stays instant.
            d10 = digits[-10:]
            q["phone_digits"] = d10 if len(digits) >= 10 else {"$regex": "^" + re.escape(d10)}
        else:
            # Text query: prefix ('starts with') match on the LOWERCASED name/email
            # fields with a CASE-SENSITIVE anchored regex → tight index bounds
            # (keysExamined≈matches, ~0ms). A case-insensitive ($options:i) regex can NOT
            # use index bounds, so the old version scanned all ~120k docs per search,
            # exhausting the DB connection pool → intermittent 500s (incl. on login).
            pfx = {"$regex": "^" + re.escape(s.lower())}
            ors = [{"name_lc": pfx}, {"contact_name_lc": pfx}, {"email_lc": pfx}]
            if digits and len(digits) >= 4:
                d10 = digits[-10:]
                ors.append({"phone_digits": d10} if len(digits) >= 10 else {"phone_digits": {"$regex": "^" + re.escape(d10)}})
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
    if follow_up_tag:
        q["follow_up_tag"] = follow_up_tag
    if lost_reason_id:
        q["lost_reason_id"] = int(lost_reason_id)
    if duplicate == "true":
        q["is_duplicate"] = True
        q.pop("active", None)  # duplicates are usually archived/merged — show all regardless of active
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
    # Case 1 access model: a caller can reach ANY lead — global SEARCH is unscoped (find any
    # customer by number/name across all buckets), opening/editing by id is unscoped, and the
    # "All leads" toggle (scope=all) or a colleague filter (user_id=<id>) shows other callers'
    # leads on demand. But the DEFAULT list is scoped to the caller's OWN book. This is a hard
    # PERFORMANCE / STABILITY requirement, not just an operational nicety: 24 callers each
    # scanning the full ~120k collection on every list load + poll saturates the shared DB
    # connection pool → the production 504/500 cascade (/api/leads at 30s, and every other
    # endpoint failing behind it). A caller's ~5k own set is a tiny index-covered query.
    # Scope resolution for the My-leads / All-leads tabs (see build_query callers):
    #  - a SEARCH is always global (Case 1: find ANY customer by number/name) → no scoping
    #  - an explicit colleague filter (user_id=<id>) wins over any scope
    #  - scope=mine → this user's own assigned book (works for ANY role — the "My leads" tab)
    #  - scope=all → everything (the "All leads" tab)
    #  - no scope (default): CALLERS default to their OWN book (a hard perf/stability rule — 24
    #    callers must NOT each scan the full ~120k collection → production pool exhaustion),
    #    while admins/managers default to everything.
    if not search and not user_id:
        if scope == "mine":
            if current_user:
                q["user_id"] = current_user["id"]
        elif scope != "all" and current_user and current_user.get("role") == "caller":
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
    follow_up_tag: Optional[str] = None, lost_reason_id: Optional[str] = None,
    bucket: Optional[str] = None, duplicate: Optional[str] = None,
    scope: Optional[str] = None,
):
    return dict(
        search=search, stage_id=stage_id, lead_stage=lead_stage, tags=tags, user_id=user_id,
        source_lead=source_lead, campaign_name=campaign_name, ads_platform=ads_platform,
        city=city, state_name=state_name, active=active, date_from=date_from, date_to=date_to,
        follow_up=follow_up, priority=priority, follow_up_tag=follow_up_tag, lost_reason_id=lost_reason_id,
        bucket=bucket, duplicate=duplicate, scope=scope,
    )


ALLOWED_SORT = {"create_date", "create_date_ist", "contact_name", "name", "phone", "city",
                "user_id", "lead_stage", "follow_up_date", "source_lead", "id", "write_date"}

# Cap every list query so a slow scan on a big filtered set aborts and RELEASES its pooled
# connection (fast error) instead of hanging until the ingress gateway 503s.
LIST_FIND_MS = 15000
LIST_COUNT_MS = 8000

# count_documents on a big filtered set (e.g. ~120k pipeline leads) scans that many index
# keys EVERY call. Under a burst of concurrent Lead-menu loads (24 callers) those scans
# contend on the DB and starve the finds → requests pile up past the timeout → 503 cascade.
# Cache counts briefly and COALESCE concurrent identical counts into a single DB call.
_COUNT_TTL = 30.0
_count_cache: dict = {}
_count_inflight: dict = {}


async def _cached_count(q: dict) -> int:
    """Return the list total WITHOUT ever blocking the Leads list from opening. If a fresh
    count for this exact query is cached, use it. Otherwise kick the count off in the
    BACKGROUND (on the analytics pool, so it never contends with the interactive finds /
    lead-detail reads) and return -1 immediately. The frontend renders -1 as 'Many' and
    paginates via its 'probably a next page' fallback; the exact number appears on the next
    load once the background count has cached. count_documents over a big filtered set (~120k
    keys) can take several seconds on a load-saturated prod DB — previously it was awaited
    INLINE, so the fast (index-covered, 50-row) find was gated behind it → the Leads list
    'took forever to open / Server is busy' while every other page (small per-user queries)
    opened fine. Decoupling the count from the item fetch is the fix."""
    key = json.dumps(q, sort_keys=True, default=str)
    now = time.time()
    hit = _count_cache.get(key)
    if hit and hit[0] > now:
        return hit[1]

    async def _do():
        try:
            val = await db_analytics.leads.count_documents(q, maxTimeMS=LIST_COUNT_MS)
            if len(_count_cache) > 1000:
                _count_cache.clear()
            _count_cache[key] = (time.time() + _COUNT_TTL, val)
        except PyMongoError:
            pass
        finally:
            _count_inflight.pop(key, None)

    if key not in _count_inflight:
        _count_inflight[key] = asyncio.ensure_future(_do())
    return -1


# group_counts runs a full-collection aggregation over ~120k pipeline docs every call.
# On a Lead-menu load EVERY caller fires the SAME group_counts (lead_stage + user_id) with
# identical params, so a 24-caller burst = 48 identical heavy aggregations contending on the
# single-worker DB → ~6s tail latency. Cache the result briefly and COALESCE concurrent
# identical aggregations into ONE DB call (the other 23 await the same task).
_GROUP_TTL = 30.0
_group_cache: dict = {}
_group_inflight: dict = {}


async def _cached_group(group_by: str, q: dict, pipeline: list):
    key = json.dumps([group_by, q], sort_keys=True, default=str)
    now = time.time()
    hit = _group_cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    if key in _group_inflight:
        return await _group_inflight[key]

    async def _do():
        try:
            # Heavy full-set aggregation → run on the analytics pool so it never starves the
            # interactive connections callers use for their Leads list / lead detail.
            rows = await db_analytics.leads.aggregate(pipeline, allowDiskUse=True, maxTimeMS=15000).to_list(200)
            val = [{"key": r["_id"], "count": r["count"]} for r in rows]
        except PyMongoError:
            return None
        if len(_group_cache) > 500:
            _group_cache.clear()
        _group_cache[key] = (time.time() + _GROUP_TTL, val)
        return val

    task = asyncio.ensure_future(_do())
    _group_inflight[key] = task
    try:
        return await task
    finally:
        _group_inflight.pop(key, None)


@router.get("")
async def list_leads(
    params: dict = Depends(query_params_dep),
    page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
    sort: str = "create_date", order: str = "desc",
    user: dict = Depends(get_current_user),
):
    q = build_query(**params, current_user=user)
    if sort not in ALLOWED_SORT:
        sort = "create_date"
    sort_dir = -1 if order == "desc" else 1
    cur = (db.leads.find(q, LIST_PROJECTION).sort([(sort, sort_dir), ("id", -1)])
           .skip((page - 1) * limit).limit(limit).allow_disk_use(True).max_time_ms(LIST_FIND_MS))
    # PIN the sort-covering index for the unscoped "all pipeline" list. Without this the planner
    # can choose {active,pipeline,create_date,id} and — because the pipeline bucket uses $ne — do
    # a BLOCKING SORT over all ~120k docs (only ~0.1s in preview, but 15-30s on a load-saturated
    # prod DB → the /api/leads 504 storm). active_createdate_id walks create_date order and applies
    # pipeline!=false as a cheap residual (examines ~limit keys). Only the exact unscoped pipeline
    # default query qualifies; scoped/filtered queries keep their own better compound indexes.
    if sort == "create_date" and set(q.keys()) <= {"active", "pipeline"} and q.get("pipeline") == {"$ne": False}:
        cur = cur.hint("active_createdate_id")
    try:
        items = await cur.to_list(limit)
    except PyMongoError:
        # Extremely slow filter/sort combo — return empty rather than 500 so the app stays up.
        raise HTTPException(status_code=504, detail="This view is taking too long — please narrow the filters.")
    total = await _cached_count(q)
    return {"items": items, "total": total, "page": page, "limit": limit}


GROUP_FIELDS = {
    "user_id": "$user_id", "lead_stage": "$lead_stage", "stage_id": "$stage_id",
    "source_lead": "$source_lead", "follow_up_tag": "$follow_up_tag",
    "ads_platform": "$ads_platform", "campaign_name": "$campaign_name",
    "city": "$city", "state_name": "$state_name", "priority": "$priority",
    "lost_reason_id": "$lost_reason_id",
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
    rows = await _cached_group(group_by, q, pipeline)
    if rows is None:
        raise HTTPException(status_code=504, detail="Grouping is taking too long — please narrow the filters.")
    return rows


@router.get("/{lead_id}")
async def get_lead(lead_id: int, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0}, max_time_ms=8000)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.get("/{lead_id}/audit")
async def lead_audit(lead_id: int, user: dict = Depends(get_current_user)):
    """Case change 1 — visible per-lead audit trail (who / what / old→new / when)."""
    return await db.audit_logs.find({"lead_id": lead_id}, {"_id": 0}).sort("id", -1).to_list(500)


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
    follow_up_time: Optional[str] = None
    follow_up_tag: Optional[str] = None
    gender: Optional[str] = None
    male_age: Optional[str] = None
    female_age: Optional[str] = None
    query: Optional[str] = None
    country: Optional[str] = None


@router.post("")
async def create_lead(body: LeadCreate, user: dict = Depends(get_current_user)):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    data.setdefault("country", "India")  # Case 3 — default market
    if not data.get("name"):
        data["name"] = data.get("contact_name") or data.get("phone") or "New Lead"
    lid = await next_id("lead")
    now = now_utc_str()
    phone_digits = re.sub(r"\D", "", data.get("phone") or "")[-10:]
    dup = await check_duplicate(phone_digits)
    doc = {
        "id": lid, "active": True, "stage_id": 1, "type": "lead", "priority": "0",
        "tags": data.pop("tags", []), "create_date": now, "create_date_ist": to_ist_str(now),
        "write_date": now, "create_uid": user["id"], "custom": {},
        "phone_digits": phone_digits,
        "is_duplicate": dup["is_duplicate"], "duplicate_of": dup["duplicate_of"],
        "original_user_id": data.get("user_id"),
        **data,
    }
    doc.update(ist_date_parts(doc["create_date_ist"]))
    doc.update(search_norm(doc))
    await db.leads.insert_one(doc)
    await log_message(lid, f"Lead created by {user['name']}", author=user)
    if dup["is_duplicate"]:
        await log_message(lid, f"⚠️ Possible duplicate — same phone as lead #{dup['duplicate_of']}", author=user, subtype="comment")
    await run_automations("on_create", doc)
    doc.pop("_id", None)
    return doc


class LeadUpdate(BaseModel):
    updates: dict


async def _track_changes(lead, updates, user):
    parts = []
    tag_names = user_names = stage_names = None
    for f in TRACKED:
        if f not in updates or updates[f] == lead.get(f):
            continue
        old, new = lead.get(f), updates[f]
        if f == "tags":
            if tag_names is None:
                tag_names = {t["id"]: t["name"] for t in await db.catalogs.find({"type": "tag"}, {"_id": 0}).to_list(500)}
            old_set, new_set = set(old or []), set(new or [])
            added, removed = new_set - old_set, old_set - new_set
            det = []
            if added:
                det.append("added " + ", ".join(tag_names.get(t, str(t)) for t in added))
            if removed:
                det.append("removed " + ", ".join(tag_names.get(t, str(t)) for t in removed))
            if det:
                parts.append("Disposition / Tags: " + "; ".join(det))
                await log_audit(lead["id"], user, "disposition_changed", field="Disposition / Tags",
                                old=(", ".join(tag_names.get(t, str(t)) for t in old_set) or "None"),
                                new=(", ".join(tag_names.get(t, str(t)) for t in new_set) or "None"))
        elif f == "user_id":
            if user_names is None:
                user_names = {u["id"]: u["name"] for u in await db.users.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)}
            ol, nl = user_names.get(old, old or "None"), user_names.get(new, new or "None")
            parts.append(f"Assigned: {ol} → {nl}")
            await log_audit(lead["id"], user, "reassigned", field="Assigned caller", old=ol, new=nl)
        elif f == "stage_id":
            if stage_names is None:
                stage_names = {s["id"]: s["name"] for s in await db.catalogs.find({"type": "stage"}, {"_id": 0}).to_list(50)}
            ol, nl = stage_names.get(old, old or "None"), stage_names.get(new, new or "None")
            parts.append(f"Pipeline stage: {ol} → {nl}")
            await log_audit(lead["id"], user, "stage_changed", field="Pipeline stage", old=ol, new=nl)
        else:
            label = f.replace("_", " ").title()
            parts.append(f"{label}: {old or 'None'} → {new or 'None'}")
            await log_audit(lead["id"], user, "field_changed", field=label,
                            old=(str(old) if old not in (None, "") else "None"),
                            new=(str(new) if new not in (None, "") else "None"))
    if parts:
        await log_message(lead["id"], "<br/>".join(parts), author=user)


@router.patch("/{lead_id}")
async def update_lead(lead_id: int, body: LeadUpdate, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, max_time_ms=8000)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    updates = {k: v for k, v in body.updates.items() if k in EDITABLE_FIELDS}
    # Case change 1 — every caller can edit any lead, BUT the assigned caller is
    # protected: only admin/manager may re-assign, and original_user_id is immutable.
    if user.get("role") == "caller":
        updates.pop("user_id", None)
    updates.pop("original_user_id", None)
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    if updates.get("user_id") and not lead.get("original_user_id"):
        updates["original_user_id"] = updates["user_id"]
    if "custom" in updates and isinstance(updates["custom"], dict):
        merged = dict(lead.get("custom") or {})
        merged.update(updates["custom"])
        updates["custom"] = merged
    if "phone" in updates:
        updates["phone_digits"] = re.sub(r"\D", "", updates.get("phone") or "")[-10:]
    for _src, _dst in (("name", "name_lc"), ("contact_name", "contact_name_lc"), ("email_from", "email_lc")):
        if _src in updates:
            _v = updates[_src]
            updates[_dst] = _v.lower() if isinstance(_v, str) and _v else None
    await _track_changes(lead, updates, user)
    updates["write_date"] = now_utc_str()
    updates["write_uid"] = user["id"]
    await db.leads.update_one({"id": lead_id}, {"$set": updates})
    new_lead = await db.leads.find_one({"id": lead_id}, {"_id": 0}, max_time_ms=8000)
    if "user_id" in updates:
        await sync_channel_owner(new_lead.get("phone_digits"), updates["user_id"])
    stage_changed = ("stage_id" in updates and updates["stage_id"] != lead.get("stage_id")) or \
                    ("lead_stage" in updates and updates["lead_stage"] != lead.get("lead_stage"))
    if stage_changed:
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
    await log_audit(lead_id, user, "lead_lost", field="Status", new="Lost", detail=(reason.strip(" —") or None))
    return {"ok": True}


@router.post("/{lead_id}/restore")
async def restore_lead(lead_id: int, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0, "user_id": 1})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    await db.leads.update_one({"id": lead_id}, {"$set": {"active": True, "lost_reason_id": None}})
    await log_message(lead_id, "Lead restored", author=user)
    return {"ok": True}


class PromoteBody(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    email_from: Optional[str] = None
    city: Optional[str] = None
    state_name: Optional[str] = None
    phone: Optional[str] = None


@router.post("/{lead_id}/promote-to-pipeline")
async def promote_to_pipeline(lead_id: int, body: PromoteBody, user: dict = Depends(get_current_user)):
    """Case 2 — validate a raw Ozonetel lead and move it into 'Lead in Pipeline'.
    Dedup: if a pipeline lead already exists with the verified phone, merge this
    lead's call activity into it instead of creating a duplicate."""
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    phone = (body.phone or lead.get("phone") or "").strip()
    pdig = re.sub(r"\D", "", phone)[-10:]
    name = body.contact_name or body.name or lead.get("contact_name") or lead.get("name")

    # Dedup — existing pipeline lead with same verified phone (not this raw one)
    existing = None
    if pdig and len(pdig) >= 8:
        existing = await db.leads.find_one({
            "phone_digits": pdig, "id": {"$ne": lead_id},
            "$or": [{"ozonetel_lead": {"$ne": True}}, {"in_pipeline": True}],
        }, {"_id": 0, "id": 1, "name": 1, "contact_name": 1}, sort=[("id", 1)])

    if existing:
        # map this lead's call activity to the existing pipeline record, archive the raw one
        await db.call_events.update_many({"lead_id": lead_id}, {"$set": {"lead_id": existing["id"]}})
        await db.leads.update_one({"id": lead_id}, {"$set": {"active": False, "merged_into": existing["id"], "is_duplicate": True, "duplicate_of": existing["id"], "write_date": now_utc_str()}})
        await log_message(existing["id"], f"📞 Ozonetel call activity from #{lead_id} merged here (duplicate phone) by {user['name']}", author=user, subtype="comment")
        await log_message(lead_id, f"Merged into pipeline lead #{existing['id']} (duplicate phone)", author=user)
        return {"ok": True, "merged_into": existing["id"]}

    updates = {"in_pipeline": True, "pipeline": True, "write_date": now_utc_str(), "write_uid": user["id"]}
    if name:
        updates["contact_name"] = name
        updates["name"] = name
    for f in ("email_from", "city", "state_name"):
        v = getattr(body, f)
        if v:
            updates[f] = v.strip()
    if phone:
        updates["phone"] = phone
        updates["phone_digits"] = pdig
    if not lead.get("user_id"):
        updates["user_id"] = user["id"]
    updates.update(search_norm({**lead, **updates}))
    await db.leads.update_one({"id": lead_id}, {"$set": updates})
    await log_message(lead_id, f"✅ Moved to <b>Lead in Pipeline</b> (verified) by {user['name']}", author=user, subtype="comment")
    return {"ok": True, "lead_id": lead_id, "in_pipeline": True}


class SendWhatsAppBody(BaseModel):
    template_id: int
    phone: Optional[str] = None


@router.post("/{lead_id}/send_whatsapp")
async def send_whatsapp(lead_id: int, body: SendWhatsAppBody, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    template = await db.templates_whatsapp.find_one({"id": body.template_id}, {"_id": 0})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    phone = body.phone or lead.get("phone") or lead.get("mobile")
    if not phone:
        raise HTTPException(status_code=400, detail="Lead has no phone number")
    preview = (template.get("body") or "").replace("{{1}}", lead.get("contact_name") or lead.get("name") or "")
    # Live send via WhatsApp Cloud API when configured, else queue until connected.
    live = await wac.is_configured()
    send_status = "pending_api_credentials"
    send_note = "sends automatically once WhatsApp API is connected"
    wamid = None
    if live:
        res = await wac.send_lead_template(lead, template)
        if res.get("ok"):
            send_status, wamid = "sent", res.get("wamid")
            send_note = "delivered via WhatsApp Cloud API"
        else:
            send_status = "failed"
            send_note = f"WhatsApp send failed: {res.get('error')}"
    await db.outbound_queue.insert_one({
        "channel": "whatsapp", "lead_id": lead_id, "template_id": template["id"],
        "template_name": template["name"], "phone": phone, "body": preview,
        "status": send_status, "requested_by": user["name"], "wamid": wamid,
        "created_at": now_utc_str(),
    })
    # Case 5 — track this outbound message for full lifecycle (sent→delivered→read…)
    track_status = {"sent": "sent", "failed": "failed"}.get(send_status, "in_queue")
    track = await record_wa_outbound(
        lead_id=lead_id, template_id=template["id"], template_name=template["name"],
        sent_to=phone, body=preview, created_by=user["name"], status=track_status,
        wamid=wamid, source="manual", error=(send_note if send_status == "failed" else None))
    # mirror into the lead's WhatsApp thread if one exists
    digits = re.sub(r"\D", "", phone)[-10:]
    if len(digits) >= 8:
        ch = await db.wa_channels.find_one({"phone_digits": {"$regex": digits + "$"}})
        if ch:
            mid = await next_id("wa_message")
            await db.wa_messages.insert_one({
                "id": mid, "channel_id": ch["id"], "body": preview, "author_name": user["name"],
                "date": now_utc_str(), "message_type": "comment", "direction": "outbound",
                "status": send_status, "wamid": wamid,
            })
    await log_message(
        lead_id,
        f"WhatsApp template <b>{template['name']}</b> to {phone} by {user['name']} ({send_note})",
        author=user,
        extra={"kind": "wa_template", "channel": "whatsapp", "preview": preview,
               "template_name": template["name"], "track_id": track["id"], "status": track_status},
    )
    if live and send_status == "failed":
        raise HTTPException(status_code=400, detail=send_note)
    await log_audit(lead_id, user, "whatsapp_sent", field="WhatsApp", detail=f"{template['name']} → {phone}")
    return {"ok": True, "status": send_status, "phone": phone, "template": template["name"]}


class SendEmailBody(BaseModel):
    to: Optional[str] = None
    subject: str
    body: str
    save_as_template: Optional[str] = None


@router.post("/{lead_id}/send_email")
async def send_email(lead_id: int, body: SendEmailBody, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    to = (body.to or lead.get("email_from") or "").strip()
    if not to:
        raise HTTPException(status_code=400, detail="Lead has no email address — enter one")
    from core import gmail_send as gm
    sent_live = False
    send_err = None
    if await gm.is_connected():
        res = await gm.send_email(to, body.subject, body.body, html=True)
        sent_live = res.get("ok", False)
        send_err = res.get("error")
    await db.outbound_queue.insert_one({
        "channel": "email", "lead_id": lead_id, "to": to, "subject": body.subject,
        "body": body.body, "status": "sent" if sent_live else "pending_api_credentials",
        "error": send_err, "requested_by": user["name"], "created_at": now_utc_str(),
    })
    if body.save_as_template:
        tid = await next_id("template_email")
        await db.templates_email.insert_one({
            "id": tid, "name": body.save_as_template, "subject": body.subject,
            "body": body.body, "active": True, "created_at": now_utc_str(),
        })
    note = (f"📧 Email sent to <b>{to}</b> by {user['name']}" if sent_live
            else f"Email queued to <b>{to}</b> by {user['name']} (sends automatically once Gmail is connected)")
    await log_message(
        lead_id,
        f"{note}<br/><b>Subject:</b> {body.subject}",
        author=user, subtype="comment",
        extra={"kind": "email_template", "channel": "email", "preview": body.body,
               "template_name": body.subject, "subject": body.subject,
               "status": "sent" if sent_live else "in_queue"},
    )
    return {"ok": True, "status": "queued", "to": to}


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
        # Case 1 — WhatsApp chat visibility follows lead assignment.
        for pd in await db.leads.distinct("phone_digits", q):
            await sync_channel_owner(pd, int(p["user_id"]))
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
    # Case 8: bulk tag/stage updates also fire automation triggers
    if body.action in ("add_tags", "set_stage", "set_lead_stage"):
        async for l in db.leads.find(q, {"_id": 0}):
            if body.action == "add_tags":
                await run_automations("on_tag_set", l, {"added_tags": [int(t) for t in p["tags"]]})
            else:
                await run_automations("on_stage_set", l)
    return {"ok": True, "count": len(ids)}


# ---------- Case 2: Follow-up entries (history with edit/delete) ----------
async def _sync_lead_followup(lead_id: int):
    """Keep the lead's follow_up_* fields pointed at the latest scheduled entry."""
    latest = await db.follow_ups.find(
        {"lead_id": lead_id, "follow_up_date": {"$gt": ""}}, {"_id": 0}
    ).sort("follow_up_date", -1).limit(1).to_list(1)
    if latest:
        f = latest[0]
        await db.leads.update_one({"id": lead_id}, {"$set": {
            "follow_up_date": f.get("follow_up_date"), "follow_up_time": f.get("follow_up_time"),
            "follow_up_tag": f.get("follow_up_tag"), "follow_up_status": f.get("status")}})
    else:
        await db.leads.update_one({"id": lead_id}, {"$set": {
            "follow_up_date": None, "follow_up_time": None, "follow_up_tag": None, "follow_up_status": None}})


class FollowUpBody(BaseModel):
    follow_up_date: Optional[str] = None
    follow_up_time: Optional[str] = None
    follow_up_tag: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = None


@router.get("/{lead_id}/followups")
async def list_followups(lead_id: int, user: dict = Depends(get_current_user)):
    return await db.follow_ups.find({"lead_id": lead_id}, {"_id": 0}).sort([("follow_up_date", -1), ("id", -1)]).to_list(200)


@router.post("/{lead_id}/followups")
async def add_followup(lead_id: int, body: FollowUpBody, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    note = (body.note or "").strip()
    if not note:  # Case 1 — note is mandatory for every follow-up
        raise HTTPException(status_code=400, detail="A note is required for every follow-up")
    fid = await next_id("follow_up")
    doc = {"id": fid, "lead_id": lead_id, "follow_up_date": body.follow_up_date or None,
           "follow_up_time": body.follow_up_time or None, "follow_up_tag": body.follow_up_tag or None,
           "note": note, "status": body.status or None, "created_by": user["id"],
           "created_by_name": user["name"], "created_at": now_utc_str()}
    await db.follow_ups.insert_one(doc)
    await _sync_lead_followup(lead_id)
    tag = f" · {doc['follow_up_tag']}" if doc.get("follow_up_tag") else ""
    when = doc.get("follow_up_date") or "no date"
    await log_message(lead_id, f"Follow-up scheduled for <b>{when}</b>{tag}<br/>{note}", author=user)
    await log_audit(lead_id, user, "follow_up_added", field="Follow-up", detail=f"{when}{tag} — {note}")
    doc.pop("_id", None)
    return doc


@router.patch("/{lead_id}/followups/{fid}")
async def update_followup(lead_id: int, fid: int, body: FollowUpBody, user: dict = Depends(get_current_user)):
    fu = await db.follow_ups.find_one({"id": fid, "lead_id": lead_id})
    if not fu:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="A note is required for every follow-up")
    updates = {"follow_up_date": body.follow_up_date or None, "follow_up_time": body.follow_up_time or None,
               "follow_up_tag": body.follow_up_tag or None, "note": note, "status": body.status or None}
    await db.follow_ups.update_one({"id": fid}, {"$set": updates})
    await _sync_lead_followup(lead_id)
    await log_message(lead_id, f"Follow-up updated → <b>{updates['follow_up_date'] or 'no date'}</b>"
                      f"{(' · ' + updates['status']) if updates.get('status') else ''}", author=user)
    return await db.follow_ups.find_one({"id": fid}, {"_id": 0})


class FollowUpStatusBody(BaseModel):
    status: str


@router.post("/{lead_id}/followups/{fid}/status")
async def set_followup_status(lead_id: int, fid: int, body: FollowUpStatusBody, user: dict = Depends(get_current_user)):
    fu = await db.follow_ups.find_one({"id": fid, "lead_id": lead_id})
    if not fu:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    status = (body.status or "").strip() or None
    await db.follow_ups.update_one({"id": fid}, {"$set": {"status": status}})
    await _sync_lead_followup(lead_id)
    await log_message(lead_id, f"Follow-up marked <b>{status or 'cleared'}</b>", author=user)
    return await db.follow_ups.find_one({"id": fid}, {"_id": 0})


@router.delete("/{lead_id}/followups/{fid}")
async def delete_followup(lead_id: int, fid: int, user: dict = Depends(get_current_user)):
    res = await db.follow_ups.delete_one({"id": fid, "lead_id": lead_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    await _sync_lead_followup(lead_id)
    await log_message(lead_id, "Follow-up entry deleted", author=user)
    return {"ok": True}



# ---------------- Caller Activities (Case 2 — call feedback / communication log) ----------------
class CallerActivityBody(BaseModel):
    feedback: str


@router.get("/{lead_id}/caller-activities")
async def list_caller_activities(lead_id: int, user: dict = Depends(get_current_user)):
    return await db.caller_activities.find({"lead_id": lead_id}, {"_id": 0}).sort("id", -1).to_list(500)


@router.post("/{lead_id}/caller-activities")
async def add_caller_activity(lead_id: int, body: CallerActivityBody, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0, "id": 1, "user_id": 1})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    fb = (body.feedback or "").strip()
    if not fb:
        raise HTTPException(status_code=400, detail="Feedback note is required")
    aid = await next_id("caller_activity")
    doc = {"id": aid, "lead_id": lead_id, "feedback": fb,
           "created_by": user["id"], "created_by_name": user["name"], "created_at": now_utc_str()}
    await db.caller_activities.insert_one(doc)
    await log_message(lead_id, f"🗣️ Caller activity — {fb}", author=user)
    await log_audit(lead_id, user, "caller_activity", field="Caller activity", detail=fb)
    doc.pop("_id", None)
    return doc


# ---------------- Follow-up analytics + reminders (Case 5 + Case 4) ----------------
@router.get("/followups/analytics")
async def followups_analytics(date: Optional[str] = None, user: dict = Depends(get_current_user)):
    day = date or today_ist()
    pipeline = [{"$match": {"follow_up_date": day}}]
    if user.get("role") == "caller":
        pipeline += [
            {"$lookup": {"from": "leads", "localField": "lead_id", "foreignField": "id", "as": "_lead"}},
            {"$match": {"_lead.user_id": user["id"]}},
        ]
    pipeline += [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    rows = await db.follow_ups.aggregate(pipeline).to_list(50)
    by, total = {}, 0
    for r in rows:
        by[r["_id"] or "__none__"] = r["n"]
        total += r["n"]
    pending = by.get("__none__", 0)
    is_past = day < today_ist()
    return {
        "date": day, "total": total,
        "completed": by.get("Completed", 0),
        "not_done": by.get("Not Done", 0) + (pending if is_past else 0),
        "rescheduled": by.get("Rescheduled", 0),
        "cancelled": by.get("Cancelled", 0),
        "pending": 0 if is_past else pending,
    }


@router.get("/followups/reminders")
async def followups_reminders(user: dict = Depends(get_current_user)):
    now = datetime.now(IST)
    day = now.strftime("%Y-%m-%d")
    now_min = now.hour * 60 + now.minute
    # Owner-specific (Case 2): remind ONLY the user who created the follow-up — not the
    # whole team, and not admins unless they created it.
    # Fail-fast: polled every 60s by all callers. Abort on DB slowness and return no reminders
    # so the poll never holds its pooled connection during a slow spell (pool-exhaustion guard).
    try:
        items = await db.follow_ups.find(
            {"follow_up_date": day, "follow_up_time": {"$nin": [None, ""]},
             "created_by": user["id"],
             "status": {"$nin": ["Completed", "Cancelled"]}}, {"_id": 0}, max_time_ms=5000).to_list(1000)
        lead_ids = list({it["lead_id"] for it in items})
        leads = {l["id"]: l for l in await db.leads.find(
            {"id": {"$in": lead_ids}},
            {"_id": 0, "id": 1, "contact_name": 1, "name": 1, "phone": 1}, max_time_ms=5000).to_list(2000)}
    except PyMongoError:
        return {"now": now.strftime("%H:%M"), "reminders": []}
    out = []
    for it in items:
        lead = leads.get(it["lead_id"])
        if not lead:
            continue
        try:
            h, m = it["follow_up_time"].split(":")[:2]
            sched = int(h) * 60 + int(m)
        except (ValueError, AttributeError):
            continue
        # Fire ONLY in the 5-minute lead-up window [sched-5, sched] — never after the
        # scheduled time. The frontend also dedupes so it shows exactly once.
        if sched - 5 <= now_min <= sched:
            out.append({
                "follow_up_id": it["id"], "lead_id": it["lead_id"],
                "lead_name": lead.get("contact_name") or lead.get("name") or f"Lead {it['lead_id']}",
                "phone": lead.get("phone"), "follow_up_time": it["follow_up_time"],
                "follow_up_date": it["follow_up_date"], "note": it.get("note"), "status": it.get("status"),
            })
    return {"now": now.strftime("%H:%M"), "reminders": out}

