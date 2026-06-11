from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user
from core.utils import next_id

router = APIRouter(prefix="/filters", tags=["filters"])


class FilterCreate(BaseModel):
    name: str
    page: str = "leads"
    params: dict = {}
    group_by: Optional[str] = None
    is_default: bool = False
    shared: bool = False


@router.get("")
async def list_filters(page: str = "leads", user: dict = Depends(get_current_user)):
    q = {"page": page, "$or": [{"user_id": user["id"]}, {"shared": True}]}
    return await db.saved_filters.find(q, {"_id": 0}).sort("name", 1).to_list(200)


@router.post("")
async def create_filter(body: FilterCreate, user: dict = Depends(get_current_user)):
    fid = await next_id("saved_filter")
    if body.is_default:
        await db.saved_filters.update_many({"user_id": user["id"], "page": body.page}, {"$set": {"is_default": False}})
    doc = {"id": fid, "user_id": user["id"], "user_name": user["name"], **body.model_dump()}
    await db.saved_filters.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/{fid}")
async def delete_filter(fid: int, user: dict = Depends(get_current_user)):
    f = await db.saved_filters.find_one({"id": fid})
    if not f:
        raise HTTPException(status_code=404, detail="Not found")
    if f["user_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not allowed")
    await db.saved_filters.delete_one({"id": fid})
    return {"ok": True}
