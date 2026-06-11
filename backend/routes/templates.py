from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user, require_roles
from core.utils import next_id, now_utc_str

router = APIRouter(prefix="/templates", tags=["templates"])

COLLECTIONS = {"email": "templates_email", "whatsapp": "templates_whatsapp"}


class TemplateBody(BaseModel):
    name: str
    subject: Optional[str] = None
    body: str = ""
    template_type: Optional[str] = None
    status: Optional[str] = None
    lang: Optional[str] = None


@router.get("/{channel}")
async def list_templates(channel: str, user: dict = Depends(get_current_user)):
    if channel not in COLLECTIONS:
        raise HTTPException(status_code=400, detail="Invalid channel")
    return await db[COLLECTIONS[channel]].find({}, {"_id": 0}).sort("name", 1).to_list(500)


@router.post("/{channel}")
async def create_template(channel: str, body: TemplateBody, user: dict = Depends(require_roles("admin", "manager"))):
    if channel not in COLLECTIONS:
        raise HTTPException(status_code=400, detail="Invalid channel")
    tid = await next_id(f"template_{channel}")
    doc = {"id": tid, **{k: v for k, v in body.model_dump().items() if v is not None},
           "active": True, "created_at": now_utc_str()}
    await db[COLLECTIONS[channel]].insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/{channel}/{tid}")
async def update_template(channel: str, tid: int, body: dict, user: dict = Depends(require_roles("admin", "manager"))):
    if channel not in COLLECTIONS:
        raise HTTPException(status_code=400, detail="Invalid channel")
    allowed = {"name", "subject", "body", "template_type", "status", "lang", "active"}
    updates = {k: v for k, v in body.items() if k in allowed}
    res = await db[COLLECTIONS[channel]].update_one({"id": tid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return await db[COLLECTIONS[channel]].find_one({"id": tid}, {"_id": 0})


@router.delete("/{channel}/{tid}")
async def delete_template(channel: str, tid: int, user: dict = Depends(require_roles("admin"))):
    if channel not in COLLECTIONS:
        raise HTTPException(status_code=400, detail="Invalid channel")
    await db[COLLECTIONS[channel]].delete_one({"id": tid})
    return {"ok": True}
