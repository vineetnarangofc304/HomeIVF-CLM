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


@router.get("/sync/status")
async def sync_status(user: dict = Depends(require_roles("admin", "manager"))):
    """Reconciliation snapshot: last record per entity, last sync, counts, and the window a new sync would cover."""
    async def max_field(coll, field, match=None):
        agg = await db[coll].aggregate([
            {"$match": match or {}},
            {"$group": {"_id": None, "m": {"$max": f"${field}"}}},
        ]).to_list(1)
        return agg[0]["m"] if agg and agg[0].get("m") else None

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
        counts[coll] = await db[coll].estimated_document_count()
    counts["leads_migrated"] = await db.leads.count_documents({"migrated": True})
    counts["leads_created_in_crm"] = counts["leads"] - counts["leads_migrated"]

    last_sync = await db.settings.find_one({"key": "last_sync"}, {"_id": 0})
    running = await db.sync_runs.find_one({"status": "running"}, {"_id": 0})
    # Self-heal dead runs: a sync executes on an in-process thread. If that thread
    # is no longer alive (crashed, or the backend process was restarted/redeployed
    # mid-sync) the DB doc stays "running" forever and permanently disables the
    # Sync button. Detect it and clear it so the button re-enables immediately.
    if running:
        alive = any(t.name == f"odoo-sync-{running['run_id']}" and t.is_alive()
                    for t in threading.enumerate())
        if not alive:
            await db.sync_runs.update_one({"run_id": running["run_id"]}, {"$set": {
                "status": "error", "error": "sync worker no longer running (process restarted or crashed)",
                "finished_at": now_utc_str()}})
            running = None

    # window a new sync would cover
    if last_sync:
        next_since = last_sync["until"]
    else:
        next_since = last_record["leads_write_date"]
    if next_since:
        try:
            next_since = (datetime.strptime(next_since, "%Y-%m-%d %H:%M:%S") - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return {"last_record": last_record, "counts": counts, "last_sync": last_sync,
            "running": running, "next_since": next_since, "now": now_utc_str(),
            "mode": "delta" if next_since else "full"}


@router.post("/sync/start")
async def sync_start(user: dict = Depends(require_roles("admin"))):
    running = await db.sync_runs.find_one({"status": "running"})
    if running:
        alive = any(t.name == f"odoo-sync-{running['run_id']}" and t.is_alive()
                    for t in threading.enumerate())
        if alive:
            raise HTTPException(status_code=409, detail="A sync is already running")
        # dead run (thread gone) — supersede it so this fresh sync can proceed
        await db.sync_runs.update_one({"run_id": running["run_id"]}, {"$set": {
            "status": "error", "error": "superseded - worker no longer running",
            "finished_at": now_utc_str()}})

    status = await sync_status(user)
    since = status["next_since"] or "1970-01-01 00:00:00"
    until = now_utc_str()
    rid = await next_id("sync_run")
    await db.sync_runs.insert_one({"run_id": rid, "status": "running", "mode": status["mode"],
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
    return {"run_id": rid, "since": since, "until": until, "mode": status["mode"]}


@router.get("/sync/runs/{run_id}")
async def sync_run(run_id: int, user: dict = Depends(require_roles("admin", "manager"))):
    run = await db.sync_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/sync/runs")
async def sync_runs(user: dict = Depends(require_roles("admin", "manager"))):
    return await db.sync_runs.find({}, {"_id": 0}).sort("run_id", -1).limit(10).to_list(10)


@router.post("/migration/audit")
async def migration_audit(user: dict = Depends(require_roles("admin", "manager"))):
    """Live comparison: counts in Odoo vs counts in this CRM, entity by entity."""
    import asyncio
    import os
    import xmlrpc.client

    def odoo_counts():
        try:
            url, dbname = os.environ["ODOO_URL"], os.environ["ODOO_DB"]
            login, pwd = os.environ["ODOO_LOGIN"], os.environ["ODOO_PASSWORD"]
        except KeyError as e:
            raise HTTPException(status_code=503, detail=f"Odoo credentials missing in environment: {e}")
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        uid = common.authenticate(dbname, login, pwd, {})
        if not uid:
            raise HTTPException(status_code=503, detail="Odoo authentication failed")
        models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

        def c(model, domain):
            try:
                return models.execute_kw(dbname, uid, pwd, model, "search_count", [domain])
            except Exception:
                return -1

        return {
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

    odoo = await asyncio.to_thread(odoo_counts)
    crm = {
        "leads": await db.leads.count_documents({"migrated": True}),
        "lead_chatter_messages": await db.messages.count_documents({"migrated": True}),
        "whatsapp_conversations": await db.wa_channels.count_documents({"migrated": True}),
        "whatsapp_messages": await db.wa_messages.count_documents({"migrated": True}),
        "contacts": await db.contacts.count_documents({"migrated": True}),
        "users": await db.users.count_documents({"odoo_user": True}),
        "tags": await db.catalogs.count_documents({"type": "tag"}),
        "pipeline_stages": await db.catalogs.count_documents({"type": "stage"}),
        "lost_reasons": await db.catalogs.count_documents({"type": "lost_reason"}),
        "open_activities": await db.activities.count_documents({"migrated": True}),
        "email_templates": await db.templates_email.count_documents({"migrated": True}),
        "whatsapp_templates": await db.templates_whatsapp.count_documents({"migrated": True}),
        "utm_sources": await db.catalogs.count_documents({"type": "utm_source"}),
        "utm_mediums": await db.catalogs.count_documents({"type": "utm_medium"}),
        "utm_campaigns": await db.catalogs.count_documents({"type": "utm_campaign"}),
    }
    notes = {
        "whatsapp_messages": "Odoo count includes messages in non-WhatsApp internal channels; CRM migrates WhatsApp-channel messages only.",
        "open_activities": "Odoo deletes activities once marked done — only OPEN activities exist to migrate. Completed activity history lives in lead chatter.",
        "lead_chatter_messages": "Odoo count grows live as your team keeps using Odoo; rerun migration script to sync deltas.",
    }
    rows = []
    for k, ov in odoo.items():
        cv = crm.get(k, 0)
        ok = (cv >= ov) if k != "whatsapp_messages" else (cv > 0 and abs(cv - ov) / max(ov, 1) < 0.1)
        rows.append({"entity": k, "odoo": ov, "crm": cv, "match": bool(ok), "note": notes.get(k)})
    result = {"rows": rows, "ran_at": now_utc_str(),
              "all_match": all(r["match"] for r in rows if r["odoo"] >= 0)}
    await db.settings.update_one({"key": "last_audit"}, {"$set": {"key": "last_audit", **result}}, upsert=True)
    return result
