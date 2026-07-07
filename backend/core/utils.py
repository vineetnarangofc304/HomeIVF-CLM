from datetime import datetime, timezone, timedelta

from core.db import db

IST_OFFSET = timedelta(hours=5, minutes=30)


def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def to_ist_str(utc_str: str) -> str:
    try:
        dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S")
        return (dt + IST_OFFSET).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return utc_str

async def ensure_catalog(ctype: str, name: str) -> dict:
    """Get-or-create a catalog item (e.g. source_lead 'Meta Lead Ads') so it shows
    in the Source/dropdown filters. Uses max-id+1 (migrated catalogs bypass counters)."""
    import re
    if not name:
        return {}
    doc = await db.catalogs.find_one(
        {"type": ctype, "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}, {"_id": 0})
    if doc:
        return doc
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
    return {"id": cid, "type": ctype, "name": name, "active": True}




async def check_duplicate(phone_digits: str, exclude_id: int = None) -> dict:
    """Case 20 — flag duplicate leads by phone. Returns {is_duplicate, duplicate_of, duplicate_count}."""
    if not phone_digits or len(phone_digits) < 8:
        return {"is_duplicate": False, "duplicate_of": None, "duplicate_count": 0}
    q = {"phone_digits": phone_digits, "active": True}
    if exclude_id is not None:
        q["id"] = {"$ne": exclude_id}
    existing = await db.leads.find_one(q, {"_id": 0, "id": 1}, sort=[("id", 1)])
    count = await db.leads.count_documents(q)
    return {"is_duplicate": bool(existing), "duplicate_of": existing["id"] if existing else None,
            "duplicate_count": count}


def today_ist() -> str:
    return (datetime.now(timezone.utc) + IST_OFFSET).strftime("%Y-%m-%d")


async def next_id(name: str) -> int:
    doc = await db.counters.find_one_and_update(
        {"_id": name}, {"$inc": {"seq": 1}}, upsert=True, return_document=True
    )
    return doc["seq"]


async def log_message(lead_id: int, body: str, author: dict = None, subtype: str = "tracking", extra: dict = None):
    mid = await next_id("message")
    msg = {
        "id": mid,
        "lead_id": lead_id,
        "body": body,
        "author_id": author["id"] if author else None,
        "author_name": author["name"] if author else "System",
        "date": now_utc_str(),
        "message_type": "comment" if subtype in ("note", "comment") else "notification",
        "subtype": subtype,
    }
    if extra:
        msg.update(extra)
    await db.messages.insert_one(msg)
    msg.pop("_id", None)
    return msg


# WhatsApp message lifecycle (Case 5 — message tracking flow)
WA_STATUS_FLOW = ["in_queue", "sent", "delivered", "read", "replied", "received", "failed", "bounced", "cancelled"]


async def record_wa_outbound(*, lead_id, template_id, template_name, sent_to, body,
                             created_by, status, wamid=None, source="manual", error=None,
                             campaign_id=None):
    """Store an outbound WhatsApp template message for end-to-end status tracking.
    The same record is later updated from Meta status webhooks (by wamid)."""
    tid = await next_id("wa_track")
    now = now_utc_str()
    doc = {
        "id": tid, "wamid": wamid, "lead_id": lead_id,
        "template_id": template_id, "template_name": template_name,
        "sent_to": sent_to, "body": body, "created_by": created_by, "source": source,
        "campaign_id": campaign_id,
        "status": status, "error": error, "failure_type": None, "error_code": None,
        "created_at": now, "status_at": now,
        "status_history": [{"status": status, "at": now}],
    }
    await db.wa_tracking.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def run_automations(trigger: str, lead: dict, extra: dict = None):
    """Execute automation rules. Template sends are queued (pending outbound) until live APIs are connected."""
    extra = extra or {}
    cursor = db.automations.find({"trigger": trigger, "active": True}, {"_id": 0})
    async for rule in cursor:
        cond = rule.get("condition") or {}
        if cond.get("stage_id") and lead.get("stage_id") != cond["stage_id"]:
            continue
        if cond.get("lead_stage") and lead.get("lead_stage") != cond["lead_stage"]:
            continue
        if cond.get("tag_id"):
            changed_tags = extra.get("added_tags", lead.get("tags") or [])
            if cond["tag_id"] not in changed_tags:
                continue
        await _apply_actions(rule, lead)


async def run_automation_by_id(automation_id, lead: dict):
    """Run a specific automation's actions (used by WhatsApp Quick Reply buttons)."""
    try:
        rule = await db.automations.find_one({"id": int(automation_id)}, {"_id": 0})
    except (TypeError, ValueError):
        rule = None
    if not rule:
        return None
    await _apply_actions(rule, lead)
    return rule


async def _apply_actions(rule: dict, lead: dict):
    updates = {}
    for action in rule.get("actions", []):
        atype, value = action.get("type"), action.get("value")
        if atype == "add_tag" and value:
            tags = set(lead.get("tags") or [])
            tags.add(int(value))
            updates["tags"] = list(tags)
        elif atype == "set_lead_stage" and value:
            updates["lead_stage"] = value
        elif atype == "assign_user" and value:
            updates["user_id"] = int(value)
        elif atype in ("send_whatsapp_template", "send_email_template") and value:
            is_wa = atype == "send_whatsapp_template"
            sent_live = False
            res = {}
            if is_wa:
                from core import whatsapp_cloud as wac
                tmpl = await db.templates_whatsapp.find_one({"id": int(value)}, {"_id": 0})
                phone = lead.get("phone") or lead.get("mobile")
                body_prev = ((tmpl.get("body") or "") if tmpl else "").replace("{{1}}", lead.get("contact_name") or lead.get("name") or "")
                if await wac.is_configured() and tmpl and phone:
                    res = await wac.send_lead_template(lead, tmpl)
                    sent_live = res.get("ok", False)
                track = None
                if tmpl:
                    track = await record_wa_outbound(
                        lead_id=lead["id"], template_id=int(value), template_name=tmpl.get("name") or str(value),
                        sent_to=phone or "", body=body_prev, created_by=f"Automation: {rule['name']}",
                        status=("sent" if sent_live else "in_queue"), wamid=res.get("wamid") if sent_live else None,
                        source="automation", error=(res.get("error") if not sent_live else None))
                    await log_message(
                        lead["id"],
                        f"Automation '{rule['name']}': WhatsApp template <b>{tmpl['name']}</b> "
                        + ("sent via Cloud API" if sent_live else (f"failed ({res.get('error')})" if res else "queued")),
                        extra={"kind": "wa_template", "channel": "whatsapp", "preview": body_prev,
                               "template_name": tmpl.get("name"), "track_id": track["id"],
                               "status": ("sent" if sent_live else "in_queue")})
            else:
                from core import gmail_send as gm
                tmpl = await db.templates_email.find_one({"id": int(value)}, {"_id": 0})
                email_body = (tmpl.get("body") if tmpl else "") or ""
                subject = (tmpl.get("subject") if tmpl else "") or "(no subject)"
                to = lead.get("email_from")
                if tmpl and to and await gm.is_connected():
                    res = await gm.send_email(to, subject, email_body, html=True)
                    sent_live = res.get("ok", False)
                if tmpl:
                    await log_message(
                        lead["id"],
                        f"Automation '{rule['name']}': Email template <b>{subject}</b> " + ("sent" if sent_live else "queued"),
                        subtype="comment",
                        extra={"kind": "email_template", "channel": "email", "preview": email_body,
                               "template_name": subject, "subject": subject,
                               "status": ("sent" if sent_live else "in_queue")})
            if not sent_live:
                await db.outbound_queue.insert_one({
                    "lead_id": lead["id"],
                    "channel": "whatsapp" if is_wa else "email",
                    "template_id": value,
                    "status": "pending_api_credentials",
                    "automation": rule["name"],
                    "created_at": now_utc_str(),
                })
    if updates:
        await db.leads.update_one({"id": lead["id"]}, {"$set": updates})
        lead.update(updates)
        await log_message(lead["id"], f"Automation '{rule['name']}' applied: {', '.join(updates.keys())}")
