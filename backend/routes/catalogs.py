from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user, require_roles
from core.utils import next_id

router = APIRouter(prefix="/catalogs", tags=["catalogs"])

CATALOG_TYPES = ["tag", "stage", "lost_reason", "lead_stage", "follow_up_tag",
                 "utm_source", "utm_medium", "utm_campaign", "activity_type", "source_lead"]


@router.get("")
async def get_catalogs(user: dict = Depends(get_current_user)):
    items = await db.catalogs.find({}, {"_id": 0}).sort([("type", 1), ("sequence", 1), ("name", 1)]).to_list(2000)
    out = {t: [] for t in CATALOG_TYPES}
    for i in items:
        out.setdefault(i["type"], []).append(i)
    users = await db.users.find({}, {"_id": 0, "id": 1, "name": 1, "role": 1, "active": 1}).sort("name", 1).to_list(500)
    out["users"] = users
    return out


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
async def create_catalog(ctype: str, body: CatalogCreate, user: dict = Depends(require_roles("admin", "manager"))):
    if ctype not in CATALOG_TYPES:
        raise HTTPException(status_code=400, detail="Invalid catalog type")
    if await db.catalogs.find_one({"type": ctype, "name": body.name}):
        raise HTTPException(status_code=400, detail="Already exists")
    cid = await next_id(f"catalog_{ctype}")
    doc = {"id": cid, "type": ctype, "name": body.name, "active": True}
    if body.color is not None:
        doc["color"] = body.color
    if body.sequence is not None:
        doc["sequence"] = body.sequence
    if body.is_won is not None:
        doc["is_won"] = body.is_won
    await db.catalogs.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/{ctype}/{cid}")
async def update_catalog(ctype: str, cid: int, body: CatalogUpdate, user: dict = Depends(require_roles("admin", "manager"))):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    res = await db.catalogs.update_one({"type": ctype, "id": cid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return await db.catalogs.find_one({"type": ctype, "id": cid}, {"_id": 0})


@router.delete("/{ctype}/{cid}")
async def delete_catalog(ctype: str, cid: int, user: dict = Depends(require_roles("admin"))):
    res = await db.catalogs.update_one({"type": ctype, "id": cid}, {"$set": {"active": False}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}
