from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.db import db
from core.security import hash_password, hash_password_async, require_roles, require_permission, get_current_user
from core.utils import next_id, now_utc_str

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: str = "caller"


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = None
    ozonetel_agent_id: Optional[str] = None
    ozonetel_phone_name: Optional[str] = None


@router.get("")
async def list_users(user: dict = Depends(get_current_user)):
    users = await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("name", 1).to_list(500)
    return users


@router.post("")
async def create_user(body: UserCreate, admin: dict = Depends(require_permission("manage_users"))):
    email = body.email.strip().lower()
    if body.role not in ("admin", "manager", "caller"):
        raise HTTPException(status_code=400, detail="Invalid role")
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already exists")
    uid = await next_id("user")
    doc = {
        "id": uid, "name": body.name, "email": email, "role": body.role,
        "active": True, "password_hash": await hash_password_async(body.password),
        "created_at": now_utc_str(),
    }
    await db.users.insert_one(doc)
    return {"id": uid, "name": body.name, "email": email, "role": body.role, "active": True}


@router.patch("/{user_id}")
async def update_user(user_id: int, body: UserUpdate, admin: dict = Depends(require_permission("manage_users"))):
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.email is not None:
        email = body.email.strip().lower()
        existing = await db.users.find_one({"email": email, "id": {"$ne": user_id}})
        if existing:
            raise HTTPException(status_code=400, detail="Email already exists")
        updates["email"] = email
    if body.role is not None:
        if body.role not in ("admin", "manager", "caller"):
            raise HTTPException(status_code=400, detail="Invalid role")
        updates["role"] = body.role
    if body.active is not None:
        updates["active"] = body.active
    if body.password:
        updates["password_hash"] = await hash_password_async(body.password)
    if body.ozonetel_agent_id is not None:
        updates["ozonetel_agent_id"] = body.ozonetel_agent_id.strip() or None
    if body.ozonetel_phone_name is not None:
        updates["ozonetel_phone_name"] = body.ozonetel_phone_name.strip() or None
    if updates:
        await db.users.update_one({"id": user_id}, {"$set": updates})
    out = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return out


@router.delete("/{user_id}")
async def delete_user(user_id: int, user: dict = Depends(require_permission("manage_users"))):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    target = await db.users.find_one({"id": user_id}, {"_id": 0, "id": 1, "role": 1})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") == "admin":
        admins = await db.users.count_documents({"role": "admin", "active": True})
        if admins <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin")
    assigned = await db.leads.count_documents({"user_id": user_id, "active": True})
    if assigned > 0:
        raise HTTPException(status_code=400,
            detail=f"This user has {assigned} active leads assigned. Reassign them first, or deactivate the user instead.")
    await db.users.delete_one({"id": user_id})
    return {"ok": True}
