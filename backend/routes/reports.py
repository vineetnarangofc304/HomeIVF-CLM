import asyncio
import calendar
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user, require_permission
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
async def pivot(body: PivotBody, user: dict = Depends(require_permission("reports"))):
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
    data = await db.leads.aggregate(pipeline, maxTimeMS=20000, allowDiskUse=True).to_list(5000)

    label_maps = {}
    for i, d in enumerate(rows):
        label_maps[f"r{i}"] = await resolve_labels(d, [])
    if col:
        label_maps["c"] = await resolve_labels(col, [])

    def label(slot, key):
        if key in (None, False, ""):
            return "New / Unassigned"
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
                 user: dict = Depends(require_permission("reports"))):
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
    ], maxTimeMS=20000, allowDiskUse=True).to_list(20000)

    periods = {}
    for r in data:
        p = r["_id"].get("p")
        if not p:
            continue
        s = r["_id"].get("s") or "New / Unassigned"
        node = periods.setdefault(p, {"period": p, "total": 0})
        node[s] = node.get(s, 0) + r["count"]
        node["total"] += r["count"]
    out = sorted(periods.values(), key=lambda x: x["period"])
    stages = [s["name"] for s in await db.catalogs.find({"type": "lead_stage"}, {"_id": 0, "name": 1}).to_list(20)]
    return {"series": out, "stages": stages + ["New / Unassigned"]}


@router.get("/heatmap")
async def heatmap(type: str = "dow_hour", date_from: Optional[str] = None,
                  date_to: Optional[str] = None, user: dict = Depends(require_permission("reports"))):
    if type == "dow_hour":
        if not date_from:
            date_from = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
        match = build_match({"date_from": date_from, "date_to": date_to, "active": "all"}, user)
        # Group on precomputed create_dow / create_hour so this runs index-COVERED (no
        # per-document fetch, no per-document $dateFromString parse). $ifNull falls back
        # to parsing create_date_ist for any lead not yet backfilled, so results stay
        # correct (and still covered) while the one-time startup backfill is in flight.
        d = {"$dateFromString": {"dateString": "$create_date_ist", "format": "%Y-%m-%d %H:%M:%S", "onError": None}}
        dow = {"$ifNull": ["$create_dow", {"$dayOfWeek": d}]}
        hour = {"$ifNull": ["$create_hour", {"$hour": d}]}
        data = await db.leads.aggregate([
            {"$match": match},
            {"$group": {"_id": {"dow": dow, "hour": hour}, "count": {"$sum": 1}}},
            {"$match": {"_id.dow": {"$ne": None}}},
        ], maxTimeMS=20000, allowDiskUse=True).to_list(200)
        return {"type": "dow_hour", "date_from": date_from,
                "cells": [{"dow": r["_id"]["dow"], "hour": r["_id"]["hour"], "count": r["count"]} for r in data]}

    if type == "caller_day":
        if not date_from:
            date_from = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30) - timedelta(days=13)).strftime("%Y-%m-%d")
        match = build_match({"date_from": date_from, "date_to": date_to, "active": "all"}, user)
        data = await db.leads.aggregate([
            {"$match": match},
            {"$group": {"_id": {"u": "$user_id", "d": {"$substrCP": ["$create_date_ist", 0, 10]}}, "count": {"$sum": 1}}},
        ], maxTimeMS=20000, allowDiskUse=True).to_list(5000)
        users = {u["id"]: u["name"] for u in await db.users.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)}
        return {"type": "caller_day", "date_from": date_from,
                "cells": [{"user_id": r["_id"].get("u"), "user": users.get(r["_id"].get("u"), "Unassigned"),
                           "day": r["_id"].get("d"), "count": r["count"]} for r in data if r["_id"].get("d")]}
    raise HTTPException(status_code=400, detail="Invalid heatmap type")


@router.get("/dashboard")
async def dashboard(date_from: str = None, date_to: str = None, user: dict = Depends(get_current_user)):
    # Scope to the "Lead in Pipeline" working set (exclude raw, un-promoted Ozonetel
    # call-leads which carry pipeline=False) so the dashboard Today count + Funnel
    # match the "Lead in Pipeline" export for the same date range (Case 4 mismatch fix).
    base = {"active": True, "pipeline": {"$ne": False}}
    if user["role"] == "caller":
        base["user_id"] = user["id"]
    today = today_ist()
    month = today[:7]

    # Case 18 - optional date-range that scopes the funnel/leaderboard/tags/chart.
    has_range = bool(date_from or date_to)
    range_start = date_from or (month + "-01")
    range_end = date_to or today
    rng = {"create_date_ist": {"$gte": range_start, "$lte": range_end + " 23:59:59"}}
    range_match = {**base, **rng}

    # Default (no range) preserves all-time funnel; a chosen range scopes everything.
    stage_match = range_match if has_range else base
    board_match = rng if has_range else {"create_date_ist": {"$gte": month + "-01"}}
    tag_match = range_match if has_range else {**base, "create_date_ist": {"$gte": month + "-01"}}
    # by_day default view only renders the last 14 buckets, so bound the scan to a recent
    # window instead of grouping the entire (100k+) active collection every load.
    if has_range:
        by_day_match, by_day_limit = range_match, 60
    else:
        recent = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
        by_day_match, by_day_limit = {**base, "create_date_ist": {"$gte": recent}}, 14

    # These reads are all independent. Run them concurrently instead of awaiting ~14
    # sequential round-trips to Atlas one at a time (the root cause of the 8-18s load).
    (leads_today, leads_mtd, total_leads, converted_mtd, followups_today, followups_overdue,
     leads_range, converted_range, by_stage, by_day, leaderboard, top_tags,
     users_list, tag_list) = await asyncio.gather(
        db.leads.count_documents({**base, "create_date_ist": {"$gte": today}}),
        db.leads.count_documents({**base, "create_date_ist": {"$gte": month + "-01"}}),
        db.leads.count_documents(base),
        db.leads.count_documents({**base, "lead_stage": "Converted", "create_date_ist": {"$gte": month + "-01"}}),
        db.leads.count_documents({**base, "follow_up_date": today}),
        db.leads.count_documents({**base, "follow_up_date": {"$lt": today, "$gt": ""}}),
        db.leads.count_documents(range_match),
        db.leads.count_documents({**range_match, "lead_stage": "Converted"}),
        db.leads.aggregate([
            {"$match": stage_match},
            {"$group": {"_id": "$lead_stage", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ], allowDiskUse=True, maxTimeMS=20000).to_list(20),
        db.leads.aggregate([
            {"$match": by_day_match},
            {"$group": {"_id": {"$substrCP": ["$create_date_ist", 0, 10]}, "count": {"$sum": 1}}},
            {"$sort": {"_id": -1}}, {"$limit": by_day_limit},
        ], allowDiskUse=True, maxTimeMS=20000).to_list(60),
        db.leads.aggregate([
            {"$match": {**base, **board_match}},
            {"$group": {"_id": "$user_id", "count": {"$sum": 1},
                        "converted": {"$sum": {"$cond": [{"$eq": ["$lead_stage", "Converted"]}, 1, 0]}}}},
            {"$sort": {"count": -1}}, {"$limit": 10},
        ], allowDiskUse=True, maxTimeMS=20000).to_list(10),
        db.leads.aggregate([
            {"$match": tag_match},
            {"$unwind": "$tags"},
            {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}, {"$limit": 10},
        ], allowDiskUse=True, maxTimeMS=20000).to_list(10),
        db.users.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500),
        db.catalogs.find({"type": "tag"}, {"_id": 0, "id": 1, "name": 1}).to_list(500),
    )

    # Merge the null/False/"" stage buckets into a single "New / Unassigned" row so
    # the funnel shows one accurate row (and the frontend never gets duplicate React
    # keys from two identically-labelled rows).
    merged = {}
    for s in by_stage:
        key = "New / Unassigned" if s["_id"] in (None, False, "") else s["_id"]
        merged[key] = merged.get(key, 0) + s["count"]
    by_stage = sorted(
        [{"_id": k, "count": v} for k, v in merged.items()],
        key=lambda x: x["count"], reverse=True,
    )
    by_day.reverse()

    users = {u["id"]: u["name"] for u in users_list}
    for l in leaderboard:
        l["name"] = users.get(l["_id"], "Unassigned")

    tag_names = {t["id"]: t["name"] for t in tag_list}
    for t in top_tags:
        t["name"] = tag_names.get(t["_id"], str(t["_id"]))

    return {
        "leads_today": leads_today, "leads_mtd": leads_mtd, "total_leads": total_leads,
        "converted_mtd": converted_mtd, "followups_today": followups_today,
        "followups_overdue": followups_overdue, "by_stage": by_stage, "by_day": by_day,
        "leaderboard": leaderboard, "top_tags": top_tags, "today": today, "month_start": month + "-01",
        "range_start": range_start, "range_end": range_end,
        "leads_range": leads_range, "converted_range": converted_range,
    }


# --- KPI Performance Overview ("Lead Pulse") ---------------------------------
# Month-aware per-disposition FTD / MTD / YTD report matching the approved design.
# All 4 stages + their full fixed disposition list are ALWAYS returned (zero rows
# included). Counts are by lead creation date in IST. `%` is computed client-side
# against the period's TOTAL leads. Funnel / valid / conversion are derived on the
# client from the current-stage snapshot (no stage history needed). Cached 120s per
# (scope, month, today) — this is a low-concurrency admin/manager report.

_kpi_cache: dict = {}
_KPI_TTL = 120

# Fixed stage -> ordered disposition list (client-approved spec). Disposition names
# are matched to catalog tags by a normalised key so both int-id and string tag
# storage resolve correctly.
KPI_STAGES = [
    {"key": "attempt", "name": "Contact Attempt", "hex": "#E7A23C",
     "rows": ["Ringing", "Busy", "Phone Switched Off", "Not Reachable"]},
    {"key": "contacted", "name": "Contacted", "hex": "#2F6DE0",
     "rows": ["Call back for first pitch", "Call back for appointment", "OPD Booked"]},
    {"key": "converted", "name": "Converted", "hex": "#11A07B",
     "rows": ["OPD Done", "Registration Done", "Blood Test Booked", "Kits Booked", "Treatment Started"]},
    {"key": "closed", "name": "Closed — Lost / Invalid", "hex": "#8A97AB",
     "rows": ["Age Issue", "Duplicate Lead", "Already Have kid", "Already Pregnant",
              "Clinic Not Available", "Gender Selection", "Incoming Not Available", "Invalid Number",
              "Job Enquiry", "Junk", "Language Barrier", "Not Contactable",
              "Not Interested (Fund Issue)", "Not Interested (Competition)", "Not looking for treatment",
              "Relative Related Enquiry", "Sperm/Egg Donor", "Unmarried", "Valid Not Interested",
              "Wrong Number", "Abusive Language", "Not Eligible For Treatment"]},
]
_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


@router.get("/kpi-overview")
async def kpi_overview(month: Optional[str] = None, user: dict = Depends(require_permission("reports"))):
    today = today_ist()                       # YYYY-MM-DD (IST)
    cur_month = today[:7]                      # YYYY-MM
    if not (month and re.match(r"^\d{4}-\d{2}$", month)):
        month = cur_month
    is_current = month == cur_month
    y, mo = int(month[:4]), int(month[5:7])
    days_in_month = calendar.monthrange(y, mo)[1]
    month_start = f"{month}-01"
    ny, nmo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    next_month_start = f"{ny:04d}-{nmo:02d}-01"
    year_start = f"{y:04d}-01-01"              # YTD anchored to the selected month's year
    elapsed_days = int(today[8:10]) if is_current else days_in_month

    prev_label = prev_start = None
    prev_days = 0
    if mo > 1:
        pmo = mo - 1
        prev_start = f"{y:04d}-{pmo:02d}-01"
        prev_days = calendar.monthrange(y, pmo)[1]
        prev_label = f"{_MONTH_ABBR[pmo - 1]} {y}"

    ck = f"{user.get('id') if user.get('role') == 'caller' else 'all'}:{month}:{today}"
    now = time.time()
    hit = _kpi_cache.get(ck)
    if hit and now - hit[0] < _KPI_TTL:
        return hit[1]

    tags = await db.catalogs.find({"type": "tag"}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    id_to_name = {t["id"]: t["name"] for t in tags}

    base = {"active": True, "pipeline": {"$ne": False}}
    if user.get("role") == "caller":
        base["user_id"] = user["id"]

    match = {**base, "create_date_ist": {"$gte": year_start}}
    if not is_current:
        match["create_date_ist"] = {"$gte": year_start, "$lt": next_month_start}

    mtd_cond = {"$cond": [{"$gte": ["$create_date_ist", month_start]}, 1, 0]}
    ftd_cond = {"$cond": [{"$gte": ["$create_date_ist", today]}, 1, 0]}
    if prev_start:
        pmtd_cond = {"$cond": [{"$and": [{"$gte": ["$create_date_ist", prev_start]},
                                         {"$lt": ["$create_date_ist", month_start]}]}, 1, 0]}
    else:
        pmtd_cond = {"$literal": 0}
    sums = {"ytd": {"$sum": 1}, "mtd": {"$sum": mtd_cond},
            "ftd": {"$sum": ftd_cond}, "pmtd": {"$sum": pmtd_cond}}

    res = await db.leads.aggregate([
        {"$match": match},
        {"$facet": {
            "by_tag": [{"$unwind": "$tags"}, {"$group": {"_id": "$tags", **sums}}],
            "totals": [{"$group": {"_id": None, **sums}}],
        }},
    ], allowDiskUse=True, maxTimeMS=25000).to_list(1)
    res = res[0] if res else {"by_tag": [], "totals": []}

    # tags are stored as int catalog ids (migrated) or string names (some paths) —
    # normalise both to a canonical key and merge.
    norm_counts: dict = {}
    for r in res.get("by_tag", []):
        key = r.get("_id")
        if key is None or isinstance(key, bool):
            continue
        nm = id_to_name.get(int(key)) if isinstance(key, (int, float)) else str(key)
        nk = _norm(nm) if nm else None
        if not nk:
            continue
        acc = norm_counts.setdefault(nk, {"ftd": 0, "mtd": 0, "ytd": 0, "pmtd": 0})
        for f in ("ftd", "mtd", "ytd", "pmtd"):
            acc[f] += r.get(f, 0)

    def counts(name: str) -> dict:
        return norm_counts.get(_norm(name), {"ftd": 0, "mtd": 0, "ytd": 0, "pmtd": 0})

    stages = []
    prev_stage_totals = {}
    for st in KPI_STAGES:
        rows, tot = [], {"ftd": 0, "mtd": 0, "ytd": 0}
        pmtd_tot = 0
        for nm in st["rows"]:
            c = counts(nm)
            # Past-month "day" column is the month's per-day average.
            ftd_val = c["ftd"] if is_current else (round(c["mtd"] / days_in_month) if days_in_month else 0)
            rows.append({"name": nm, "ftd": ftd_val, "mtd": c["mtd"], "ytd": c["ytd"]})
            tot["ftd"] += ftd_val; tot["mtd"] += c["mtd"]; tot["ytd"] += c["ytd"]
            pmtd_tot += c["pmtd"]
        stages.append({"key": st["key"], "name": st["name"], "hex": st["hex"], "rows": rows, "totals": tot})
        prev_stage_totals[st["key"]] = pmtd_tot

    tt = (res.get("totals") or [{}])[0] or {}
    total_mtd = tt.get("mtd", 0)
    total = {
        "ftd": tt.get("ftd", 0) if is_current else (round(total_mtd / days_in_month) if days_in_month else 0),
        "mtd": total_mtd,
        "ytd": tt.get("ytd", 0),
    }

    max_mo = int(cur_month[5:7]) if y == int(cur_month[:4]) else 12
    months = [{"value": f"{y:04d}-{i:02d}", "label": f"{_MONTH_ABBR[i - 1]} {y}",
               "current": f"{y:04d}-{i:02d}" == cur_month} for i in range(1, max_mo + 1)]

    out = {
        "month": month, "is_current": is_current, "today": today,
        "days_in_month": days_in_month, "elapsed_days": max(elapsed_days, 1),
        "day_label": "FTD" if is_current else "Avg/Day",
        "month_label": "MTD" if is_current else "Month",
        "months": months,
        "prev_month": ({"label": prev_label, "days": prev_days, "stage_totals": prev_stage_totals}
                       if prev_label else None),
        "stages": stages,
        "total": total,
    }
    _kpi_cache[ck] = (now, out)
    return out
