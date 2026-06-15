"""Ozonetel telephony integration — incoming-call screen-pop, call logging & click-to-dial.

Ozonetel hits the Screen-Pop URL on each incoming call with query params
(phoneNumber, callerID, ucid, did, agentID, phoneName, agentPhoneNumber,
campaignID, type, dataID, uui, ...). We record the call, match it to a lead by
phone, log it to the lead chatter, and surface a live incoming-call banner to the
mapped CRM agent. Click-to-dial pushes a number into an Ozonetel outbound
campaign via the Add Campaign Data API.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user, require_roles
from core.utils import log_message, next_id, now_utc_str, to_ist_str

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
    page: int = 1, limit: int = 50, direction: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    q = {}
    if user["role"] == "caller":
        q["user_id"] = user["id"]
    if direction:
        q["direction"] = direction
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
