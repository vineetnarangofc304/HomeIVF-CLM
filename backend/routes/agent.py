"""Agent break/status system (§5) + Agent Live Status + break reports."""
import re
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user, require_roles
from core.utils import next_id, now_utc_str, drain_lead_queue

router = APIRouter(prefix="/agent", tags=["agent"])

BREAK_STATUSES = {"Lunch Break", "Washroom Break", "Refreshment Break", "Meeting"}
VALID_STATUSES = {"Available", "On Call", "Offline"} | BREAK_STATUSES
FMT = "%Y-%m-%d %H:%M:%S"


def _secs_since(start: str) -> int:
    try:
        s = datetime.strptime(start, FMT).replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - s).total_seconds()))
    except Exception:
        return 0


class StatusBody(BaseModel):
    status: str


@router.post("/status")
async def set_status(body: StatusBody, user: dict = Depends(get_current_user)):
    status = body.status.strip()
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    now = now_utc_str()
    # close the currently-open status log
    open_log = await db.status_logs.find_one(
        {"user_id": user["id"], "end": None}, sort=[("start", -1)], max_time_ms=8000)
    if open_log:
        await db.status_logs.update_one(
            {"id": open_log["id"]},
            {"$set": {"end": now, "duration_sec": _secs_since(open_log["start"])}},
        )
    # open a new one + update the user
    lid = await next_id("status_log")
    await db.status_logs.insert_one({
        "id": lid, "user_id": user["id"], "user_name": user["name"], "status": status,
        "is_break": status in BREAK_STATUSES, "start": now, "end": None, "duration_sec": None,
        "date": now[:10],
    })
    await db.users.update_one({"id": user["id"]}, {"$set": {"status": status, "status_since": now}})
    # Case 2 — becoming Available/On Call pulls queued leads. Runs in the BACKGROUND
    # (single-flight, bounded) so the status change returns instantly and a large queue
    # can never make this request hang / hold a DB connection (previously caused the
    # 24-caller morning rush to exhaust the pool → 500s).
    if status in {"Available", "On Call"}:
        asyncio.create_task(drain_lead_queue())
    return {"ok": True, "status": status, "since": now}


class AdminStatusBody(BaseModel):
    user_id: int
    status: str = "Offline"


@router.post("/admin/set-status")
async def admin_set_status(body: AdminStatusBody, user: dict = Depends(require_roles("admin", "manager"))):
    """Case 2 — admin/manager manually overrides a caller's presence (e.g. force Offline
    when a caller forgot to). Setting Offline immediately stops new-lead assignment to them
    (routing reads users.status live). Setting Available/On Call drains the waiting queue."""
    status = body.status.strip()
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    target = await db.users.find_one({"id": body.user_id}, {"_id": 0, "id": 1, "name": 1})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    now = now_utc_str()
    open_log = await db.status_logs.find_one(
        {"user_id": body.user_id, "end": None}, sort=[("start", -1)], max_time_ms=8000)
    if open_log:
        await db.status_logs.update_one(
            {"id": open_log["id"]},
            {"$set": {"end": now, "duration_sec": _secs_since(open_log["start"])}},
        )
    lid = await next_id("status_log")
    await db.status_logs.insert_one({
        "id": lid, "user_id": body.user_id, "user_name": target["name"], "status": status,
        "is_break": status in BREAK_STATUSES, "start": now, "end": None, "duration_sec": None,
        "date": now[:10], "set_by_admin": user["name"],
    })
    await db.users.update_one({"id": body.user_id}, {"$set": {"status": status, "status_since": now}})
    if status in {"Available", "On Call"}:
        asyncio.create_task(drain_lead_queue())
    return {"ok": True, "user_id": body.user_id, "status": status, "by": user["name"]}


@router.get("/me")
async def my_status(user: dict = Depends(get_current_user)):
    u = await db.users.find_one({"id": user["id"]}, {"_id": 0, "status": 1, "status_since": 1})
    return {"status": (u or {}).get("status") or "Offline", "since": (u or {}).get("status_since")}


@router.get("/live")
async def live_agents(user: dict = Depends(require_roles("admin", "manager"))):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = []
    async for u in db.users.find({"active": True}, {"_id": 0, "id": 1, "name": 1, "role": 1, "status": 1, "status_since": 1}):
        status = u.get("status") or "Offline"
        # today's break seconds (closed logs + the open one if currently on break)
        break_secs = 0
        async for lg in db.status_logs.find({"user_id": u["id"], "date": today, "is_break": True}):
            break_secs += lg.get("duration_sec") if lg.get("duration_sec") is not None else _secs_since(lg["start"])
        out.append({
            "id": u["id"], "name": u["name"], "role": u.get("role"),
            "status": status, "since": u.get("status_since"),
            "since_seconds": _secs_since(u["status_since"]) if u.get("status_since") else 0,
            "break_seconds_today": break_secs,
        })
    order = {"On Call": 0, "Available": 1}
    out.sort(key=lambda a: (order.get(a["status"], 2), a["name"]))
    return out


def _to_int(v) -> int:
    try:
        return int(float(v))
    except Exception:
        return 0


@router.get("/analytics")
async def agent_analytics(date: str = None, user: dict = Depends(get_current_user)):
    """§6 Agent productivity & call analytics for a single day (IST).
    Managers/admins see the full agent roster; callers see only their own row."""
    day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    is_mgr = user["role"] in ("admin", "manager")

    uq = {"active": True} if is_mgr else {"id": user["id"]}
    users = await db.users.find(uq, {"_id": 0, "id": 1, "name": 1, "role": 1}).to_list(500)
    umap = {u["id"]: u for u in users}
    rows = {uid: {"total": 0, "connected": 0, "missed": 0, "outbound": 0, "incoming": 0,
                  "_dur_sum": 0, "talk_time": 0, "conversions": 0, "break_seconds": 0}
            for uid in umap}

    cq = {"created_at_ist": {"$regex": f"^{day}"}}
    if not is_mgr:
        cq["user_id"] = user["id"]
    async for c in db.call_events.find(cq, {"_id": 0, "user_id": 1, "direction": 1, "status": 1,
                                            "duration": 1, "talk_time": 1, "disposition": 1}):
        uid = c.get("user_id")
        if uid not in rows:
            continue
        r = rows[uid]
        r["total"] += 1
        if c.get("direction") == "outbound":
            r["outbound"] += 1
        else:
            r["incoming"] += 1
        if c.get("status") == "connected":
            r["connected"] += 1
            r["_dur_sum"] += _to_int(c.get("duration"))
        elif c.get("status") == "missed":
            r["missed"] += 1
        r["talk_time"] += _to_int(c.get("talk_time"))
        if (c.get("disposition") or "") == "Converted":
            r["conversions"] += 1

    bq = {"date": day, "is_break": True}
    if not is_mgr:
        bq["user_id"] = user["id"]
    async for lg in db.status_logs.find(bq):
        uid = lg.get("user_id")
        if uid in rows:
            rows[uid]["break_seconds"] += lg.get("duration_sec") if lg.get("duration_sec") is not None else _secs_since(lg["start"])

    out = []
    for uid, r in rows.items():
        avg = int(r["_dur_sum"] / r["connected"]) if r["connected"] else 0
        rate = round(r["connected"] / r["total"] * 100) if r["total"] else 0
        out.append({
            "user_id": uid, "name": umap[uid]["name"], "role": umap[uid].get("role"),
            "total": r["total"], "connected": r["connected"], "missed": r["missed"],
            "outbound": r["outbound"], "incoming": r["incoming"], "avg_duration": avg,
            "talk_time": r["talk_time"], "conversions": r["conversions"],
            "break_seconds": r["break_seconds"], "connect_rate": rate,
        })
    if is_mgr:
        out = [o for o in out if o["total"] > 0 or o["break_seconds"] > 0]
    out.sort(key=lambda x: (-x["total"], -x["connected"], x["name"]))

    totals = {k: sum(o[k] for o in out) for k in ("total", "connected", "missed", "outbound", "incoming", "talk_time", "conversions", "break_seconds")}
    totals["connect_rate"] = round(totals["connected"] / totals["total"] * 100) if totals["total"] else 0
    return {"date": day, "is_manager": is_mgr, "agents": out, "totals": totals}


@router.get("/status-logs")
async def status_logs(date: str = None, user_id: int = None, breaks_only: bool = True,
                      user: dict = Depends(require_roles("admin", "manager"))):
    q = {}
    q["date"] = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if user_id:
        q["user_id"] = user_id
    if breaks_only:
        q["is_break"] = True
    logs = await db.status_logs.find(q, {"_id": 0}).sort("start", -1).to_list(500)
    for lg in logs:
        if lg.get("duration_sec") is None:
            lg["duration_sec"] = _secs_since(lg["start"])
            lg["ongoing"] = True
    return logs



STATUS_ORDER = ["Available", "On Call", "Lunch Break", "Washroom Break", "Refreshment Break", "Meeting", "Offline"]


@router.get("/attendance")
async def attendance(date: str = None, month: str = None, user_id: int = None,
                     user: dict = Depends(require_roles("admin", "manager"))):
    """Case 2 — day-wise or month-wise attendance. Per-caller time in each status
    (Available / On Call / breaks / Offline), working vs break totals, first/last seen,
    and (when user_id is passed) that caller's full status timeline for the period."""
    if month:
        match = {"date": {"$regex": f"^{re.escape(month)}"}}
        period, mode = month, "month"
    else:
        day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        match = {"date": day}
        period, mode = day, "day"

    users = await db.users.find(
        {"active": True}, {"_id": 0, "id": 1, "name": 1, "role": 1, "status": 1, "status_since": 1}).to_list(500)
    umap = {u["id"]: u for u in users}
    rows = {uid: {"user_id": uid, "name": umap[uid]["name"], "role": umap[uid].get("role"),
                  "current_status": umap[uid].get("status") or "Offline",
                  "current_since": umap[uid].get("status_since"),
                  "by_status": {}, "first_seen": None, "last_seen": None, "days": set()}
            for uid in umap}

    async for lg in db.status_logs.find(match):
        uid = lg.get("user_id")
        if uid not in rows:
            continue
        secs = lg.get("duration_sec") if lg.get("duration_sec") is not None else _secs_since(lg["start"])
        st = lg.get("status") or "Offline"
        r = rows[uid]
        r["by_status"][st] = r["by_status"].get(st, 0) + secs
        if lg.get("date"):
            r["days"].add(lg["date"])
        if r["first_seen"] is None or lg["start"] < r["first_seen"]:
            r["first_seen"] = lg["start"]
        end = lg.get("end") or lg["start"]
        if r["last_seen"] is None or end > r["last_seen"]:
            r["last_seen"] = end

    out = []
    for uid, r in rows.items():
        bs = r["by_status"]
        working = bs.get("Available", 0) + bs.get("On Call", 0)
        brk = sum(bs.get(s, 0) for s in BREAK_STATUSES)
        offline = bs.get("Offline", 0)
        present = bool(r["first_seen"]) and (working + brk) > 0
        # Callers always appear (present or absent); managers/admins only when they logged status.
        if r["role"] != "caller" and not r["first_seen"]:
            continue
        out.append({
            "user_id": uid, "name": r["name"], "role": r["role"],
            "current_status": r["current_status"], "current_since": r["current_since"],
            "by_status": bs, "first_seen": r["first_seen"], "last_seen": r["last_seen"],
            "working_seconds": working, "break_seconds": brk, "offline_seconds": offline,
            "days_present": len(r["days"]), "present": present,
        })
    out.sort(key=lambda x: (0 if x["present"] else 1, -x["working_seconds"], x["name"]))

    timeline = []
    if user_id:
        tl = await db.status_logs.find({**match, "user_id": user_id}, {"_id": 0}).sort("start", 1).to_list(3000)
        for lg in tl:
            if lg.get("duration_sec") is None:
                lg["duration_sec"] = _secs_since(lg["start"])
                lg["ongoing"] = True
        timeline = tl

    totals = {
        "working_seconds": sum(o["working_seconds"] for o in out),
        "break_seconds": sum(o["break_seconds"] for o in out),
        "present_count": sum(1 for o in out if o["present"]),
        "caller_count": sum(1 for o in out if o["role"] == "caller"),
    }
    return {"period": period, "mode": mode, "status_order": STATUS_ORDER,
            "rows": out, "timeline": timeline, "totals": totals}


@router.get("/queue")
async def lead_queue_status(user: dict = Depends(require_roles("admin", "manager"))):
    """Case 2 — leads waiting for a caller to become Available (assigned when someone does)."""
    total = await db.lead_queue.count_documents({})
    items = await db.lead_queue.find({}, {"_id": 0}).sort("lead_id", 1).limit(50).to_list(50)
    lead_ids = [it["lead_id"] for it in items]
    leads = {l["id"]: l for l in await db.leads.find(
        {"id": {"$in": lead_ids}}, {"_id": 0, "id": 1, "contact_name": 1, "name": 1, "phone": 1, "source_lead": 1}).to_list(50)}
    out = []
    for it in items:
        l = leads.get(it["lead_id"], {})
        out.append({"lead_id": it["lead_id"], "queued_at": it.get("queued_at"),
                    "name": l.get("contact_name") or l.get("name") or f"Lead {it['lead_id']}",
                    "phone": l.get("phone"), "source": l.get("source_lead")})
    return {"total": total, "items": out}
