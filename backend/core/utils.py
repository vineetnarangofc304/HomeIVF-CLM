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


async def log_message(lead_id: int, body: str, author: dict = None, subtype: str = "tracking"):
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
    await db.messages.insert_one(msg)
    msg.pop("_id", None)
    return msg


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
            elif atype in ("send_whatsapp_template", "send_email_template"):
                sent_live = False
                if atype == "send_whatsapp_template" and value:
                    from core import whatsapp_cloud as wac
                    if await wac.is_configured():
                        tmpl = await db.templates_whatsapp.find_one({"id": int(value)}, {"_id": 0})
                        if tmpl and (lead.get("phone") or lead.get("mobile")):
                            res = await wac.send_lead_template(lead, tmpl)
                            sent_live = res.get("ok", False)
                            await log_message(
                                lead["id"],
                                f"Automation '{rule['name']}': WhatsApp template <b>{tmpl['name']}</b> "
                                + ("delivered via Cloud API" if sent_live else f"failed ({res.get('error')})"),
                            )
                if not sent_live:
                    await db.outbound_queue.insert_one({
                        "lead_id": lead["id"],
                        "channel": "whatsapp" if "whatsapp" in atype else "email",
                        "template_id": value,
                        "status": "pending_api_credentials",
                        "automation": rule["name"],
                        "created_at": now_utc_str(),
                    })
                    await log_message(
                        lead["id"],
                        f"Automation '{rule['name']}': queued {('WhatsApp' if 'whatsapp' in atype else 'Email')} template (awaiting live API connection)",
                    )
        if updates:
            await db.leads.update_one({"id": lead["id"]}, {"$set": updates})
            lead.update(updates)
            await log_message(lead["id"], f"Automation '{rule['name']}' applied: {', '.join(updates.keys())}")
