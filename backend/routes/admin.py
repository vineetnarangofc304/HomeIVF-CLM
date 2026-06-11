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
