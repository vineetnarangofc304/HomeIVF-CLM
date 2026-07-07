"""Case 14 / Case 3 — Email / WhatsApp marketing campaigns: create, preview, send in bulk,
track live delivery/read/reply stats, progress, pause/resume and edit."""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import require_permission
from core.utils import next_id, now_utc_str, record_wa_outbound
from core import whatsapp_cloud as wac
from routes.leads import build_query

router = APIRouter(prefix="/marketing", tags=["marketing"])

MAX_SEND = 5000
AUDIENCE_KEYS = ["search", "lead_stage", "tags", "user_id", "source_lead", "campaign_name",
                 "ads_platform", "city", "state_name", "follow_up_tag", "priority", "active"]


def _audience_query(audience: dict, user: dict) -> dict:
    params = {k: None for k in [
        "search", "stage_id", "lead_stage", "tags", "user_id", "source_lead", "campaign_name",
        "ads_platform", "city", "state_name", "date_from", "date_to", "follow_up", "priority",
        "follow_up_tag", "lost_reason_id"]}
    params["active"] = audience.get("active", "true")
    for k in AUDIENCE_KEYS:
        if k != "active" and audience.get(k) not in (None, ""):
            params[k] = audience[k]
    return build_query(**params, current_user=user)


async def _template_of(camp: dict):
    if not camp.get("template_id"):
        return None
    coll = db.templates_whatsapp if camp["channel"] == "whatsapp" else db.templates_email
    return await coll.find_one({"id": int(camp["template_id"])}, {"_id": 0})


def _audience_desc(audience: dict) -> str:
    """Human-readable trigger / logic summary for a campaign box."""
    parts = []
    labels = {"lead_stage": "Stage", "source_lead": "Source", "tags": "Tag",
              "city": "City", "state_name": "State", "follow_up_tag": "Follow-up",
              "priority": "Priority", "search": "Search"}
    for k, label in labels.items():
        v = audience.get(k)
        if v not in (None, ""):
            parts.append(f"{label}: {v}")
    return " · ".join(parts) if parts else "All active leads"


class CampaignBody(BaseModel):
    name: str
    channel: str  # whatsapp | email
    template_id: Optional[int] = None
    audience: dict = {}


class CampaignPatch(BaseModel):
    name: Optional[str] = None
    template_id: Optional[int] = None
    audience: Optional[dict] = None


async def _enrich(camps: list) -> list:
    """Attach live delivered/read/replied counts (from wa_tracking) + progress % + labels."""
    ids = [c["id"] for c in camps]
    stats: dict = {}
    if ids:
        pipeline = [{"$match": {"campaign_id": {"$in": ids}}},
                    {"$group": {"_id": {"c": "$campaign_id", "s": "$status"}, "n": {"$sum": 1}}}]
        async for row in db.wa_tracking.aggregate(pipeline):
            stats.setdefault(row["_id"]["c"], {})[row["_id"]["s"]] = row["n"]
    tpl_ids_wa = [int(c["template_id"]) for c in camps if c["channel"] == "whatsapp" and c.get("template_id")]
    tpl_ids_em = [int(c["template_id"]) for c in camps if c["channel"] == "email" and c.get("template_id")]
    names = {}
    if tpl_ids_wa:
        async for t in db.templates_whatsapp.find({"id": {"$in": tpl_ids_wa}}, {"_id": 0, "id": 1, "name": 1}):
            names[("whatsapp", t["id"])] = t["name"]
    if tpl_ids_em:
        async for t in db.templates_email.find({"id": {"$in": tpl_ids_em}}, {"_id": 0, "id": 1, "name": 1}):
            names[("email", t["id"])] = t["name"]
    for c in camps:
        st = stats.get(c["id"], {})
        c["read"] = st.get("read", 0) + st.get("replied", 0)
        c["delivered"] = st.get("delivered", 0) + c["read"]
        c["replied"] = st.get("replied", 0)
        c["template_name"] = names.get((c["channel"], c.get("template_id")))
        c["trigger_desc"] = _audience_desc(c.get("audience") or {})
        total = c.get("total") or 0
        processed = (c.get("sent", 0) + c.get("failed", 0) + c.get("queued", 0))
        c["progress"] = round(processed / total * 100) if total else (100 if c.get("status") == "completed" else 0)
    return camps


@router.get("/campaigns")
async def list_campaigns(user: dict = Depends(require_permission("marketing"))):
    camps = await db.campaigns.find({}, {"_id": 0}).sort("id", -1).to_list(200)
    return await _enrich(camps)


@router.post("/campaigns")
async def create_campaign(body: CampaignBody, user: dict = Depends(require_permission("marketing"))):
    if body.channel not in ("whatsapp", "email"):
        raise HTTPException(status_code=400, detail="Invalid channel")
    cid = await next_id("campaign")
    doc = {"id": cid, "name": body.name.strip(), "channel": body.channel,
           "template_id": body.template_id, "audience": body.audience or {},
           "status": "draft", "total": 0, "sent": 0, "failed": 0, "queued": 0,
           "created_by": user["name"], "created_at": now_utc_str()}
    await db.campaigns.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/campaigns/{cid}")
async def edit_campaign(cid: int, body: CampaignPatch, user: dict = Depends(require_permission("marketing"))):
    camp = await db.campaigns.find_one({"id": cid}, {"_id": 0})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if camp.get("status") == "in_progress":
        raise HTTPException(status_code=409, detail="Pause the campaign before editing")
    updates = {}
    if body.name is not None:
        updates["name"] = body.name.strip()
    if body.template_id is not None:
        updates["template_id"] = body.template_id
    if body.audience is not None:
        updates["audience"] = body.audience
    if updates:
        await db.campaigns.update_one({"id": cid}, {"$set": updates})
    return await db.campaigns.find_one({"id": cid}, {"_id": 0})


@router.delete("/campaigns/{cid}")
async def delete_campaign(cid: int, user: dict = Depends(require_permission("marketing"))):
    await db.campaigns.delete_one({"id": cid})
    return {"ok": True}


@router.post("/campaigns/{cid}/audience-count")
async def audience_count(cid: int, user: dict = Depends(require_permission("marketing"))):
    camp = await db.campaigns.find_one({"id": cid}, {"_id": 0})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    q = _audience_query(camp.get("audience") or {}, user)
    field = "phone_digits" if camp["channel"] == "whatsapp" else "email_from"
    q[field] = {"$nin": [None, "", False]}
    return {"count": await db.leads.count_documents(q)}


@router.get("/campaigns/{cid}/failures")
async def campaign_failures(cid: int, user: dict = Depends(require_permission("marketing"))):
    camp = await db.campaigns.find_one({"id": cid}, {"_id": 0})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    out = []
    if camp["channel"] == "whatsapp":
        async for r in db.wa_tracking.find(
                {"campaign_id": cid, "status": {"$in": ["failed", "bounced"]}},
                {"_id": 0, "lead_id": 1, "sent_to": 1, "error": 1, "error_code": 1}).limit(200):
            out.append({"lead_id": r.get("lead_id"), "to": r.get("sent_to"),
                        "error": r.get("error") or "Unknown error", "code": r.get("error_code")})
    else:
        async for r in db.outbound_queue.find(
                {"campaign_id": cid, "status": "failed"},
                {"_id": 0, "lead_id": 1, "to": 1, "error": 1}).limit(200):
            out.append({"lead_id": r.get("lead_id"), "to": r.get("to"),
                        "error": r.get("error") or "Unknown error", "code": None})
    return {"failures": out, "count": len(out)}


@router.post("/campaigns/{cid}/pause")
async def pause_campaign(cid: int, user: dict = Depends(require_permission("marketing"))):
    camp = await db.campaigns.find_one({"id": cid}, {"_id": 0})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if camp.get("status") != "in_progress":
        raise HTTPException(status_code=409, detail="Campaign is not running")
    await db.campaigns.update_one({"id": cid}, {"$set": {"status": "paused"}})
    return {"ok": True, "status": "paused"}


async def _run_campaign(cid: int, user: dict):
    """Background sender: streams the audience, sends per lead, updates progress live,
    honours pause, and marks Completed at 100%."""
    try:
        camp = await db.campaigns.find_one({"id": cid}, {"_id": 0})
        if not camp:
            return
        template = await _template_of(camp)
        if not template:
            await db.campaigns.update_one({"id": cid}, {"$set": {"status": "failed"}})
            return

        wa_live = await wac.is_configured() if camp["channel"] == "whatsapp" else False
        email_live = False
        if camp["channel"] == "email":
            from core import gmail_send as gm
            email_live = await gm.is_connected()

        # Skip leads already processed (supports resume after pause).
        done_ids = set()
        if camp["channel"] == "whatsapp":
            async for r in db.wa_tracking.find({"campaign_id": cid}, {"_id": 0, "lead_id": 1}):
                done_ids.add(r.get("lead_id"))
        else:
            async for r in db.outbound_queue.find({"campaign_id": cid}, {"_id": 0, "lead_id": 1}):
                done_ids.add(r.get("lead_id"))

        sent = camp.get("sent", 0)
        failed = camp.get("failed", 0)
        queued = camp.get("queued", 0)

        q = _audience_query(camp.get("audience") or {}, user)
        field = "phone_digits" if camp["channel"] == "whatsapp" else "email_from"
        q[field] = {"$nin": [None, "", False]}

        n = 0
        cursor = db.leads.find(q, {"_id": 0}).limit(MAX_SEND)
        async for lead in cursor:
            if lead["id"] in done_ids:
                continue
            # Check pause flag periodically.
            if n % 5 == 0:
                cur = await db.campaigns.find_one({"id": cid}, {"_id": 0, "status": 1})
                if cur and cur.get("status") == "paused":
                    await db.campaigns.update_one({"id": cid}, {"$set": {
                        "sent": sent, "failed": failed, "queued": queued}})
                    return

            if camp["channel"] == "whatsapp":
                phone = lead.get("phone") or lead.get("mobile") or ""
                body_prev = (template.get("body") or "").replace("{{1}}", lead.get("contact_name") or lead.get("name") or "")
                if wa_live:
                    res = await wac.send_lead_template(lead, template)
                    if res.get("ok"):
                        sent += 1
                        await record_wa_outbound(lead_id=lead["id"], template_id=template["id"],
                            template_name=template["name"], sent_to=phone, body=body_prev,
                            created_by=f"Campaign: {camp['name']}", status="sent",
                            wamid=res.get("wamid"), source="campaign", campaign_id=cid)
                    else:
                        failed += 1
                        await db.outbound_queue.insert_one({"channel": "whatsapp", "lead_id": lead["id"],
                            "template_id": template["id"], "status": "failed", "campaign_id": cid,
                            "error": res.get("error"), "created_at": now_utc_str()})
                        await record_wa_outbound(lead_id=lead["id"], template_id=template["id"],
                            template_name=template["name"], sent_to=phone, body=body_prev,
                            created_by=f"Campaign: {camp['name']}", status="failed",
                            source="campaign", error=res.get("error"), campaign_id=cid)
                else:
                    queued += 1
                    await db.outbound_queue.insert_one({"channel": "whatsapp", "lead_id": lead["id"],
                        "template_id": template["id"], "status": "pending_api_credentials",
                        "campaign_id": cid, "created_at": now_utc_str()})
                    await record_wa_outbound(lead_id=lead["id"], template_id=template["id"],
                        template_name=template["name"], sent_to=phone, body=body_prev,
                        created_by=f"Campaign: {camp['name']}", status="in_queue",
                        source="campaign", campaign_id=cid)
            else:
                to = (lead.get("email_from") or "").strip()
                name = lead.get("contact_name") or "there"
                body_txt = (template.get("body") or "").replace("{{1}}", name)
                subject = template.get("subject") or camp["name"]
                if email_live and to:
                    from core import gmail_send as gm
                    res = await gm.send_email(to, subject, body_txt, html=True)
                    if res.get("ok"):
                        sent += 1
                        await db.outbound_queue.insert_one({"channel": "email", "lead_id": lead["id"],
                            "to": to, "subject": subject, "status": "sent", "template_id": template["id"],
                            "campaign_id": cid, "created_at": now_utc_str()})
                    else:
                        failed += 1
                        await db.outbound_queue.insert_one({"channel": "email", "lead_id": lead["id"],
                            "to": to, "subject": subject, "body": body_txt, "status": "failed",
                            "error": res.get("error"), "template_id": template["id"], "campaign_id": cid,
                            "created_at": now_utc_str()})
                else:
                    queued += 1
                    await db.outbound_queue.insert_one({"channel": "email", "lead_id": lead["id"],
                        "to": to, "subject": subject, "body": body_txt, "template_id": template["id"],
                        "status": "pending_api_credentials", "campaign_id": cid, "created_at": now_utc_str()})

            n += 1
            if n % 10 == 0:
                await db.campaigns.update_one({"id": cid}, {"$set": {
                    "sent": sent, "failed": failed, "queued": queued}})

        # Finished the whole audience.
        if sent == 0 and failed > 0 and queued == 0:
            status = "failed"
        elif queued and not sent:
            status = "queued"
        else:
            status = "completed"
        await db.campaigns.update_one({"id": cid}, {"$set": {
            "status": status, "sent": sent, "failed": failed, "queued": queued,
            "finished_at": now_utc_str()}})
    except Exception as e:  # noqa: BLE001
        await db.campaigns.update_one({"id": cid}, {"$set": {"status": "failed", "error": str(e)}})


@router.post("/campaigns/{cid}/send")
async def send_campaign(cid: int, user: dict = Depends(require_permission("marketing"))):
    camp = await db.campaigns.find_one({"id": cid}, {"_id": 0})
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if camp.get("status") == "in_progress":
        raise HTTPException(status_code=409, detail="Campaign is already sending")
    template = await _template_of(camp)
    if not template:
        raise HTTPException(status_code=400, detail="Select a valid template first")

    q = _audience_query(camp.get("audience") or {}, user)
    field = "phone_digits" if camp["channel"] == "whatsapp" else "email_from"
    q[field] = {"$nin": [None, "", False]}
    total = await db.leads.count_documents(q)
    if total == 0:
        raise HTTPException(status_code=400, detail="No recipients match this audience")

    resuming = camp.get("status") == "paused"
    set_fields = {"status": "in_progress", "total": total}
    if not resuming:
        set_fields.update({"sent": 0, "failed": 0, "queued": 0, "started_at": now_utc_str()})
    await db.campaigns.update_one({"id": cid}, {"$set": set_fields})

    asyncio.create_task(_run_campaign(cid, user))
    return {"ok": True, "status": "in_progress", "total": total, "resuming": resuming}
