"""Case 11 — multiple file attachments per lead (medical reports etc.) via Emergent object storage."""
import uuid
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Header, Query, Request
from fastapi.responses import Response

from core.db import db
from core.security import get_current_user, get_jwt_secret, JWT_ALGORITHM, ensure_lead_edit
from core.storage import put_object, get_object, APP_NAME
from core.utils import log_message, now_utc_str

router = APIRouter(tags=["attachments"])

MAX_BYTES = 25 * 1024 * 1024
MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
        "webp": "image/webp", "pdf": "application/pdf", "csv": "text/csv", "txt": "text/plain",
        "doc": "application/msword", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xls": "application/vnd.ms-excel", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


@router.get("/leads/{lead_id}/attachments")
async def list_attachments(lead_id: int, user: dict = Depends(get_current_user)):
    items = await db.attachments.find(
        {"lead_id": lead_id, "is_deleted": {"$ne": True}}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    return items


@router.post("/leads/{lead_id}/attachments")
async def upload_attachment(lead_id: int, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0, "id": 1, "user_id": 1})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 25MB)")
    ext = (file.filename.rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "bin")
    ctype = file.content_type or MIME.get(ext, "application/octet-stream")
    path = f"{APP_NAME}/leads/{lead_id}/{uuid.uuid4()}.{ext}"
    try:
        result = await put_object(path, data, ctype)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upload failed: {e}")
    aid = str(uuid.uuid4())
    doc = {
        "id": aid, "lead_id": lead_id, "storage_path": result["path"],
        "original_filename": file.filename, "content_type": ctype,
        "size": result.get("size", len(data)), "is_deleted": False,
        "uploaded_by": user["name"], "uploaded_by_id": user["id"], "created_at": now_utc_str(),
    }
    await db.attachments.insert_one(doc)
    await log_message(lead_id, f"📎 Attachment added: <b>{file.filename}</b> by {user['name']}", author=user, subtype="comment")
    doc.pop("_id", None)
    return doc


def _resolve_user(token: str):
    payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    return payload


@router.get("/attachments/{att_id}/download")
async def download_attachment(att_id: str, request: Request, auth: Optional[str] = Query(None),
                              authorization: Optional[str] = Header(None)):
    token = request.cookies.get("access_token") or auth
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        _resolve_user(token)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    rec = await db.attachments.find_one({"id": att_id, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Attachment not found")
    try:
        content, ctype = await get_object(rec["storage_path"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Download failed: {e}")
    return Response(content=content, media_type=rec.get("content_type") or ctype,
                    headers={"Content-Disposition": f'inline; filename="{rec.get("original_filename", "file")}"'})


@router.delete("/attachments/{att_id}")
async def delete_attachment(att_id: str, user: dict = Depends(get_current_user)):
    rec = await db.attachments.find_one({"id": att_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Attachment not found")
    await db.attachments.update_one({"id": att_id}, {"$set": {"is_deleted": True}})
    await log_message(rec["lead_id"], f"📎 Attachment removed: {rec.get('original_filename')} by {user['name']}", author=user, subtype="comment")
    return {"ok": True}
