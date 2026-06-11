from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import require_roles
from core.utils import next_id, now_utc_str

router = APIRouter(prefix="/admin", tags=["admin"])


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


@router.get("/outbound_queue")
async def outbound_queue(user: dict = Depends(require_roles("admin", "manager"))):
    items = await db.outbound_queue.find({}, {"_id": 0}).sort("created_at", -1).limit(200).to_list(200)
    return items


@router.post("/migration/audit")
async def migration_audit(user: dict = Depends(require_roles("admin", "manager"))):
    """Live comparison: counts in Odoo vs counts in this CRM, entity by entity."""
    import asyncio
    import os
    import xmlrpc.client

    def odoo_counts():
        url, dbname = os.environ["ODOO_URL"], os.environ["ODOO_DB"]
        login, pwd = os.environ["ODOO_LOGIN"], os.environ["ODOO_PASSWORD"]
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        uid = common.authenticate(dbname, login, pwd, {})
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
