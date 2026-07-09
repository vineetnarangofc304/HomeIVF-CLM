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
    return {"matrix": await get_role_permissions()}


@router.get("/migration/status")
async def migration_status(user: dict = Depends(require_roles("admin", "manager"))):
    items = await db.migration_status.find({}, {"_id": 0}).to_list(50)
    counts = {}
    for coll in ["leads", "messages", "wa_channels", "wa_messages", "contacts", "users", "catalogs",
                 "templates_email", "templates_whatsapp", "activities"]:
        counts[coll] = await db[coll].estimated_document_count()
    return {"entities": items, "counts": counts}


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


@router.post("/whatsapp/sync-odoo-templates")
async def sync_odoo_wa_templates(user: dict = Depends(require_roles("admin"))):
    """Pull approved Meta template names (template_name) + language from Odoo's
    whatsapp.template records and link them onto the CRM WhatsApp templates so
    live Cloud-API sending uses the exact approved template."""
    import asyncio
    import xmlrpc.client

    def fetch():
        url, dbn = os.environ["ODOO_URL"], os.environ["ODOO_DB"]
        login, pwd = os.environ["ODOO_LOGIN"], os.environ["ODOO_PASSWORD"]
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        uid = common.authenticate(dbn, login, pwd, {})
        if not uid:
            raise HTTPException(status_code=503, detail="Odoo authentication failed")
        models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
        return models.execute_kw(dbn, uid, pwd, "whatsapp.template", "search_read", [[]],
            {"fields": ["name", "template_name", "status", "lang_code", "template_type", "body"]})

    recs = await asyncio.to_thread(fetch)
    updated = created = skipped = 0
    for r in recs:
        meta_name = (r.get("template_name") or "").strip()
        name = (r.get("name") or "").strip()
        if not meta_name or not name:
            skipped += 1
            continue
        fields = {
            "wa_template_name": meta_name,
            "lang": r.get("lang_code") or "en",
            "status": (r.get("status") or "approved"),
            "template_type": (r.get("template_type") or "").lower() or "utility",
        }
        existing = await db.templates_whatsapp.find_one(
            {"$or": [{"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}},
                     {"wa_template_name": meta_name}]})
        if existing:
            await db.templates_whatsapp.update_one({"id": existing["id"]}, {"$set": fields})
            updated += 1
        else:
            tid = await next_id("template_whatsapp")
            await db.templates_whatsapp.insert_one({
                "id": tid, "name": name, "body": r.get("body") or "",
                "active": True, "created_at": now_utc_str(), **fields})
            created += 1
    return {"ok": True, "odoo_templates": len(recs), "linked_updated": updated,
            "created": created, "skipped_no_meta_name": skipped}


@router.get("/outbound_queue")
async def outbound_queue(user: dict = Depends(require_roles("admin", "manager"))):
    items = await db.outbound_queue.find({}, {"_id": 0}).sort("created_at", -1).limit(200).to_list(200)
    return items


async def _next_since():
    """Cheap, never-raising computation of the delta-sync window start.
    Prefers the recorded last_sync 'until' (a tiny settings lookup); only if that
    is missing does it fall back to a single $max on migrated leads. On any DB
    slowness/error it returns None (=> the caller treats it as a FULL import)."""
    last_sync = await db.settings.find_one({"key": "last_sync"}, {"_id": 0})
    base = last_sync.get("until") if last_sync else None
    if not base:
        try:
            agg = await db.leads.aggregate([
                {"$match": {"migrated": True}},
                {"$group": {"_id": None, "m": {"$max": "$write_date"}}},
            ], maxTimeMS=8000).to_list(1)
            base = agg[0]["m"] if agg and agg[0].get("m") else None
        except Exception:
            base = None
    if base:
        try:
            base = (datetime.strptime(base, "%Y-%m-%d %H:%M:%S") - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return base


@router.get("/sync/status")
async def sync_status(user: dict = Depends(require_roles("admin", "manager"))):
    """Reconciliation snapshot: last record per entity, last sync, counts, and the window a new sync would cover."""
    async def max_field(coll, field, match=None):
        try:
            agg = await db[coll].aggregate([
                {"$match": match or {}},
                {"$group": {"_id": None, "m": {"$max": f"${field}"}}},
            ], maxTimeMS=8000).to_list(1)
            return agg[0]["m"] if agg and agg[0].get("m") else None
        except Exception:
            return None

    last_record = {
        "leads_write_date": await max_field("leads", "write_date", {"migrated": True}),
        "leads_create_date": await max_field("leads", "create_date", {"migrated": True}),
        "lead_messages_date": await max_field("messages", "date", {"migrated": True}),
        "wa_messages_date": await max_field("wa_messages", "date", {"migrated": True}),
        "contacts_create_date": await max_field("contacts", "create_date", {"migrated": True}),
    }
    counts = {}
    for coll in ["leads", "messages", "wa_channels", "wa_messages", "contacts", "users",
                 "templates_email", "templates_whatsapp", "activities"]:
        try:
            counts[coll] = await db[coll].estimated_document_count()
        except Exception:
            counts[coll] = 0
    try:
        counts["leads_migrated"] = await db.leads.count_documents({"migrated": True}, maxTimeMS=8000)
    except Exception:
        counts["leads_migrated"] = 0
    counts["leads_created_in_crm"] = max(counts.get("leads", 0) - counts["leads_migrated"], 0)

    last_sync = await db.settings.find_one({"key": "last_sync"}, {"_id": 0})
    running = await db.sync_runs.find_one({"status": "running"}, {"_id": 0})
    # Self-heal dead runs: a sync executes on an in-process thread. If that thread
    # is no longer alive (crashed, or the backend process was restarted/redeployed
    # mid-sync) the DB doc stays "running" forever and permanently disables the
    # Sync button. Detect it and clear it so the button re-enables immediately.
    if running:
        rid_r = running.get("run_id")
        alive = rid_r is not None and any(
            t.name == f"odoo-sync-{rid_r}" and t.is_alive() for t in threading.enumerate())
        if not alive:
            await db.sync_runs.update_one({"_id": running["_id"]} if running.get("_id") else {"run_id": rid_r}, {"$set": {
                "status": "error", "error": "sync worker no longer running (process restarted or crashed)",
                "finished_at": now_utc_str()}})
            running = None

    # window a new sync would cover (cheap, never raises)
    next_since = await _next_since()
    return {"last_record": last_record, "counts": counts, "last_sync": last_sync,
            "running": running, "next_since": next_since, "now": now_utc_str(),
            "mode": "delta" if next_since else "full"}


@router.post("/sync/start")
async def sync_start(user: dict = Depends(require_roles("admin"))):
    running = await db.sync_runs.find_one({"status": "running"})
    if running:
        rid_r = running.get("run_id")
        alive = rid_r is not None and any(
            t.name == f"odoo-sync-{rid_r}" and t.is_alive() for t in threading.enumerate())
        if alive:
            raise HTTPException(status_code=409, detail="A sync is already running")
        # dead run (thread gone) — supersede it so this fresh sync can proceed
        await db.sync_runs.update_one({"_id": running["_id"]}, {"$set": {
            "status": "error", "error": "superseded - worker no longer running",
            "finished_at": now_utc_str()}})

    next_since = await _next_since()
    mode = "delta" if next_since else "full"
    since = next_since or "1970-01-01 00:00:00"
    until = now_utc_str()
    rid = await next_id("sync_run")
    await db.sync_runs.insert_one({"run_id": rid, "status": "running", "mode": mode,
                                   "since": since, "until": until, "started_at": now_utc_str(),
                                   "started_by": user["name"], "progress": {}})

    # Run the sync in-process on a background thread. This is far more robust in a
    # managed/container deployment than spawning a detached subprocess + writing a
    # log file (which can fail on a read-only FS). Progress is tracked in `sync_runs`.
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mig_dir = os.path.join(backend_dir, "migration")

    def _worker():
        if mig_dir not in sys.path:
            sys.path.insert(0, mig_dir)
        try:
            import odoo_sync
            odoo_sync.run_sync(rid, since, until)
        except Exception:  # import/connect failure — record it on the run via a sync client
            err = traceback.format_exc()
            try:
                from pymongo import MongoClient
                sdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
                sdb.sync_runs.update_one({"run_id": rid}, {"$set": {
                    "status": "error", "error": err[-800:],
                    "finished_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}})
            except Exception:
                pass

    threading.Thread(target=_worker, name=f"odoo-sync-{rid}", daemon=True).start()
    return {"run_id": rid, "since": since, "until": until, "mode": mode}


@router.get("/sync/runs/{run_id}")
async def sync_run(run_id: int, user: dict = Depends(require_roles("admin", "manager"))):
    run = await db.sync_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/sync/runs")
async def sync_runs(user: dict = Depends(require_roles("admin", "manager"))):
    return await db.sync_runs.find({}, {"_id": 0}).sort("run_id", -1).limit(10).to_list(10)


AUDIT_NOTES = {
    "whatsapp_messages": "Odoo count includes messages in non-WhatsApp internal channels; CRM migrates WhatsApp-channel messages only.",
    "open_activities": "Odoo deletes activities once marked done — only OPEN activities exist to migrate. Completed activity history lives in lead chatter.",
    "lead_chatter_messages": "Odoo count grows live as your team keeps using Odoo; rerun migration script to sync deltas.",
}


def _audit_worker(started_by):
    """Runs the live Odoo-vs-CRM audit on a background thread and stores the result
    in settings.last_audit. Decoupled from the HTTP request so the ~20-40s of Odoo
    round-trips can never hit an ingress/gateway timeout."""
    mig_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migration")
    if mig_dir not in sys.path:
        sys.path.insert(0, mig_dir)
    try:
        from odoo_migrate import call as odoo_call, db as sdb  # resilient (timeout+retry+reauth) client

        def c(model, domain):
            try:
                return odoo_call(model, "search_count", domain)
            except Exception:
                return -1

        odoo = {
            "leads": c("crm.lead", [["active", "in", [True, False]]]),
            "lead_chatter_messages": c("mail.message", [["model", "=", "crm.lead"], ["body", "!=", ""]]),
            "whatsapp_conversations": c("discuss.channel", [["channel_type", "=", "whatsapp"]]),
            "whatsapp_messages": c("mail.message", [["model", "=", "discuss.channel"], ["body", "!=", ""]]),
            "contacts": c("res.partner", []),
            "users": c("res.users", [["share", "=", False]]),
            "tags": c("crm.tag", []),
            "pipeline_stages": c("crm.stage", []),
            "lost_reasons": c("crm.lost.reason", []),
            "open_activities": c("mail.activity", [["res_model", "=", "crm.lead"]]),
            "email_templates": c("mail.template", []),
            "whatsapp_templates": c("whatsapp.template", []),
            "utm_sources": c("utm.source", []),
            "utm_mediums": c("utm.medium", []),
            "utm_campaigns": c("utm.campaign", []),
        }
        crm = {
            "leads": sdb.leads.count_documents({"migrated": True}),
            "lead_chatter_messages": sdb.messages.count_documents({"migrated": True}),
            "whatsapp_conversations": sdb.wa_channels.count_documents({"migrated": True}),
            "whatsapp_messages": sdb.wa_messages.count_documents({"migrated": True}),
            "contacts": sdb.contacts.count_documents({"migrated": True}),
            "users": sdb.users.count_documents({"odoo_user": True}),
            "tags": sdb.catalogs.count_documents({"type": "tag"}),
            "pipeline_stages": sdb.catalogs.count_documents({"type": "stage"}),
            "lost_reasons": sdb.catalogs.count_documents({"type": "lost_reason"}),
            "open_activities": sdb.activities.count_documents({"migrated": True}),
            "email_templates": sdb.templates_email.count_documents({"migrated": True}),
            "whatsapp_templates": sdb.templates_whatsapp.count_documents({"migrated": True}),
            "utm_sources": sdb.catalogs.count_documents({"type": "utm_source"}),
            "utm_mediums": sdb.catalogs.count_documents({"type": "utm_medium"}),
            "utm_campaigns": sdb.catalogs.count_documents({"type": "utm_campaign"}),
        }
        rows = []
        for k, ov in odoo.items():
            cv = crm.get(k, 0)
            ok = (cv >= ov) if k != "whatsapp_messages" else (cv > 0 and abs(cv - ov) / max(ov, 1) < 0.1)
            rows.append({"entity": k, "odoo": ov, "crm": cv, "match": bool(ok), "note": AUDIT_NOTES.get(k)})
        sdb.settings.update_one({"key": "last_audit"}, {"$set": {
            "key": "last_audit", "status": "done", "rows": rows, "ran_at": now_utc_str(),
            "started_by": started_by, "error": None,
            "all_match": all(r["match"] for r in rows if r["odoo"] >= 0)}}, upsert=True)
    except Exception:
        err = traceback.format_exc()
        try:
            from pymongo import MongoClient
            edb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
            edb.settings.update_one({"key": "last_audit"}, {"$set": {
                "key": "last_audit", "status": "error", "error": err[-500:],
                "ran_at": now_utc_str(), "started_by": started_by}}, upsert=True)
        except Exception:
            pass


@router.post("/migration/audit")
async def migration_audit(user: dict = Depends(require_roles("admin", "manager"))):
    """Start a background Odoo-vs-CRM audit. Poll GET /migration/audit/status for the result."""
    current = await db.settings.find_one({"key": "last_audit"}, {"_id": 0})
    if current and current.get("status") == "running":
        started = current.get("started_at", "")
        stale = started < (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        if not stale:
            return {"status": "running"}
    await db.settings.update_one({"key": "last_audit"}, {"$set": {
        "key": "last_audit", "status": "running", "started_at": now_utc_str(),
        "started_by": user["name"]}}, upsert=True)
    threading.Thread(target=_audit_worker, args=(user["name"],), name="odoo-audit", daemon=True).start()
    return {"status": "running"}


@router.get("/migration/audit/status")
async def migration_audit_status(user: dict = Depends(require_roles("admin", "manager"))):
    doc = await db.settings.find_one({"key": "last_audit"}, {"_id": 0})
    return doc or {"status": "none"}



# ---------- Case 1: Duplicate lead cleanup (scan preview + confirm delete) ----------
def _dup_scan_worker(date_from, date_to, scan_id):
    """Find leads that share a phone number, keeping the OLDEST per phone and flagging
    the newer duplicates CREATED within [date_from, date_to] for deletion. Runs on a
    background thread; result stored in settings.dup_scan.

    Indexed two-step approach (avoids a full-collection $group that trips MongoDB's
    operation time limit on large datasets):
      1) distinct phone_digits among leads CREATED in the window (uses create_date index)
      2) fetch only leads sharing those phones (uses phone_digits index) and group in-memory."""
    from pymongo import MongoClient
    sdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    fields = ["id", "name", "phone", "create_date", "user_id", "stage_id", "active"]
    try:
        try:
            sdb.leads.create_index("phone_digits")
            sdb.leads.create_index("create_date")
        except Exception:
            pass
        lo, hi = f"{date_from} 00:00:00", f"{date_to} 23:59:59"
        window_phones = [p for p in sdb.leads.distinct("phone_digits", {
            "create_date": {"$gte": lo, "$lte": hi}, "phone_digits": {"$nin": [None, ""]}}) if p]
        groups_out, cand_ids = [], []
        for i in range(0, len(window_phones), 400):
            chunk = window_phones[i:i + 400]
            proj = {"_id": 0, "phone_digits": 1, **{f: 1 for f in fields}}
            by_phone = {}
            for l in sdb.leads.find({"phone_digits": {"$in": chunk}}, proj):
                by_phone.setdefault(l.get("phone_digits"), []).append(l)
            for phone, grp in by_phone.items():
                if len(grp) < 2:
                    continue
                keeper = min(grp, key=lambda l: l.get("create_date") or "9999")
                cands = [l for l in grp if l["id"] != keeper["id"]
                         and l.get("create_date") and lo <= l["create_date"] <= hi]
                if not cands:
                    continue
                slim = lambda l: {f: l.get(f) for f in fields}
                groups_out.append({"phone": phone, "keeper": slim(keeper),
                                   "candidates": [slim(c) for c in cands]})
                cand_ids += [c["id"] for c in cands]
        sdb.settings.update_one({"key": "dup_scan"}, {"$set": {
            "key": "dup_scan", "status": "done", "scan_id": scan_id,
            "date_from": date_from, "date_to": date_to,
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


@router.post("/duplicates/scan")
async def dup_scan(body: DupScanBody, user: dict = Depends(require_roles("admin"))):
    scan_id = int(datetime.now(timezone.utc).timestamp())
    await db.settings.update_one({"key": "dup_scan"}, {"$set": {
        "key": "dup_scan", "status": "running", "scan_id": scan_id,
        "date_from": body.date_from, "date_to": body.date_to,
        "started_at": now_utc_str(), "started_by": user["name"]}}, upsert=True)
    threading.Thread(target=_dup_scan_worker, args=(body.date_from, body.date_to, scan_id),
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
