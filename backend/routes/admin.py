import asyncio
import os
import re
import sys
import threading
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import require_roles, require_permission
from core.utils import next_id, now_utc_str

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/role-permissions")
async def get_role_perms(user: dict = Depends(require_roles("admin", "manager"))):
    from core.permissions import get_role_permissions, ALL_PERMS, MODULE_PERMS, ACTION_PERMS, PERM_LABELS
    return {"matrix": await get_role_permissions(), "all_perms": ALL_PERMS,
            "module_perms": MODULE_PERMS, "action_perms": ACTION_PERMS, "labels": PERM_LABELS}


class RolePermsBody(BaseModel):
    matrix: dict  # {"manager": {perm: bool}, "caller": {perm: bool}}


@router.patch("/role-permissions")
async def set_role_perms(body: RolePermsBody, user: dict = Depends(require_roles("admin"))):
    from core.permissions import get_role_permissions, ALL_PERMS
    current = await get_role_permissions()
    for role in ("manager", "caller"):
        incoming = body.matrix.get(role) or {}
        for k, v in incoming.items():
            if k in ALL_PERMS:
                current[role][k] = bool(v)
    await db.settings.update_one({"key": "role_permissions"},
        {"$set": {"key": "role_permissions", "value": {"manager": current["manager"], "caller": current["caller"]}}},
        upsert=True)
    from core.permissions import invalidate_role_permissions_cache
    invalidate_role_permissions_cache()
    return {"matrix": await get_role_permissions()}


@router.get("/settings")
async def get_settings(user: dict = Depends(require_roles("admin", "manager"))):
    docs = await db.settings.find({}, {"_id": 0}).to_list(50)
    return {d["key"]: d for d in docs}


class SettingBody(BaseModel):
    key: str
    value: dict


@router.patch("/settings")
async def update_setting(body: SettingBody, user: dict = Depends(require_roles("admin"))):
    await db.settings.update_one({"key": body.key}, {"$set": {**body.value, "key": body.key}}, upsert=True)
    return await db.settings.find_one({"key": body.key}, {"_id": 0})


class AutomationBody(BaseModel):
    name: str
    trigger: str  # on_create | on_stage_set | on_tag_set
    condition: dict = {}
    actions: list = []
    active: bool = True


@router.get("/automations")
async def list_automations(user: dict = Depends(require_roles("admin", "manager"))):
    return await db.automations.find({}, {"_id": 0}).sort("id", 1).to_list(200)


@router.post("/automations")
async def create_automation(body: AutomationBody, user: dict = Depends(require_roles("admin"))):
    if body.trigger not in ("on_create", "on_stage_set", "on_tag_set"):
        raise HTTPException(status_code=400, detail="Invalid trigger")
    aid = await next_id("automation")
    doc = {"id": aid, **body.model_dump(), "created_at": now_utc_str()}
    await db.automations.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/automations/{aid}")
async def update_automation(aid: int, body: dict, user: dict = Depends(require_roles("admin"))):
    allowed = {"name", "trigger", "condition", "actions", "active"}
    updates = {k: v for k, v in body.items() if k in allowed}
    res = await db.automations.update_one({"id": aid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return await db.automations.find_one({"id": aid}, {"_id": 0})


@router.delete("/automations/{aid}")
async def delete_automation(aid: int, user: dict = Depends(require_roles("admin"))):
    await db.automations.delete_one({"id": aid})
    return {"ok": True}


@router.get("/outbound_queue")
async def outbound_queue(user: dict = Depends(require_roles("admin", "manager"))):
    items = await db.outbound_queue.find({}, {"_id": 0}).sort("created_at", -1).limit(200).to_list(200)
    return items


# ---------- Case 1: Duplicate lead cleanup (scan preview + confirm delete) ----------
def _dup_scan_worker(date_from, date_to, scan_id, source=None):
    """Find leads that share a phone number, keeping the OLDEST per phone and flagging
    the newer duplicates CREATED within [date_from, date_to] for deletion. Optionally
    scoped to a single lead SOURCE so only that source's duplicates are cleaned (e.g.
    "Website AI Agent"), leaving other sources untouched. Runs on a background thread;
    result stored in settings.dup_scan.

    Indexed two-step approach (avoids a full-collection $group that trips MongoDB's
    operation time limit on large datasets):
      1) distinct phone_digits among leads CREATED in the window (uses create_date index)
      2) fetch only leads sharing those phones (uses phone_digits index) and group in-memory."""
    from pymongo import MongoClient
    sdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    fields = ["id", "name", "phone", "create_date", "user_id", "stage_id", "active", "source_lead"]
    try:
        try:
            sdb.leads.create_index("phone_digits")
            sdb.leads.create_index("create_date")
        except Exception:
            pass
        lo, hi = f"{date_from} 00:00:00", f"{date_to} 23:59:59"
        window_match = {"create_date": {"$gte": lo, "$lte": hi}, "phone_digits": {"$nin": [None, ""]}}
        if source:
            window_match["source_lead"] = source
        window_phones = [p for p in sdb.leads.distinct("phone_digits", window_match) if p]
        groups_out, cand_ids = [], []
        for i in range(0, len(window_phones), 400):
            chunk = window_phones[i:i + 400]
            proj = {"_id": 0, "phone_digits": 1, **{f: 1 for f in fields}}
            fetch_q = {"phone_digits": {"$in": chunk}}
            if source:
                fetch_q["source_lead"] = source
            by_combo = {}
            for l in sdb.leads.find(fetch_q, proj):
                key = ((l.get("name") or "").strip().lower(), l.get("phone_digits"))
                by_combo.setdefault(key, []).append(l)
            for (nm, ph), grp in by_combo.items():
                if len(grp) < 2:
                    continue
                keeper = min(grp, key=lambda l: l.get("create_date") or "9999")
                cands = [l for l in grp if l["id"] != keeper["id"]
                         and l.get("create_date") and lo <= l["create_date"] <= hi]
                if not cands:
                    continue
                slim = lambda l: {f: l.get(f) for f in fields}
                groups_out.append({"phone": ph, "name": keeper.get("name") or "—",
                                   "keeper": slim(keeper), "candidates": [slim(c) for c in cands]})
                cand_ids += [c["id"] for c in cands]
        sdb.settings.update_one({"key": "dup_scan"}, {"$set": {
            "key": "dup_scan", "status": "done", "scan_id": scan_id,
            "date_from": date_from, "date_to": date_to, "source": source or "",
            "groups": groups_out[:1000], "group_count": len(groups_out),
            "candidate_ids": cand_ids, "total_delete": len(cand_ids),
            "scanned_at": now_utc_str()}}, upsert=True)
    except Exception:
        err = traceback.format_exc()
        try:
            sdb.settings.update_one({"key": "dup_scan"}, {"$set": {
                "key": "dup_scan", "status": "error", "error": err[-500:], "scan_id": scan_id}}, upsert=True)
        except Exception:
            pass


class DupScanBody(BaseModel):
    date_from: str
    date_to: str
    source: Optional[str] = None


@router.post("/duplicates/scan")
async def dup_scan(body: DupScanBody, user: dict = Depends(require_roles("admin"))):
    scan_id = int(datetime.now(timezone.utc).timestamp())
    src = (body.source or "").strip() or None
    await db.settings.update_one({"key": "dup_scan"}, {"$set": {
        "key": "dup_scan", "status": "running", "scan_id": scan_id,
        "date_from": body.date_from, "date_to": body.date_to, "source": src or "",
        "started_at": now_utc_str(), "started_by": user["name"]}}, upsert=True)
    threading.Thread(target=_dup_scan_worker, args=(body.date_from, body.date_to, scan_id, src),
                     name="dup-scan", daemon=True).start()
    return {"status": "running", "scan_id": scan_id}


@router.get("/duplicates/scan/status")
async def dup_scan_status(user: dict = Depends(require_roles("admin"))):
    doc = await db.settings.find_one({"key": "dup_scan"}, {"_id": 0})
    return doc or {"status": "none"}


class DupDeleteBody(BaseModel):
    scan_id: int


@router.post("/duplicates/delete")
async def dup_delete(body: DupDeleteBody, user: dict = Depends(require_roles("admin"))):
    scan = await db.settings.find_one({"key": "dup_scan"}, {"_id": 0})
    if not scan or scan.get("status") != "done":
        raise HTTPException(status_code=400, detail="Run a duplicate scan first")
    if scan.get("scan_id") != body.scan_id:
        raise HTTPException(status_code=409, detail="Scan changed — please re-scan before deleting")
    ids = scan.get("candidate_ids") or []
    if not ids:
        return {"deleted": 0}
    # archive to deleted_leads (reversible) before hard-deleting
    docs = await db.leads.find({"id": {"$in": ids}}).to_list(None)
    now = now_utc_str()
    for d in docs:
        d.pop("_id", None)
        d["deleted_at"] = now
        d["deleted_by"] = user["name"]
        d["deleted_reason"] = f"duplicate cleanup {scan.get('date_from')}..{scan.get('date_to')}"
    if docs:
        await db.deleted_leads.insert_many(docs)
    res = await db.leads.delete_many({"id": {"$in": ids}})
    await db.follow_ups.delete_many({"lead_id": {"$in": ids}})
    await db.settings.update_one({"key": "dup_scan"}, {"$set": {
        "status": "deleted", "deleted": res.deleted_count, "deleted_at": now, "deleted_by": user["name"]}})
    return {"deleted": res.deleted_count, "archived": len(docs)}
