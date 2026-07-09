import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

IST = timezone(timedelta(hours=5, minutes=30))
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user, require_roles
from core.utils import log_message, next_id, now_utc_str, run_automations, to_ist_str, today_ist, check_duplicate, record_wa_outbound
from core import whatsapp_cloud as wac

router = APIRouter(prefix="/leads", tags=["leads"])

LIST_PROJECTION = {
    "_id": 0, "id": 1, "name": 1, "contact_name": 1, "phone": 1, "email_from": 1,
    "city": 1, "state_name": 1, "lead_stage": 1, "stage_id": 1, "tags": 1, "user_id": 1,
    "create_date": 1, "create_date_ist": 1, "follow_up_date": 1, "follow_up_time": 1, "follow_up_tag": 1,
    "source_lead": 1, "campaign_name": 1, "ads_platform": 1, "priority": 1, "active": 1,
    "probability": 1, "appointment_date": 1, "lost_reason_id": 1, "is_duplicate": 1, "duplicate_of": 1,
    "ozonetel_lead": 1, "in_pipeline": 1,
}

EDITABLE_FIELDS = {
    "name", "contact_name", "phone", "mobile", "email_from", "city", "state_name",
    "country", "street",
    "stage_id", "lead_stage", "tags", "user_id", "follow_up_date", "follow_up_time", "follow_up_tag",
    "appointment_date", "appointment_time", "source_lead", "campaign_name", "ads_platform", "ads_campaign_name",
    "ads_name", "description", "priority", "gender", "age", "male_age", "female_age",
    "spouse_name", "spouse_age", "spouse_alternate_no", "query", "remark", "pre_conditions",
    "doctor_name", "lost_reason_id", "custom",
    "source_id", "medium_id", "campaign_id",
}

TRACKED = ["stage_id", "lead_stage", "user_id", "tags", "follow_up_date", "follow_up_tag", "lost_reason_id"]


def build_query(
    search=None, stage_id=None, lead_stage=None, tags=None, user_id=None,
    source_lead=None, campaign_name=None, ads_platform=None, city=None, state_name=None,
    active="true", date_from=None, date_to=None, follow_up=None, priority=None,
    follow_up_tag=None, lost_reason_id=None, bucket=None,
    current_user=None,
):
    q = {}
    if bucket == "ozonetel":
        q["ozonetel_lead"] = True
        q["in_pipeline"] = {"$ne": True}
    elif bucket == "pipeline":
        q["$and"] = [{"$or": [{"ozonetel_lead": {"$ne": True}}, {"in_pipeline": True}]}]
    if active == "true":
        q["active"] = True
    elif active == "false":
        q["active"] = False
    if search:
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        digits = re.sub(r"\D", "", search)
        ors = [{"name": rx}, {"contact_name": rx}, {"email_from": rx}]
        if digits and len(digits) >= 4:
            ors.append({"phone_digits": {"$regex": digits}})
        else:
            ors.append({"phone": rx})
        q["$or"] = ors
    if stage_id:
        q["stage_id"] = int(stage_id)
    if lead_stage == "__none__":
        q["lead_stage"] = {"$in": [None, False, ""]}
    elif lead_stage:
        q["lead_stage"] = {"$in": lead_stage.split(",")} if "," in lead_stage else lead_stage
    if tags:
        q["tags"] = {"$in": [int(t) for t in tags.split(",") if t]}
    if user_id == "none":
        q["user_id"] = {"$in": [None, False]}
    elif user_id:
        q["user_id"] = int(user_id)
    if source_lead:
        q["source_lead"] = source_lead
    if follow_up_tag:
        q["follow_up_tag"] = follow_up_tag
    if lost_reason_id:
        q["lost_reason_id"] = int(lost_reason_id)
    if campaign_name:
        q["campaign_name"] = {"$regex": re.escape(campaign_name), "$options": "i"}
    if ads_platform:
        q["ads_platform"] = {"$regex": re.escape(ads_platform), "$options": "i"}
    if city:
        q["city"] = {"$regex": re.escape(city), "$options": "i"}
    if state_name:
        q["state_name"] = {"$regex": re.escape(state_name), "$options": "i"}
    if priority:
        q["priority"] = priority
    if date_from:
        q.setdefault("create_date_ist", {})["$gte"] = date_from
    if date_to:
        q.setdefault("create_date_ist", {})["$lte"] = date_to + " 23:59:59"
    today = today_ist()
    if follow_up == "today":
        q["follow_up_date"] = today
    elif follow_up == "overdue":
        q["follow_up_date"] = {"$lt": today, "$gt": ""}
    elif follow_up == "upcoming":
        q["follow_up_date"] = {"$gt": today}
    elif follow_up == "set":
        q["follow_up_date"] = {"$gt": ""}
    # callers only see their own leads
    if current_user and current_user.get("role") == "caller":
        q["user_id"] = current_user["id"]
    return q


def query_params_dep(
    search: Optional[str] = None, stage_id: Optional[str] = None,
    lead_stage: Optional[str] = None, tags: Optional[str] = None,
    user_id: Optional[str] = None, source_lead: Optional[str] = None,
    campaign_name: Optional[str] = None, ads_platform: Optional[str] = None,
    city: Optional[str] = None, state_name: Optional[str] = None,
    active: str = "true", date_from: Optional[str] = None, date_to: Optional[str] = None,
    follow_up: Optional[str] = None, priority: Optional[str] = None,
    follow_up_tag: Optional[str] = None, lost_reason_id: Optional[str] = None,
    bucket: Optional[str] = None,
):
    return dict(
        search=search, stage_id=stage_id, lead_stage=lead_stage, tags=tags, user_id=user_id,
        source_lead=source_lead, campaign_name=campaign_name, ads_platform=ads_platform,
        city=city, state_name=state_name, active=active, date_from=date_from, date_to=date_to,
        follow_up=follow_up, priority=priority, follow_up_tag=follow_up_tag, lost_reason_id=lost_reason_id,
        bucket=bucket,
    )


ALLOWED_SORT = {"create_date", "create_date_ist", "contact_name", "name", "phone", "city",
                "user_id", "lead_stage", "follow_up_date", "source_lead", "id", "write_date"}


@router.get("")
async def list_leads(
    params: dict = Depends(query_params_dep),
    page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
    sort: str = "create_date", order: str = "desc",
    user: dict = Depends(get_current_user),
):
    q = build_query(**params, current_user=user)
    if sort not in ALLOWED_SORT:
        sort = "create_date"
    sort_dir = -1 if order == "desc" else 1
    total, items = await asyncio.gather(
        db.leads.count_documents(q),
        db.leads.find(q, LIST_PROJECTION).sort([(sort, sort_dir), ("id", -1)])
        .skip((page - 1) * limit).limit(limit).to_list(limit),
    )
    return {"items": items, "total": total, "page": page, "limit": limit}


GROUP_FIELDS = {
    "user_id": "$user_id", "lead_stage": "$lead_stage", "stage_id": "$stage_id",
    "source_lead": "$source_lead", "follow_up_tag": "$follow_up_tag",
    "ads_platform": "$ads_platform", "campaign_name": "$campaign_name",
    "city": "$city", "state_name": "$state_name", "priority": "$priority",
    "lost_reason_id": "$lost_reason_id",
    "create_date:day": {"$substrCP": ["$create_date_ist", 0, 10]},
    "create_date:month": {"$substrCP": ["$create_date_ist", 0, 7]},
}


@router.get("/group_counts")
async def group_counts(
    group_by: str = "lead_stage",
    params: dict = Depends(query_params_dep),
    user: dict = Depends(get_current_user),
):
    q = build_query(**params, current_user=user)
    pipeline = [{"$match": q}]
    if group_by == "tags":
        pipeline += [{"$unwind": {"path": "$tags", "preserveNullAndEmptyArrays": True}},
                     {"$group": {"_id": "$tags", "count": {"$sum": 1}}}]
    elif group_by in GROUP_FIELDS:
        pipeline += [{"$group": {"_id": GROUP_FIELDS[group_by], "count": {"$sum": 1}}}]
    else:
        raise HTTPException(status_code=400, detail="Unsupported group_by")
    pipeline += [{"$sort": {"count": -1}}, {"$limit": 200}]
    rows = await db.leads.aggregate(pipeline).to_list(200)
    return [{"key": r["_id"], "count": r["count"]} for r in rows]


@router.get("/{lead_id}")
async def get_lead(lead_id: int, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


class LeadCreate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email_from: Optional[str] = None
    city: Optional[str] = None
    state_name: Optional[str] = None
    user_id: Optional[int] = None
    lead_stage: Optional[str] = None
    tags: Optional[list] = None
    source_lead: Optional[str] = None
    description: Optional[str] = None
    follow_up_date: Optional[str] = None
    follow_up_time: Optional[str] = None
    follow_up_tag: Optional[str] = None
    gender: Optional[str] = None
    male_age: Optional[str] = None
    female_age: Optional[str] = None
    query: Optional[str] = None
    country: Optional[str] = None


@router.post("")
async def create_lead(body: LeadCreate, user: dict = Depends(get_current_user)):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    data.setdefault("country", "India")  # Case 3 — default market
    if not data.get("name"):
        data["name"] = data.get("contact_name") or data.get("phone") or "New Lead"
    lid = await next_id("lead")
    now = now_utc_str()
    phone_digits = re.sub(r"\D", "", data.get("phone") or "")[-10:]
    dup = await check_duplicate(phone_digits)
    doc = {
        "id": lid, "active": True, "stage_id": 1, "type": "lead", "priority": "0",
        "tags": data.pop("tags", []), "create_date": now, "create_date_ist": to_ist_str(now),
        "write_date": now, "create_uid": user["id"], "custom": {},
        "phone_digits": phone_digits,
        "is_duplicate": dup["is_duplicate"], "duplicate_of": dup["duplicate_of"],
        **data,
    }
    await db.leads.insert_one(doc)
    await log_message(lid, f"Lead created by {user['name']}", author=user)
    if dup["is_duplicate"]:
        await log_message(lid, f"⚠️ Possible duplicate — same phone as lead #{dup['duplicate_of']}", author=user, subtype="comment")
    await run_automations("on_create", doc)
    doc.pop("_id", None)
    return doc


class LeadUpdate(BaseModel):
    updates: dict


async def _track_changes(lead, updates, user):
    parts = []
    for f in TRACKED:
        if f in updates and updates[f] != lead.get(f):
            old, new = lead.get(f), updates[f]
            if f == "tags":
                old_set, new_set = set(old or []), set(new or [])
                added, removed = new_set - old_set, old_set - new_set
                names = {t["id"]: t["name"] for t in await db.catalogs.find({"type": "tag"}, {"_id": 0}).to_list(500)}
                if added:
                    parts.append("Tags added: " + ", ".join(names.get(t, str(t)) for t in added))
                if removed:
                    parts.append("Tags removed: " + ", ".join(names.get(t, str(t)) for t in removed))
            elif f == "user_id":
                users = {u["id"]: u["name"] for u in await db.users.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)}
                parts.append(f"Assigned: {users.get(old, old or 'None')} → {users.get(new, new or 'None')}")
            elif f == "stage_id":
                stages = {s["id"]: s["name"] for s in await db.catalogs.find({"type": "stage"}, {"_id": 0}).to_list(50)}
                parts.append(f"Pipeline stage: {stages.get(old, old or 'None')} → {stages.get(new, new or 'None')}")
            else:
                parts.append(f"{f.replace('_', ' ').title()}: {old or 'None'} → {new or 'None'}")
    if parts:
        await log_message(lead["id"], "<br/>".join(parts), author=user)


@router.patch("/{lead_id}")
async def update_lead(lead_id: int, body: LeadUpdate, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    updates = {k: v for k, v in body.updates.items() if k in EDITABLE_FIELDS}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    if "custom" in updates and isinstance(updates["custom"], dict):
        merged = dict(lead.get("custom") or {})
        merged.update(updates["custom"])
        updates["custom"] = merged
    if "phone" in updates:
        updates["phone_digits"] = re.sub(r"\D", "", updates.get("phone") or "")[-10:]
    await _track_changes(lead, updates, user)
    updates["write_date"] = now_utc_str()
    updates["write_uid"] = user["id"]
    await db.leads.update_one({"id": lead_id}, {"$set": updates})
    new_lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
    stage_changed = ("stage_id" in updates and updates["stage_id"] != lead.get("stage_id")) or \
                    ("lead_stage" in updates and updates["lead_stage"] != lead.get("lead_stage"))
    if stage_changed:
        await run_automations("on_stage_set", new_lead)
    if "tags" in updates:
        added = list(set(updates["tags"] or []) - set(lead.get("tags") or []))
        if added:
            await run_automations("on_tag_set", new_lead, {"added_tags": added})
    return new_lead


class LostBody(BaseModel):
    lost_reason_id: Optional[int] = None
    note: Optional[str] = None


@router.post("/{lead_id}/lost")
async def mark_lost(lead_id: int, body: LostBody, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    await db.leads.update_one({"id": lead_id}, {"$set": {
        "active": False, "lost_reason_id": body.lost_reason_id,
        "date_closed": now_utc_str(), "probability": 0,
    }})
    reason = ""
    if body.lost_reason_id:
        r = await db.catalogs.find_one({"type": "lost_reason", "id": body.lost_reason_id})
        reason = f" — Reason: {r['name']}" if r else ""
    await log_message(lead_id, f"Lead marked as Lost{reason}{('<br/>' + body.note) if body.note else ''}", author=user)
    return {"ok": True}


@router.post("/{lead_id}/restore")
async def restore_lead(lead_id: int, user: dict = Depends(get_current_user)):
    await db.leads.update_one({"id": lead_id}, {"$set": {"active": True, "lost_reason_id": None}})
    await log_message(lead_id, "Lead restored", author=user)
    return {"ok": True}


class PromoteBody(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    email_from: Optional[str] = None
    city: Optional[str] = None
    state_name: Optional[str] = None
    phone: Optional[str] = None


@router.post("/{lead_id}/promote-to-pipeline")
async def promote_to_pipeline(lead_id: int, body: PromoteBody, user: dict = Depends(get_current_user)):
    """Case 2 — validate a raw Ozonetel lead and move it into 'Lead in Pipeline'.
    Dedup: if a pipeline lead already exists with the verified phone, merge this
    lead's call activity into it instead of creating a duplicate."""
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    phone = (body.phone or lead.get("phone") or "").strip()
    pdig = re.sub(r"\D", "", phone)[-10:]
    name = body.contact_name or body.name or lead.get("contact_name") or lead.get("name")

    # Dedup — existing pipeline lead with same verified phone (not this raw one)
    existing = None
    if pdig and len(pdig) >= 8:
        existing = await db.leads.find_one({
            "phone_digits": pdig, "id": {"$ne": lead_id},
            "$or": [{"ozonetel_lead": {"$ne": True}}, {"in_pipeline": True}],
        }, {"_id": 0, "id": 1, "name": 1, "contact_name": 1}, sort=[("id", 1)])

    if existing:
        # map this lead's call activity to the existing pipeline record, archive the raw one
        await db.call_events.update_many({"lead_id": lead_id}, {"$set": {"lead_id": existing["id"]}})
        await db.leads.update_one({"id": lead_id}, {"$set": {"active": False, "merged_into": existing["id"], "is_duplicate": True, "duplicate_of": existing["id"], "write_date": now_utc_str()}})
        await log_message(existing["id"], f"📞 Ozonetel call activity from #{lead_id} merged here (duplicate phone) by {user['name']}", author=user, subtype="comment")
        await log_message(lead_id, f"Merged into pipeline lead #{existing['id']} (duplicate phone)", author=user)
        return {"ok": True, "merged_into": existing["id"]}

    updates = {"in_pipeline": True, "write_date": now_utc_str(), "write_uid": user["id"]}
    if name:
        updates["contact_name"] = name
        updates["name"] = name
    for f in ("email_from", "city", "state_name"):
        v = getattr(body, f)
        if v:
            updates[f] = v.strip()
    if phone:
        updates["phone"] = phone
        updates["phone_digits"] = pdig
    if not lead.get("user_id"):
        updates["user_id"] = user["id"]
    await db.leads.update_one({"id": lead_id}, {"$set": updates})
    await log_message(lead_id, f"✅ Moved to <b>Lead in Pipeline</b> (verified) by {user['name']}", author=user, subtype="comment")
    return {"ok": True, "lead_id": lead_id, "in_pipeline": True}


class SendWhatsAppBody(BaseModel):
    template_id: int
    phone: Optional[str] = None


@router.post("/{lead_id}/send_whatsapp")
async def send_whatsapp(lead_id: int, body: SendWhatsAppBody, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    template = await db.templates_whatsapp.find_one({"id": body.template_id}, {"_id": 0})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    phone = body.phone or lead.get("phone") or lead.get("mobile")
    if not phone:
        raise HTTPException(status_code=400, detail="Lead has no phone number")
    preview = (template.get("body") or "").replace("{{1}}", lead.get("contact_name") or lead.get("name") or "")
    # Live send via WhatsApp Cloud API when configured, else queue until connected.
    live = await wac.is_configured()
    send_status = "pending_api_credentials"
    send_note = "sends automatically once WhatsApp API is connected"
    wamid = None
    if live:
        res = await wac.send_lead_template(lead, template)
        if res.get("ok"):
            send_status, wamid = "sent", res.get("wamid")
            send_note = "delivered via WhatsApp Cloud API"
        else:
            send_status = "failed"
            send_note = f"WhatsApp send failed: {res.get('error')}"
    await db.outbound_queue.insert_one({
        "channel": "whatsapp", "lead_id": lead_id, "template_id": template["id"],
        "template_name": template["name"], "phone": phone, "body": preview,
        "status": send_status, "requested_by": user["name"], "wamid": wamid,
        "created_at": now_utc_str(),
    })
    # Case 5 — track this outbound message for full lifecycle (sent→delivered→read…)
    track_status = {"sent": "sent", "failed": "failed"}.get(send_status, "in_queue")
    track = await record_wa_outbound(
        lead_id=lead_id, template_id=template["id"], template_name=template["name"],
        sent_to=phone, body=preview, created_by=user["name"], status=track_status,
        wamid=wamid, source="manual", error=(send_note if send_status == "failed" else None))
    # mirror into the lead's WhatsApp thread if one exists
    digits = re.sub(r"\D", "", phone)[-10:]
    if len(digits) >= 8:
        ch = await db.wa_channels.find_one({"phone_digits": {"$regex": digits + "$"}})
        if ch:
            mid = await next_id("wa_message")
            await db.wa_messages.insert_one({
                "id": mid, "channel_id": ch["id"], "body": preview, "author_name": user["name"],
                "date": now_utc_str(), "message_type": "comment", "direction": "outbound",
                "status": send_status, "wamid": wamid,
            })
    await log_message(
        lead_id,
        f"WhatsApp template <b>{template['name']}</b> to {phone} by {user['name']} ({send_note})",
        author=user,
        extra={"kind": "wa_template", "channel": "whatsapp", "preview": preview,
               "template_name": template["name"], "track_id": track["id"], "status": track_status},
    )
    if live and send_status == "failed":
        raise HTTPException(status_code=400, detail=send_note)
    return {"ok": True, "status": send_status, "phone": phone, "template": template["name"]}


class SendEmailBody(BaseModel):
    to: Optional[str] = None
    subject: str
    body: str
    save_as_template: Optional[str] = None


@router.post("/{lead_id}/send_email")
async def send_email(lead_id: int, body: SendEmailBody, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    to = (body.to or lead.get("email_from") or "").strip()
    if not to:
        raise HTTPException(status_code=400, detail="Lead has no email address — enter one")
    from core import gmail_send as gm
    sent_live = False
    send_err = None
    if await gm.is_connected():
        res = await gm.send_email(to, body.subject, body.body, html=True)
        sent_live = res.get("ok", False)
        send_err = res.get("error")
    await db.outbound_queue.insert_one({
        "channel": "email", "lead_id": lead_id, "to": to, "subject": body.subject,
        "body": body.body, "status": "sent" if sent_live else "pending_api_credentials",
        "error": send_err, "requested_by": user["name"], "created_at": now_utc_str(),
    })
    if body.save_as_template:
        tid = await next_id("template_email")
        await db.templates_email.insert_one({
            "id": tid, "name": body.save_as_template, "subject": body.subject,
            "body": body.body, "active": True, "created_at": now_utc_str(),
        })
    note = (f"📧 Email sent to <b>{to}</b> by {user['name']}" if sent_live
            else f"Email queued to <b>{to}</b> by {user['name']} (sends automatically once Gmail is connected)")
    await log_message(
        lead_id,
        f"{note}<br/><b>Subject:</b> {body.subject}",
        author=user, subtype="comment",
        extra={"kind": "email_template", "channel": "email", "preview": body.body,
               "template_name": body.subject, "subject": body.subject,
               "status": "sent" if sent_live else "in_queue"},
    )
    return {"ok": True, "status": "queued", "to": to}


class BulkBody(BaseModel):
    ids: list
    action: str
    payload: dict = {}


@router.post("/bulk")
async def bulk_action(body: BulkBody, user: dict = Depends(require_roles("admin", "manager"))):
    ids = [int(i) for i in body.ids]
    q = {"id": {"$in": ids}}
    p = body.payload
    if body.action == "assign":
        await db.leads.update_many(q, {"$set": {"user_id": int(p["user_id"])}})
    elif body.action == "add_tags":
        await db.leads.update_many(q, {"$addToSet": {"tags": {"$each": [int(t) for t in p["tags"]]}}})
    elif body.action == "remove_tags":
        await db.leads.update_many(q, {"$pull": {"tags": {"$in": [int(t) for t in p["tags"]]}}})
    elif body.action == "set_stage":
        await db.leads.update_many(q, {"$set": {"stage_id": int(p["stage_id"])}})
    elif body.action == "set_lead_stage":
        await db.leads.update_many(q, {"$set": {"lead_stage": p["lead_stage"]}})
    elif body.action == "archive":
        await db.leads.update_many(q, {"$set": {"active": False}})
    elif body.action == "restore":
        await db.leads.update_many(q, {"$set": {"active": True}})
    elif body.action == "set_follow_up":
        await db.leads.update_many(q, {"$set": {"follow_up_date": p.get("follow_up_date"), "follow_up_tag": p.get("follow_up_tag")}})
    else:
        raise HTTPException(status_code=400, detail="Unknown action")
    # Case 8: bulk tag/stage updates also fire automation triggers
    if body.action in ("add_tags", "set_stage", "set_lead_stage"):
        async for l in db.leads.find(q, {"_id": 0}):
            if body.action == "add_tags":
                await run_automations("on_tag_set", l, {"added_tags": [int(t) for t in p["tags"]]})
            else:
                await run_automations("on_stage_set", l)
    return {"ok": True, "count": len(ids)}


# ---------- Case 2: Follow-up entries (history with edit/delete) ----------
async def _sync_lead_followup(lead_id: int):
    """Keep the lead's follow_up_* fields pointed at the latest scheduled entry."""
    latest = await db.follow_ups.find(
        {"lead_id": lead_id, "follow_up_date": {"$gt": ""}}, {"_id": 0}
    ).sort("follow_up_date", -1).limit(1).to_list(1)
    if latest:
        f = latest[0]
        await db.leads.update_one({"id": lead_id}, {"$set": {
            "follow_up_date": f.get("follow_up_date"), "follow_up_time": f.get("follow_up_time"),
            "follow_up_tag": f.get("follow_up_tag")}})
    else:
        await db.leads.update_one({"id": lead_id}, {"$set": {
            "follow_up_date": None, "follow_up_time": None, "follow_up_tag": None}})


class FollowUpBody(BaseModel):
    follow_up_date: Optional[str] = None
    follow_up_time: Optional[str] = None
    follow_up_tag: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = None


@router.get("/{lead_id}/followups")
async def list_followups(lead_id: int, user: dict = Depends(get_current_user)):
    return await db.follow_ups.find({"lead_id": lead_id}, {"_id": 0}).sort([("follow_up_date", -1), ("id", -1)]).to_list(200)


@router.post("/{lead_id}/followups")
async def add_followup(lead_id: int, body: FollowUpBody, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    note = (body.note or "").strip()
    if not note:  # Case 1 — note is mandatory for every follow-up
        raise HTTPException(status_code=400, detail="A note is required for every follow-up")
    fid = await next_id("follow_up")
    doc = {"id": fid, "lead_id": lead_id, "follow_up_date": body.follow_up_date or None,
           "follow_up_time": body.follow_up_time or None, "follow_up_tag": body.follow_up_tag or None,
           "note": note, "status": body.status or None, "created_by": user["id"],
           "created_by_name": user["name"], "created_at": now_utc_str()}
    await db.follow_ups.insert_one(doc)
    await _sync_lead_followup(lead_id)
    tag = f" · {doc['follow_up_tag']}" if doc.get("follow_up_tag") else ""
    when = doc.get("follow_up_date") or "no date"
    await log_message(lead_id, f"Follow-up scheduled for <b>{when}</b>{tag}<br/>{note}", author=user)
    doc.pop("_id", None)
    return doc


@router.patch("/{lead_id}/followups/{fid}")
async def update_followup(lead_id: int, fid: int, body: FollowUpBody, user: dict = Depends(get_current_user)):
    fu = await db.follow_ups.find_one({"id": fid, "lead_id": lead_id})
    if not fu:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="A note is required for every follow-up")
    updates = {"follow_up_date": body.follow_up_date or None, "follow_up_time": body.follow_up_time or None,
               "follow_up_tag": body.follow_up_tag or None, "note": note, "status": body.status or None}
    await db.follow_ups.update_one({"id": fid}, {"$set": updates})
    await _sync_lead_followup(lead_id)
    await log_message(lead_id, f"Follow-up updated → <b>{updates['follow_up_date'] or 'no date'}</b>"
                      f"{(' · ' + updates['status']) if updates.get('status') else ''}", author=user)
    return await db.follow_ups.find_one({"id": fid}, {"_id": 0})


class FollowUpStatusBody(BaseModel):
    status: str


@router.post("/{lead_id}/followups/{fid}/status")
async def set_followup_status(lead_id: int, fid: int, body: FollowUpStatusBody, user: dict = Depends(get_current_user)):
    fu = await db.follow_ups.find_one({"id": fid, "lead_id": lead_id})
    if not fu:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    status = (body.status or "").strip() or None
    await db.follow_ups.update_one({"id": fid}, {"$set": {"status": status}})
    await log_message(lead_id, f"Follow-up marked <b>{status or 'cleared'}</b>", author=user)
    return await db.follow_ups.find_one({"id": fid}, {"_id": 0})


@router.delete("/{lead_id}/followups/{fid}")
async def delete_followup(lead_id: int, fid: int, user: dict = Depends(get_current_user)):
    res = await db.follow_ups.delete_one({"id": fid, "lead_id": lead_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    await _sync_lead_followup(lead_id)
    await log_message(lead_id, "Follow-up entry deleted", author=user)
    return {"ok": True}



# ---------------- Caller Activities (Case 2 — call feedback / communication log) ----------------
class CallerActivityBody(BaseModel):
    feedback: str


@router.get("/{lead_id}/caller-activities")
async def list_caller_activities(lead_id: int, user: dict = Depends(get_current_user)):
    return await db.caller_activities.find({"lead_id": lead_id}, {"_id": 0}).sort("id", -1).to_list(500)


@router.post("/{lead_id}/caller-activities")
async def add_caller_activity(lead_id: int, body: CallerActivityBody, user: dict = Depends(get_current_user)):
    lead = await db.leads.find_one({"id": lead_id}, {"_id": 0, "id": 1})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    fb = (body.feedback or "").strip()
    if not fb:
        raise HTTPException(status_code=400, detail="Feedback note is required")
    aid = await next_id("caller_activity")
    doc = {"id": aid, "lead_id": lead_id, "feedback": fb,
           "created_by": user["id"], "created_by_name": user["name"], "created_at": now_utc_str()}
    await db.caller_activities.insert_one(doc)
    await log_message(lead_id, f"🗣️ Caller activity — {fb}", author=user)
    doc.pop("_id", None)
    return doc


# ---------------- Follow-up analytics + reminders (Case 5 + Case 4) ----------------
@router.get("/followups/analytics")
async def followups_analytics(date: Optional[str] = None, user: dict = Depends(get_current_user)):
    day = date or today_ist()
    pipeline = [{"$match": {"follow_up_date": day}}]
    if user.get("role") == "caller":
        pipeline += [
            {"$lookup": {"from": "leads", "localField": "lead_id", "foreignField": "id", "as": "_lead"}},
            {"$match": {"_lead.user_id": user["id"]}},
        ]
    pipeline += [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    rows = await db.follow_ups.aggregate(pipeline).to_list(50)
    by, total = {}, 0
    for r in rows:
        by[r["_id"] or "__none__"] = r["n"]
        total += r["n"]
    pending = by.get("__none__", 0)
    is_past = day < today_ist()
    return {
        "date": day, "total": total,
        "completed": by.get("Completed", 0),
        "not_done": by.get("Not Done", 0) + (pending if is_past else 0),
        "rescheduled": by.get("Rescheduled", 0),
        "cancelled": by.get("Cancelled", 0),
        "pending": 0 if is_past else pending,
    }


@router.get("/followups/reminders")
async def followups_reminders(user: dict = Depends(get_current_user)):
    now = datetime.now(IST)
    day = now.strftime("%Y-%m-%d")
    now_min = now.hour * 60 + now.minute
    items = await db.follow_ups.find(
        {"follow_up_date": day, "follow_up_time": {"$nin": [None, ""]},
         "status": {"$nin": ["Completed", "Cancelled"]}}, {"_id": 0}).to_list(1000)
    lead_ids = list({it["lead_id"] for it in items})
    leads = {l["id"]: l for l in await db.leads.find(
        {"id": {"$in": lead_ids}},
        {"_id": 0, "id": 1, "contact_name": 1, "name": 1, "phone": 1, "user_id": 1}).to_list(2000)}
    out = []
    for it in items:
        lead = leads.get(it["lead_id"])
        if not lead:
            continue
        if user.get("role") == "caller" and lead.get("user_id") != user["id"]:
            continue
        try:
            h, m = it["follow_up_time"].split(":")[:2]
            sched = int(h) * 60 + int(m)
        except (ValueError, AttributeError):
            continue
        if now_min >= sched - 5:  # reminder window opens 5 min before the scheduled time
            out.append({
                "follow_up_id": it["id"], "lead_id": it["lead_id"],
                "lead_name": lead.get("contact_name") or lead.get("name") or f"Lead {it['lead_id']}",
                "phone": lead.get("phone"), "follow_up_time": it["follow_up_time"],
                "follow_up_date": it["follow_up_date"], "note": it.get("note"), "status": it.get("status"),
            })
    return {"now": now.strftime("%H:%M"), "reminders": out}

