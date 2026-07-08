import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user, require_roles
from core.utils import next_id

router = APIRouter(prefix="/catalogs", tags=["catalogs"])

CATALOG_TYPES = ["tag", "stage", "lost_reason", "lead_stage", "follow_up_tag",
                 "utm_source", "utm_medium", "utm_campaign", "activity_type", "source_lead",
                 "state", "country", "followup_status"]


@router.get("")
async def get_catalogs(user: dict = Depends(get_current_user)):
    items = await db.catalogs.find({}, {"_id": 0}).sort([("type", 1), ("sequence", 1), ("name", 1)]).to_list(3000)
    out = {t: [] for t in CATALOG_TYPES}
    for i in items:
        out.setdefault(i["type"], []).append(i)
    users = await db.users.find({}, {"_id": 0, "id": 1, "name": 1, "role": 1, "active": 1}).sort("name", 1).to_list(500)
    out["users"] = users
    labels = await db.settings.find_one({"key": "lead_field_labels"}, {"_id": 0})
    out["field_labels"] = (labels or {}).get("fields", {})
    out["custom_fields"] = await db.custom_fields.find({}, {"_id": 0}).sort([("sequence", 1), ("id", 1)]).to_list(300)
    return out


# ---------------- Custom Fields (Case 4: self-service field builder) ----------------
# IMPORTANT: These specific routes MUST be declared BEFORE the generic /{ctype}/{cid}
# routes below, otherwise FastAPI's routing matches /catalogs/custom-fields/{id} against
# /{ctype}/{cid} with ctype="custom-fields" → 404 because it is not a valid catalog type.

class CustomFieldCreate(BaseModel):
    label: str
    field_type: str = "char"  # char|text|integer|float|monetary|date|datetime|boolean|selection
    options: list = []
    section: str = "qa"  # qa | general
    aliases: list = []


VALID_FIELD_TYPES = {"char", "text", "integer", "float", "monetary", "date", "datetime", "boolean", "selection"}


@router.get("/custom-fields/all")
async def list_custom_fields(user: dict = Depends(get_current_user)):
    return await db.custom_fields.find({}, {"_id": 0}).sort([("sequence", 1), ("id", 1)]).to_list(300)


# Standard lead fields exposed for template mapping (Phone Field / Variables Field dropdowns)
STANDARD_LEAD_FIELDS = [
    ("contact_name", "Name"), ("phone", "Phone"), ("mobile", "Mobile"),
    ("email_from", "Email"), ("city", "City"), ("state_name", "State"),
    ("country", "Country"), ("street", "Address"), ("gender", "Gender"),
    ("age", "Age"), ("spouse_name", "Spouse Name"), ("doctor_name", "Doctor"),
    ("source_lead", "Source"), ("campaign_name", "Campaign"), ("follow_up_date", "Follow-up Date"),
]


@router.get("/lead-field-options")
async def lead_field_options(user: dict = Depends(get_current_user)):
    """All mappable CRM lead fields (standard + custom) for WhatsApp template dropdowns."""
    opts = [{"key": k, "label": lbl, "group": "Standard"} for k, lbl in STANDARD_LEAD_FIELDS]
    cf = await db.custom_fields.find({"active": {"$ne": False}}, {"_id": 0, "key": 1, "label": 1}).sort([("sequence", 1), ("id", 1)]).to_list(300)
    for f in cf:
        if f.get("key"):
            opts.append({"key": f["key"], "label": f.get("label") or f["key"], "group": "Custom"})
    return {"options": opts}


@router.post("/custom-fields/create")
async def create_custom_field(body: CustomFieldCreate, user: dict = Depends(require_roles("admin", "manager"))):
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="Label required")
    if body.field_type not in VALID_FIELD_TYPES:
        raise HTTPException(status_code=400, detail="Invalid field type")
    if body.section not in ("qa", "general"):
        raise HTTPException(status_code=400, detail="Invalid section")
    key = "x_custom_" + re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:50]
    if await db.custom_fields.find_one({"key": key}):
        raise HTTPException(status_code=400, detail="A field with this label already exists")
    fid = await next_id("custom_field")
    last = await db.custom_fields.find_one({}, sort=[("sequence", -1)])
    seq = (last.get("sequence", 0) if last else 0) + 1
    doc = {"id": fid, "key": key, "label": label, "field_type": body.field_type,
           "options": [str(o).strip() for o in body.options if str(o).strip()],
           "section": body.section, "sequence": seq,
           "aliases": [str(a).strip() for a in body.aliases if str(a).strip()],
           "active": True}
    await db.custom_fields.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/custom-fields/reorder")
async def reorder_custom_fields(body: dict, user: dict = Depends(require_roles("admin", "manager"))):
    """body: {order: [field_id, ...]} — sets sequence per the given order."""
    order = body.get("order") or []
    for i, fid in enumerate(order):
        await db.custom_fields.update_one({"id": int(fid)}, {"$set": {"sequence": i + 1}})
    return {"ok": True}


@router.patch("/custom-fields/{fid}")
async def update_custom_field(fid: int, body: dict, user: dict = Depends(require_roles("admin", "manager"))):
    allowed = {"label", "field_type", "options", "section", "aliases", "active", "sequence"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if "field_type" in updates and updates["field_type"] not in VALID_FIELD_TYPES:
        raise HTTPException(status_code=400, detail="Invalid field type")
    res = await db.custom_fields.update_one({"id": fid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return await db.custom_fields.find_one({"id": fid}, {"_id": 0})


@router.delete("/custom-fields/{fid}")
async def delete_custom_field(fid: int, hard: bool = False, user: dict = Depends(require_roles("admin"))):
    if hard:
        await db.custom_fields.delete_one({"id": fid})
    else:
        await db.custom_fields.update_one({"id": fid}, {"$set": {"active": False}})
    return {"ok": True}


# ---------------- Generic catalog CRUD ----------------

class CatalogCreate(BaseModel):
    name: str
    color: Optional[int] = None
    sequence: Optional[int] = None
    is_won: Optional[bool] = None


class CatalogUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[int] = None
    sequence: Optional[int] = None
    is_won: Optional[bool] = None
    active: Optional[bool] = None


@router.post("/{ctype}")
async def create_catalog(ctype: str, body: CatalogCreate, user: dict = Depends(get_current_user)):
    if ctype not in CATALOG_TYPES:
        raise HTTPException(status_code=400, detail="Invalid catalog type")
    # disposition tags can be created by any user (matches Odoo); other types need manager/admin
    if ctype != "tag" and user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    existing = await db.catalogs.find_one({"type": ctype, "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}})
    if existing:
        if existing.get("active") is False:
            await db.catalogs.update_one({"type": ctype, "id": existing["id"]}, {"$set": {"active": True}})
            existing["active"] = True
        existing.pop("_id", None)
        return existing
    cid = await next_id(f"catalog_{ctype}")
    doc = {"id": cid, "type": ctype, "name": name, "active": True}
    if body.color is not None:
        doc["color"] = body.color
    if body.sequence is not None:
        doc["sequence"] = body.sequence
    if body.is_won is not None:
        doc["is_won"] = body.is_won
    # migrated catalogs bypassed the counter, so next_id can collide with existing ids —
    # retry with max-id+1 until the insert succeeds.
    for _ in range(6):
        try:
            await db.catalogs.insert_one(doc)
            doc.pop("_id", None)
            return doc
        except Exception:
            last = await db.catalogs.find_one({"type": ctype}, sort=[("id", -1)])
            doc["id"] = (last.get("id", 0) if last else 0) + 1
            doc.pop("_id", None)
    raise HTTPException(status_code=500, detail="Could not create catalog item")


@router.patch("/{ctype}/{cid}")
async def update_catalog(ctype: str, cid: int, body: CatalogUpdate, user: dict = Depends(require_roles("admin", "manager"))):
    if ctype not in CATALOG_TYPES:
        raise HTTPException(status_code=400, detail="Invalid catalog type")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    res = await db.catalogs.update_one({"type": ctype, "id": cid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return await db.catalogs.find_one({"type": ctype, "id": cid}, {"_id": 0})


@router.delete("/{ctype}/{cid}")
async def delete_catalog(ctype: str, cid: int, user: dict = Depends(require_roles("admin"))):
    if ctype not in CATALOG_TYPES:
        raise HTTPException(status_code=400, detail="Invalid catalog type")
    res = await db.catalogs.update_one({"type": ctype, "id": cid}, {"$set": {"active": False}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}
