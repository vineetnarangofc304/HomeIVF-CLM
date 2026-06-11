from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user
from core.utils import today_ist

router = APIRouter(prefix="/reports", tags=["reports"])

DIMS = {
    "user_id": "$user_id", "lead_stage": "$lead_stage", "stage_id": "$stage_id",
    "source_lead": "$source_lead", "follow_up_tag": "$follow_up_tag",
    "ads_platform": "$ads_platform", "campaign_name": "$campaign_name",
    "city": "$city", "state_name": "$state_name", "priority": "$priority",
    "lost_reason_id": "$lost_reason_id", "tags": "$tags",
    "create_date:day": {"$substrCP": ["$create_date_ist", 0, 10]},
    "create_date:month": {"$substrCP": ["$create_date_ist", 0, 7]},
}


def key_str(v):
    return "__null__" if v in (None, False, "") else str(v)


class PivotBody(BaseModel):
    rows: list  # 1-2 dims
    cols: Optional[str] = None  # 0-1 dim
    filters: dict = {}


def build_match(filters: dict, current_user: dict):
    q = {}
    active = filters.get("active", "true")
    if active == "true":
        q["active"] = True
    elif active == "false":
        q["active"] = False
    if filters.get("date_from"):
        q.setdefault("create_date_ist", {})["$gte"] = filters["date_from"]
    if filters.get("date_to"):
        q.setdefault("create_date_ist", {})["$lte"] = filters["date_to"] + " 23:59:59"
    if filters.get("user_ids"):
        q["user_id"] = {"$in": [int(u) for u in filters["user_ids"]]}
    elif filters.get("user_id"):
        q["user_id"] = int(filters["user_id"])
    if filters.get("tags"):
        tags = filters["tags"] if isinstance(filters["tags"], list) else [filters["tags"]]
        q["tags"] = {"$in": [int(t) for t in tags]}
    for f in ["lead_stage", "source_lead", "campaign_name", "ads_platform", "state_name", "city", "follow_up_tag"]:
        if filters.get(f):
            q[f] = filters[f]
    if filters.get("lost_reason_id"):
        q["lost_reason_id"] = int(filters["lost_reason_id"])
    if filters.get("stage_id"):
        q["stage_id"] = int(filters["stage_id"])
    if current_user.get("role") == "caller":
        q["user_id"] = current_user["id"]
    return q


async def resolve_labels(dim: str, keys: list) -> dict:
    if dim == "user_id":
        users = await db.users.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
        return {u["id"]: u["name"] for u in users}
    if dim == "tags":
        tags = await db.catalogs.find({"type": "tag"}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
        return {t["id"]: t["name"] for t in tags}
    if dim == "stage_id":
        stages = await db.catalogs.find({"type": "stage"}, {"_id": 0, "id": 1, "name": 1}).to_list(50)
        return {s["id"]: s["name"] for s in stages}
    if dim == "lost_reason_id":
        rs = await db.catalogs.find({"type": "lost_reason"}, {"_id": 0, "id": 1, "name": 1}).to_list(50)
        return {r["id"]: r["name"] for r in rs}
    return {}


@router.post("/pivot")
async def pivot(body: PivotBody, user: dict = Depends(get_current_user)):
    rows = [r for r in body.rows if r in DIMS][:2]
    col = body.cols if body.cols in DIMS else None
    if not rows:
        raise HTTPException(status_code=400, detail="At least one valid row dimension required")
    match = build_match(body.filters, user)
    pipeline = [{"$match": match}]
    if "tags" in rows + ([col] if col else []):
        pipeline.append({"$unwind": {"path": "$tags", "preserveNullAndEmptyArrays": True}})
    group_id = {f"r{i}": DIMS[d] for i, d in enumerate(rows)}
    if col:
        group_id["c"] = DIMS[col]
    pipeline.append({"$group": {"_id": group_id, "count": {"$sum": 1}}})
    pipeline.append({"$limit": 5000})
    data = await db.leads.aggregate(pipeline).to_list(5000)

    label_maps = {}
    for i, d in enumerate(rows):
        label_maps[f"r{i}"] = await resolve_labels(d, [])
    if col:
        label_maps["c"] = await resolve_labels(col, [])

    def label(slot, key):
        if key in (None, False, ""):
            return "Undefined"
        return str(label_maps.get(slot, {}).get(key, key))

    # column definitions (raw key + label)
    if col:
        col_map = {}
        for r in data:
            ck = r["_id"].get("c")
            col_map[key_str(ck)] = {"key": key_str(ck), "label": label("c", ck)}
        col_keys = sorted(col_map.values(), key=lambda x: x["label"])
    else:
        col_keys = [{"key": "__count__", "label": "Leads"}]

    tree = {}
    for r in data:
        rk0, rk1 = r["_id"].get("r0"), r["_id"].get("r1") if len(rows) > 1 else None
        k0 = key_str(rk0)
        ck = key_str(r["_id"].get("c")) if col else "__count__"
        node = tree.setdefault(k0, {"key": k0, "label": label("r0", rk0), "cells": {}, "total": 0, "children": {}})
        if len(rows) > 1:
            k1 = key_str(rk1)
            child = node["children"].setdefault(k1, {"key": k1, "label": label("r1", rk1), "cells": {}, "total": 0})
            child["cells"][ck] = child["cells"].get(ck, 0) + r["count"]
            child["total"] += r["count"]
        node["cells"][ck] = node["cells"].get(ck, 0) + r["count"]
        node["total"] += r["count"]

    out_rows = []
    for n in sorted(tree.values(), key=lambda x: -x["total"]):
        out_rows.append({
            "key": n["key"], "label": n["label"], "cells": n["cells"], "total": n["total"],
            "children": sorted(n["children"].values(), key=lambda x: -x["total"]),
        })
    grand = sum(n["total"] for n in tree.values())
    col_totals = {}
    for n in tree.values():
        for ck, v in n["cells"].items():
            col_totals[ck] = col_totals.get(ck, 0) + v
    return {"rows": out_rows, "col_keys": col_keys, "grand_total": grand, "col_totals": col_totals,
            "row_dims": rows, "col_dim": col}


@router.get("/trends")
async def trends(granularity: str = "day", date_from: Optional[str] = None,
                 date_to: Optional[str] = None, active: str = "all",
                 user: dict = Depends(get_current_user)):
    if granularity not in ("day", "week", "month"):
        raise HTTPException(status_code=400, detail="Invalid granularity")
    if not date_from:
        days = {"day": 30, "week": 180, "month": 730}[granularity]
        date_from = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    match = build_match({"date_from": date_from, "date_to": date_to, "active": active}, user)
    match["create_date_ist"] = {**match.get("create_date_ist", {}), "$gte": max(date_from, match.get("create_date_ist", {}).get("$gte", date_from))}

    if granularity == "day":
        period = {"$substrCP": ["$create_date_ist", 0, 10]}
    elif granularity == "month":
        period = {"$substrCP": ["$create_date_ist", 0, 7]}
    else:
        period = {"$dateToString": {"format": "%Y-%m-%d", "date": {"$dateTrunc": {
            "date": {"$dateFromString": {"dateString": "$create_date_ist", "format": "%Y-%m-%d %H:%M:%S", "onError": None}},
            "unit": "week", "startOfWeek": "monday"}}}}

    data = await db.leads.aggregate([
        {"$match": match},
        {"$group": {"_id": {"p": period, "s": "$lead_stage"}, "count": {"$sum": 1}}},
    ]).to_list(20000)

    periods = {}
    for r in data:
        p = r["_id"]["p"]
        if not p:
            continue
        s = r["_id"]["s"] or "Undefined"
        node = periods.setdefault(p, {"period": p, "total": 0})
        node[s] = node.get(s, 0) + r["count"]
        node["total"] += r["count"]
    out = sorted(periods.values(), key=lambda x: x["period"])
    stages = [s["name"] for s in await db.catalogs.find({"type": "lead_stage"}, {"_id": 0, "name": 1}).to_list(20)]
    return {"series": out, "stages": stages + ["Undefined"]}


@router.get("/heatmap")
async def heatmap(type: str = "dow_hour", date_from: Optional[str] = None,
                  date_to: Optional[str] = None, user: dict = Depends(get_current_user)):
    if type == "dow_hour":
        if not date_from:
            date_from = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
        match = build_match({"date_from": date_from, "date_to": date_to, "active": "all"}, user)
        d = {"$dateFromString": {"dateString": "$create_date_ist", "format": "%Y-%m-%d %H:%M:%S", "onError": None}}
        data = await db.leads.aggregate([
            {"$match": match},
            {"$project": {"dow": {"$dayOfWeek": d}, "hour": {"$hour": d}}},
            {"$match": {"dow": {"$ne": None}}},
            {"$group": {"_id": {"dow": "$dow", "hour": "$hour"}, "count": {"$sum": 1}}},
        ]).to_list(200)
        return {"type": "dow_hour", "date_from": date_from,
                "cells": [{"dow": r["_id"]["dow"], "hour": r["_id"]["hour"], "count": r["count"]} for r in data]}

    if type == "caller_day":
        if not date_from:
            date_from = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30) - timedelta(days=13)).strftime("%Y-%m-%d")
        match = build_match({"date_from": date_from, "date_to": date_to, "active": "all"}, user)
        data = await db.leads.aggregate([
            {"$match": match},
            {"$group": {"_id": {"u": "$user_id", "d": {"$substrCP": ["$create_date_ist", 0, 10]}}, "count": {"$sum": 1}}},
        ]).to_list(5000)
        users = {u["id"]: u["name"] for u in await db.users.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)}
        return {"type": "caller_day", "date_from": date_from,
                "cells": [{"user_id": r["_id"]["u"], "user": users.get(r["_id"]["u"], "Unassigned"),
                           "day": r["_id"]["d"], "count": r["count"]} for r in data]}
    raise HTTPException(status_code=400, detail="Invalid heatmap type")


@router.get("/dashboard")
async def dashboard(user: dict = Depends(get_current_user)):
    base = {"active": True}
    if user["role"] == "caller":
        base["user_id"] = user["id"]
    today = today_ist()
    month = today[:7]
    leads_today = await db.leads.count_documents({**base, "create_date_ist": {"$gte": today}})
    leads_mtd = await db.leads.count_documents({**base, "create_date_ist": {"$gte": month + "-01"}})
    total_leads = await db.leads.count_documents(base)
    converted_mtd = await db.leads.count_documents({**base, "lead_stage": "Converted", "create_date_ist": {"$gte": month + "-01"}})
    followups_today = await db.leads.count_documents({**base, "follow_up_date": today})
    followups_overdue = await db.leads.count_documents({**base, "follow_up_date": {"$lt": today, "$gt": ""}})

    by_stage = await db.leads.aggregate([
        {"$match": base},
        {"$group": {"_id": "$lead_stage", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]).to_list(20)

    by_day = await db.leads.aggregate([
        {"$match": {**base, "create_date_ist": {"$gte": ""}}},
        {"$group": {"_id": {"$substrCP": ["$create_date_ist", 0, 10]}, "count": {"$sum": 1}}},
        {"$sort": {"_id": -1}}, {"$limit": 14},
    ]).to_list(14)
    by_day.reverse()

    leaderboard = await db.leads.aggregate([
        {"$match": {"active": True, "create_date_ist": {"$gte": month + "-01"}}},
        {"$group": {"_id": "$user_id", "count": {"$sum": 1},
                    "converted": {"$sum": {"$cond": [{"$eq": ["$lead_stage", "Converted"]}, 1, 0]}}}},
        {"$sort": {"count": -1}}, {"$limit": 10},
    ]).to_list(10)
    users = {u["id"]: u["name"] for u in await db.users.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)}
    for l in leaderboard:
        l["name"] = users.get(l["_id"], "Unassigned")

    top_tags = await db.leads.aggregate([
        {"$match": {**base, "create_date_ist": {"$gte": month + "-01"}}},
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}, {"$limit": 10},
    ]).to_list(10)
    tag_names = {t["id"]: t["name"] for t in await db.catalogs.find({"type": "tag"}, {"_id": 0, "id": 1, "name": 1}).to_list(500)}
    for t in top_tags:
        t["name"] = tag_names.get(t["_id"], str(t["_id"]))

    return {
        "leads_today": leads_today, "leads_mtd": leads_mtd, "total_leads": total_leads,
        "converted_mtd": converted_mtd, "followups_today": followups_today,
        "followups_overdue": followups_overdue, "by_stage": by_stage, "by_day": by_day,
        "leaderboard": leaderboard, "top_tags": top_tags, "today": today, "month_start": month + "-01",
    }
