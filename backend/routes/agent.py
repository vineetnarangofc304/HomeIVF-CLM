"""Agent break/status system (§5) + Agent Live Status + break reports."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user, require_roles
from core.utils import next_id, now_utc_str

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
    open_log = await db.status_logs.find_one({"user_id": user["id"], "end": None}, sort=[("start", -1)])
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
    return {"ok": True, "status": status, "since": now}


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
