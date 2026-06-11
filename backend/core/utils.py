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
