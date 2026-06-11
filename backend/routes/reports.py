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
    if filters.get("tags"):
        q["tags"] = {"$in": [int(t) for t in filters["tags"]]}
    if filters.get("lead_stage"):
        q["lead_stage"] = filters["lead_stage"]
    if filters.get("source_lead"):
        q["source_lead"] = filters["source_lead"]
    if filters.get("campaign_name"):
        q["campaign_name"] = filters["campaign_name"]
    if current_user.get("role") == "caller":
        q["user_id"] = current_user["id"]
    return q


async def resolve_labels(dim: str, keys: list) -> dict:
    if dim == "user_id":
        users = await db.users.find({"id": {"$in": [k for k in keys if isinstance(k, int)]}}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
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
    unwound = set()
    for d in rows + ([col] if col else []):
        if d == "tags" and "tags" not in unwound:
            pipeline.append({"$unwind": {"path": "$tags", "preserveNullAndEmptyArrays": True}})
            unwound.add("tags")
    group_id = {f"r{i}": DIMS[d] for i, d in enumerate(rows)}
    if col:
        group_id["c"] = DIMS[col]
    pipeline.append({"$group": {"_id": group_id, "count": {"$sum": 1}}})
    pipeline.append({"$limit": 5000})
    data = await db.leads.aggregate(pipeline).to_list(5000)

    label_maps = {}
    for i, d in enumerate(rows):
        keys = list({r["_id"].get(f"r{i}") for r in data})
        label_maps[f"r{i}"] = await resolve_labels(d, keys)
    if col:
        keys = list({r["_id"].get("c") for r in data})
        label_maps["c"] = await resolve_labels(col, keys)

    def label(slot, key, dim):
        if key in (None, False, ""):
            return "Undefined"
        return str(label_maps.get(slot, {}).get(key, key))

    col_keys = sorted({label("c", r["_id"].get("c"), col) for r in data}) if col else ["count"]
    tree = {}
    for r in data:
        k0 = label("r0", r["_id"].get("r0"), rows[0])
        k1 = label("r1", r["_id"].get("r1"), rows[1]) if len(rows) > 1 else None
        ck = label("c", r["_id"].get("c"), col) if col else "count"
        node = tree.setdefault(k0, {"cells": {}, "total": 0, "children": {}})
        if k1 is not None:
            child = node["children"].setdefault(k1, {"cells": {}, "total": 0})
            child["cells"][ck] = child["cells"].get(ck, 0) + r["count"]
            child["total"] += r["count"]
        node["cells"][ck] = node["cells"].get(ck, 0) + r["count"]
        node["total"] += r["count"]

    out_rows = []
    for k0 in sorted(tree.keys(), key=lambda x: -tree[x]["total"]):
        n = tree[k0]
        out_rows.append({"key": k0, "cells": n["cells"], "total": n["total"],
                         "children": [{"key": k1, "cells": c["cells"], "total": c["total"]}
                                      for k1, c in sorted(n["children"].items(), key=lambda x: -x[1]["total"])]})
    grand = sum(n["total"] for n in tree.values())
    col_totals = {}
    for n in tree.values():
        for ck, v in n["cells"].items():
            col_totals[ck] = col_totals.get(ck, 0) + v
    return {"rows": out_rows, "col_keys": col_keys, "grand_total": grand, "col_totals": col_totals}


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
        "leaderboard": leaderboard, "top_tags": top_tags,
    }
