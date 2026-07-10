"""Ozonetel telephony integration — incoming-call screen-pop, call logging,
CDR callback (status/duration/recording/disposition), auto lead creation,
click-to-dial & batch push to the progressive autodialer campaign.
"""
import re
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user, require_roles
from core.utils import log_message, next_id, now_utc_str, run_automations, to_ist_str, ist_date_parts

router = APIRouter(prefix="/calls", tags=["calls"])

LEAD_SUMMARY = {
    "_id": 0, "id": 1, "name": 1, "contact_name": 1, "phone": 1, "email_from": 1,
    "city": 1, "state_name": 1, "lead_stage": 1, "tags": 1, "user_id": 1,
    "source_lead": 1, "follow_up_tag": 1, "follow_up_date": 1, "active": 1,
}


def norm_phone(p: Optional[str]) -> str:
    digits = re.sub(r"\D", "", str(p or ""))
    return digits[-10:] if len(digits) >= 10 else digits


def _params_from_request(request: Request, body: dict) -> dict:
    """Merge query params + JSON/form body (Ozonetel may use either)."""
    merged = dict(request.query_params)
    if body:
        merged.update({k: v for k, v in body.items() if v is not None})
    return merged


async def _match_lead(phone_digits: str):
    if phone_digits and len(phone_digits) >= 7:
        return await db.leads.find_one(
            {"phone_digits": phone_digits}, LEAD_SUMMARY, sort=[("write_date", -1)]
        )
    return None


async def _match_agent(agent_oid: Optional[str], phone_name: Optional[str]):
    if agent_oid:
        u = await db.users.find_one({"ozonetel_agent_id": agent_oid}, {"_id": 0, "id": 1, "name": 1})
        if u:
            return u
    if phone_name:
        u = await db.users.find_one({"ozonetel_phone_name": phone_name}, {"_id": 0, "id": 1, "name": 1})
        if u:
            return u
    return None


async def _ensure_catalog(ctype: str, name: str) -> dict:
    doc = await db.catalogs.find_one({"type": ctype, "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}, {"_id": 0})
    if doc:
        return doc
    # safe id: max existing id for this type + 1 (migrated catalogs bypassed the counter)
    last = await db.catalogs.find_one({"type": ctype}, sort=[("id", -1)])
    cid = (last.get("id", 0) if last else 0) + 1
    for _ in range(5):
        try:
            doc = {"id": cid, "type": ctype, "name": name, "active": True}
            await db.catalogs.insert_one(doc)
            doc.pop("_id", None)
            return doc
        except Exception:
            cid += 1
    raise HTTPException(status_code=500, detail="Could not create catalog item")


async def _create_call_lead(phone: str, source_name: str, missed: bool = False, agent: Optional[dict] = None, name: Optional[str] = None) -> dict:
    pdig = norm_phone(phone)
    src = await _ensure_catalog("source_lead", source_name)
    tags = []
    if missed:
        t = await _ensure_catalog("tag", "Missed Call")
        tags = [t["id"]]
    lid = await next_id("lead")
    now = now_utc_str()
    doc = {
        "id": lid, "active": True, "stage_id": 1, "type": "lead", "priority": "0",
        "name": name or phone or "Ozonetel Lead", "contact_name": name,
        "phone": phone, "phone_digits": pdig, "tags": tags,
        "source_lead": src["name"], "lead_stage": None,
        "user_id": agent["id"] if agent else None,
        "create_date": now, "create_date_ist": to_ist_str(now), "write_date": now,
        "custom": {}, "ozonetel_lead": True,
    }
    doc.update(ist_date_parts(doc["create_date_ist"]))
    await db.leads.insert_one(doc)
    await log_message(lid, f"Lead auto-created from {source_name} (via Ozonetel)")
    await run_automations("on_create", doc)
    doc.pop("_id", None)
    return doc


async def _record_incoming(params: dict) -> dict:
    ucid = (params.get("ucid") or params.get("monitorUcid") or "").strip() or None
    # Idempotency: Ozonetel may hit both client + server side for the same call
    if ucid:
        existing = await db.call_events.find_one({"ucid": ucid}, {"_id": 0})
        if existing:
            lead = None
            if existing.get("lead_id"):
                lead = await db.leads.find_one({"id": existing["lead_id"]}, LEAD_SUMMARY)
            return {"ok": True, "call_id": existing["id"], "matched": bool(lead), "lead": lead, "call": existing}

    phone = (params.get("phoneNumber") or params.get("callerID")
             or params.get("customer") or "").strip()
    pdig = norm_phone(phone)
    agent_oid = str(params.get("agentID") or "").strip() or None
    phone_name = (params.get("phoneName") or "").strip() or None

    lead = await _match_lead(pdig)
    agent = await _match_agent(agent_oid, phone_name)

    cid = await next_id("call")
    now = now_utc_str()
    doc = {
        "id": cid,
        "direction": "incoming",
        "status": "ringing",
        "ucid": ucid,
        "phone": phone,
        "phone_digits": pdig,
        "caller_id": params.get("callerID"),
        "did": params.get("did"),
        "campaign_id": params.get("campaignID"),
        "call_type": params.get("type"),
        "data_id": params.get("dataID"),
        "uui": params.get("uui"),
        "skill_name": params.get("skillName"),
        "agent_ozonetel_id": agent_oid,
        "agent_phone_name": phone_name,
        "agent_phone_number": params.get("agentPhoneNumber"),
        "user_id": agent["id"] if agent else (lead.get("user_id") if lead else None),
        "lead_id": lead["id"] if lead else None,
        "lead_name": (lead.get("contact_name") or lead.get("name")) if lead else None,
        "created_at": now,
        "created_at_ist": to_ist_str(now),
        "raw": params,
    }
    await db.call_events.insert_one(doc)
    if lead:
        agent_label = agent["name"] if agent else (phone_name or "an agent")
        await log_message(
            lead["id"],
            f"📞 Incoming call from {phone or pdig} — routed to {agent_label} (via Ozonetel)",
            subtype="tracking",
        )
    doc.pop("_id", None)
    return {"ok": True, "call_id": cid, "matched": bool(lead), "lead": lead, "call": doc}


# ---- Public webhook / screen-pop receiver (Ozonetel calls this; no auth) ----
@router.api_route("/ozonetel/screenpop", methods=["GET", "POST"])
async def ozonetel_screenpop(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        try:
            form = await request.form()
            body = dict(form)
        except Exception:
            body = {}
    params = _params_from_request(request, body if isinstance(body, dict) else {})
    return await _record_incoming(params)


# ---- Live incoming-call for the logged-in agent (banner polling) ----
@router.get("/active")
async def active_call(user: dict = Depends(get_current_user)):
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=45)).strftime("%Y-%m-%d %H:%M:%S")
    ors = [{"user_id": user["id"]}]
    if user.get("ozonetel_agent_id"):
        ors.append({"agent_ozonetel_id": str(user["ozonetel_agent_id"])})
    if user.get("ozonetel_phone_name"):
        ors.append({"agent_phone_name": user["ozonetel_phone_name"]})
    q = {"direction": "incoming", "created_at": {"$gte": cutoff}, "$or": ors}
    call = await db.call_events.find_one(q, {"_id": 0}, sort=[("created_at", -1)])
    if not call:
        return {"active": None}
    lead = None
    if call.get("lead_id"):
        lead = await db.leads.find_one({"id": call["lead_id"]}, LEAD_SUMMARY)
    return {"active": call, "lead": lead}


# ---- Call logs ----
@router.get("")
async def list_calls(
    page: int = 1, limit: int = 50, direction: Optional[str] = None, status: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    q = {}
    if user["role"] == "caller":
        q["user_id"] = user["id"]
    if direction:
        q["direction"] = direction
    if status:
        q["status"] = status
    total = await db.call_events.count_documents(q)
    skip = (max(page, 1) - 1) * limit
    items = await db.call_events.find(q, {"_id": 0, "raw": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    # resolve agent names
    uids = list({i["user_id"] for i in items if i.get("user_id")})
    umap = {}
    if uids:
        async for u in db.users.find({"id": {"$in": uids}}, {"_id": 0, "id": 1, "name": 1}):
            umap[u["id"]] = u["name"]
    for i in items:
        i["agent_name"] = umap.get(i.get("user_id"))
    return {"items": items, "total": total, "page": page}


@router.get("/lead/{lead_id}")
async def lead_calls(lead_id: int, user: dict = Depends(get_current_user)):
    items = await db.call_events.find({"lead_id": lead_id}, {"_id": 0, "raw": 0}).sort("created_at", -1).to_list(100)
    uids = list({i["user_id"] for i in items if i.get("user_id")})
    umap = {}
    if uids:
        async for u in db.users.find({"id": {"$in": uids}}, {"_id": 0, "id": 1, "name": 1}):
            umap[u["id"]] = u["name"]
    for i in items:
        i["agent_name"] = umap.get(i.get("user_id"))
    return items


# ---- Click-to-dial (outbound via Ozonetel Add Campaign Data API) ----
class DialBody(BaseModel):
    lead_id: Optional[int] = None
    phone: Optional[str] = None


@router.post("/dial")
async def click_to_dial(body: DialBody, user: dict = Depends(get_current_user)):
    cfg = await db.settings.find_one({"key": "ozonetel"}, {"_id": 0})
    if not cfg or not cfg.get("api_key") or not cfg.get("username") or not cfg.get("campaign_name"):
        raise HTTPException(status_code=400, detail="Ozonetel is not configured (Admin → Telephony). Need API key, username & campaign.")
    domain = cfg.get("domain") or "in1-ccaas-api.ozonetel.com"

    lead = None
    phone = body.phone
    if body.lead_id:
        lead = await db.leads.find_one({"id": body.lead_id}, LEAD_SUMMARY)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        phone = phone or lead.get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="No phone number to dial")

    payload = {
        "apiKey": cfg["api_key"],
        "userName": cfg["username"],
        "campaignName": cfg["campaign_name"],
        "phoneNumber": str(phone),
        "name": (lead.get("contact_name") or lead.get("name")) if lead else "CRM Lead",
        "checkDuplicate": "false",
    }
    if user.get("ozonetel_agent_id"):
        payload["agentId"] = str(user["ozonetel_agent_id"])
    if cfg.get("priority"):
        payload["priority"] = cfg["priority"]

    url = f"https://{domain}/ca_apis/AddCampaignData"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ozonetel request failed: {e}")

    ok = str(data.get("status", "")).lower() in ("success", "true")
    cid = await next_id("call")
    now = now_utc_str()
    await db.call_events.insert_one({
        "id": cid, "direction": "outbound", "status": "queued" if ok else "failed",
        "phone": str(phone), "phone_digits": norm_phone(phone),
        "lead_id": lead["id"] if lead else None,
        "lead_name": (lead.get("contact_name") or lead.get("name")) if lead else None,
        "user_id": user["id"], "campaign": cfg["campaign_name"],
        "created_at": now, "created_at_ist": to_ist_str(now),
        "ozonetel_response": data,
    })
    if lead:
        await log_message(lead["id"], f"📲 Click-to-dial queued to {phone} via Ozonetel ({data.get('message', '')})", user, subtype="tracking")
    if not ok:
        raise HTTPException(status_code=400, detail=f"Ozonetel: {data.get('message', 'dial failed')}")
    return {"ok": True, "response": data}



# ---- Agent disposition + notes after a call (§4) ----
DISPOSITIONS = {"Interested", "Not interested", "Call back later", "Converted"}


class DispositionBody(BaseModel):
    disposition: str
    note: Optional[str] = None
    follow_up_date: Optional[str] = None


@router.post("/{call_id}/disposition")
async def set_disposition(call_id: int, body: DispositionBody, user: dict = Depends(get_current_user)):
    if body.disposition not in DISPOSITIONS:
        raise HTTPException(status_code=400, detail="Invalid disposition")
    call = await db.call_events.find_one({"id": call_id}, {"_id": 0})
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    await db.call_events.update_one({"id": call_id}, {"$set": {
        "disposition": body.disposition, "disposition_note": body.note,
        "disposition_by": user["name"], "disposition_at": now_utc_str(),
    }})
    lead_id = call.get("lead_id")
    if lead_id:
        lead = await db.leads.find_one({"id": lead_id}, {"_id": 0})
        if lead:
            updates = {}
            if body.disposition == "Converted":
                stage = await _ensure_catalog("lead_stage", "Converted")
                updates["lead_stage"] = stage["name"]
            elif body.disposition == "Call back later" and body.follow_up_date:
                updates["follow_up_date"] = body.follow_up_date
                updates["follow_up_tag"] = "To Follow Up"
            # tag the lead with the disposition for easy filtering
            tag = await _ensure_catalog("tag", body.disposition)
            tags = list(lead.get("tags") or [])
            if tag["id"] not in tags:
                tags.append(tag["id"])
            updates["tags"] = tags
            if updates:
                await db.leads.update_one({"id": lead_id}, {"$set": updates})
            note = f"<br/><span style='color:#64748b'>{body.note}</span>" if body.note else ""
            await log_message(lead_id, f"📋 Call disposition: <b>{body.disposition}</b> by {user['name']}{note}", author=user, subtype="comment")
    return {"ok": True, "disposition": body.disposition}


# ---- Batch push to the progressive autodialer campaign (§3) ----
class PushBody(BaseModel):
    lead_ids: list[int] = []


@router.post("/push-to-dialer")
async def push_to_dialer(body: PushBody, user: dict = Depends(get_current_user)):
    cfg = await db.settings.find_one({"key": "ozonetel"}, {"_id": 0})
    if not cfg or not all(cfg.get(k) for k in ("api_key", "username", "campaign_name")):
        raise HTTPException(status_code=400, detail="Ozonetel is not configured (Admin → Telephony). Need API key, username & campaign name.")
    domain = cfg.get("domain") or "in1-ccaas-api.ozonetel.com"
    ids = [int(i) for i in (body.lead_ids or [])][:1000]
    if not ids:
        raise HTTPException(status_code=400, detail="No leads selected")
    out = {"queued": 0, "failed": 0, "skipped": 0, "errors": []}
    url = f"https://{domain}/ca_apis/AddCampaignData"
    async with httpx.AsyncClient(timeout=30) as client:
        for lid in ids:
            lead = await db.leads.find_one({"id": lid}, LEAD_SUMMARY)
            if not lead or not lead.get("phone"):
                out["skipped"] += 1
                continue
            payload = {
                "apiKey": cfg["api_key"], "userName": cfg["username"],
                "campaignName": cfg["campaign_name"], "phoneNumber": str(lead["phone"]),
                "name": lead.get("contact_name") or lead.get("name") or "Lead",
                "checkDuplicate": "true",  # progressive Nonagentwise → skip dup numbers
            }
            try:
                resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text}
                ok = str(data.get("status", "")).lower() in ("success", "true")
            except Exception as e:
                ok, data = False, {"error": str(e)}
            cid = await next_id("call")
            now = now_utc_str()
            await db.call_events.insert_one({
                "id": cid, "direction": "outbound", "status": "queued" if ok else "failed",
                "phone": str(lead["phone"]), "phone_digits": norm_phone(lead["phone"]),
                "lead_id": lid, "lead_name": lead.get("contact_name") or lead.get("name"),
                "user_id": user["id"], "campaign": cfg["campaign_name"],
                "created_at": now, "created_at_ist": to_ist_str(now), "ozonetel_response": data,
            })
            if ok:
                out["queued"] += 1
                await log_message(lid, f"📲 Pushed to Ozonetel autodialer ({cfg['campaign_name']}) by {user['name']}", user, subtype="tracking")
            else:
                out["failed"] += 1
                out["errors"].append({"lead_id": lid, "error": data.get("message") or data.get("error") or "failed"})
    return out


# ---- CDR callback (§1/§2/§6): Ozonetel POSTs final call data after each call ----
def _cdr_get(p: dict, *keys):
    for k in keys:
        if p.get(k) not in (None, ""):
            return p[k]
    return None


@router.api_route("/ozonetel/cdr", methods=["GET", "POST"])
async def ozonetel_cdr(request: Request):
    # Ozonetel sends application/x-www-form-urlencoded with a `data` JSON string.
    payload = {}
    try:
        form = dict(await request.form())
    except Exception:
        form = {}
    if form.get("data"):
        try:
            payload = json.loads(form["data"])
        except Exception:
            payload = form
    elif form:
        payload = form
    else:
        try:
            payload = await request.json()
        except Exception:
            payload = dict(request.query_params)

    phone = _cdr_get(payload, "CallerID", "callerID", "customer", "customerNumber", "phoneNumber", "phone")
    ucid = _cdr_get(payload, "ucid", "UCID", "monitorUcid")
    status_raw = str(_cdr_get(payload, "Status", "status") or "")
    answered = "answer" in status_raw.lower() and "not" not in status_raw.lower()
    duration = _cdr_get(payload, "CallDuration", "Duration", "duration")
    talk_time = _cdr_get(payload, "TalkTime", "talkTime")
    recording = _cdr_get(payload, "AudioFile", "RecordingURL", "recording")
    disposition = _cdr_get(payload, "Disposition", "disposition")
    agent_oid = str(_cdr_get(payload, "AgentID", "agentID") or "").strip() or None
    agent_name = _cdr_get(payload, "AgentName", "agentName")
    phone_name = _cdr_get(payload, "phoneName", "PhoneName")
    campaign = _cdr_get(payload, "CampaignName", "campaignName", "campaignID")
    did = _cdr_get(payload, "DID", "did")

    cfg = await db.settings.find_one({"key": "ozonetel"}, {"_id": 0}) or {}
    out_campaign = cfg.get("campaign_name")
    direction = "outbound" if (campaign and out_campaign and str(campaign) == str(out_campaign)) else "incoming"
    pdig = norm_phone(phone)
    agent = await _match_agent(agent_oid, phone_name)

    ce = await db.call_events.find_one({"ucid": ucid}) if ucid else None
    lead = await _match_lead(pdig)
    if not lead and pdig and len(pdig) >= 8:
        if direction == "incoming":
            src = "Ozonetel Missed Call" if not answered else "Ozonetel Incoming Call"
            lead = await _create_call_lead(phone, src, missed=not answered, agent=agent)
        else:
            lead = await _create_call_lead(phone, "Ozonetel Outbound Call", missed=False, agent=agent)

    status = "connected" if answered else ("missed" if direction == "incoming" else "not_connected")
    fields = {
        "status": status, "call_status_raw": status_raw, "duration": duration, "talk_time": talk_time,
        "recording_url": recording, "disposition": disposition, "did": did, "campaign": campaign,
        "direction": direction, "ended_at": _cdr_get(payload, "EndTime"), "started_at": _cdr_get(payload, "StartTime"),
        "agent_ozonetel_id": agent_oid, "agent_phone_name": phone_name, "agent_name": agent_name,
        "user_id": (agent["id"] if agent else (ce.get("user_id") if ce else (lead.get("user_id") if lead else None))),
        "lead_id": lead["id"] if lead else (ce.get("lead_id") if ce else None),
        "lead_name": (lead.get("contact_name") or lead.get("name")) if lead else (ce.get("lead_name") if ce else None),
        "cdr": payload,
    }
    if ce:
        await db.call_events.update_one({"id": ce["id"]}, {"$set": fields})
        cid = ce["id"]
    else:
        cid = await next_id("call")
        now = now_utc_str()
        await db.call_events.insert_one({"id": cid, "ucid": ucid, "phone": phone, "phone_digits": pdig,
                                         "created_at": now, "created_at_ist": to_ist_str(now), **fields})
    if lead:
        rec = f" · <a href='{recording}' target='_blank'>recording</a>" if recording else ""
        disp = f" · {disposition}" if disposition else ""
        await log_message(lead["id"], f"📞 {direction.title()} call <b>{status}</b> ({duration or '0'}s) with {agent_name or 'agent'}{disp}{rec}", subtype="tracking")
    return {"ok": True, "call_id": cid, "lead_id": lead["id"] if lead else None, "status": status}
