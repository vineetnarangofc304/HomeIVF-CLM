from datetime import datetime, timezone, timedelta

import re
import asyncio
import logging

from core.db import db

logger = logging.getLogger(__name__)

IST_OFFSET = timedelta(hours=5, minutes=30)


def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def to_ist_str(utc_str: str) -> str:
    try:
        dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S")
        return (dt + IST_OFFSET).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return utc_str


def ist_date_parts(ist_str: str) -> dict:
    """Precomputed date parts so heatmap / trends aggregations run index-COVERED
    (no per-document fetch or per-document $dateFromString parse). create_dow uses
    Mongo's $dayOfWeek convention (Sun=1..Sat=7) so new writes match both the
    server-side backfill and the pre-existing heatmap output exactly."""
    try:
        d = datetime.strptime(ist_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return {}
    return {"create_dt": d, "create_dow": (d.isoweekday() % 7) + 1, "create_hour": d.hour}


def search_norm(doc: dict) -> dict:
    """Lowercased search fields for a lead (name_lc/contact_name_lc/email_lc).
    A CASE-SENSITIVE '^prefix' regex on these uses TIGHT index bounds; a
    case-insensitive ($options:i) regex cannot, so it scanned the whole ~120k
    collection on every search — the 'search is slow' + connection-pool-exhaustion
    (login 500) root cause. Recompute whenever name/contact_name/email_from change."""
    out = {}
    for src, dst in (("name", "name_lc"), ("contact_name", "contact_name_lc"), ("email_from", "email_lc")):
        v = doc.get(src)
        out[dst] = v.lower() if isinstance(v, str) and v else None
    return out


async def sync_channel_owner(phone_digits, user_id):
    """Point WhatsApp channel(s) for this number at the lead's assigned caller so
    Case 1 chat-visibility (caller sees only own chats) follows lead reassignment."""
    if not phone_digits:
        return
    d = re.sub(r"\D", "", str(phone_digits))[-10:]
    if len(d) < 8:
        return
    await db.wa_channels.update_many({"phone_digits": {"$regex": re.escape(d) + "$"}},
                                     {"$set": {"owner_id": user_id}})


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
    existing = await db.leads.find_one(q, {"_id": 0, "id": 1}, sort=[("id", 1)], max_time_ms=5000)
    count = await db.leads.count_documents(q, maxTimeMS=5000)
    return {"is_duplicate": bool(existing), "duplicate_of": existing["id"] if existing else None,
            "duplicate_count": count}


async def check_duplicate_today(phone_digits: str, exclude_id: int = None):
    """SAME-DAY dedup (client requirement): return the id of an ACTIVE lead with this phone
    that was created TODAY (IST), else None. A same-phone lead from a PREVIOUS day is a genuinely
    new enquiry and is NOT merged. Uses the selective phone_digits index + a create_date_ist
    residual. Returns the most recent same-day lead so its activity/notes stay together."""
    if not phone_digits or len(phone_digits) < 8:
        return None
    today = today_ist()  # "YYYY-MM-DD" (IST)
    q = {"phone_digits": phone_digits, "active": True,
         "create_date_ist": {"$gte": today + " 00:00:00", "$lte": today + " 23:59:59"}}
    if exclude_id is not None:
        q["id"] = {"$ne": exclude_id}
    doc = await db.leads.find_one(q, {"_id": 0, "id": 1}, sort=[("id", -1)], max_time_ms=5000)
    return doc["id"] if doc else None


def today_ist() -> str:
    return (datetime.now(timezone.utc) + IST_OFFSET).strftime("%Y-%m-%d")


async def next_id(name: str) -> int:
    doc = await db.counters.find_one_and_update(
        {"_id": name}, {"$inc": {"seq": 1}}, upsert=True, return_document=True
    )
    return doc["seq"]


# ---------------- Case 2: presence-based lead routing ----------------
# A caller receives new leads only while working. Per the confirmed spec: "Available"
# AND "On Call" both receive; Lunch/Washroom/Refreshment Break, Meeting and Offline do NOT.
AVAILABLE_STATUSES = {"Available", "On Call"}


async def _presence_callers(prefer_ids=None):
    q = {"active": True, "role": "caller"}
    if prefer_ids:
        q["id"] = {"$in": [int(i) for i in prefer_ids]}
    return await db.users.find(q, {"_id": 0, "id": 1, "status": 1}).sort("id", 1).to_list(500)


async def pick_available_caller(prefer_ids=None):
    """Presence-based round-robin: return the next active caller who is currently
    Available/On Call, or None if NOBODY is available (the lead should be queued)."""
    callers = await _presence_callers(prefer_ids)
    available = [c["id"] for c in callers if (c.get("status") or "Offline") in AVAILABLE_STATUSES]
    if not available:
        return None
    ptr = await next_id("presence_assign_pointer")
    return available[(ptr - 1) % len(available)]


async def pick_any_caller(prefer_ids=None):
    """Fallback when NOBODY is Available/On Call: round-robin across ALL active callers so a
    new lead is never left invisible/unassigned. Returns None only if no active caller exists."""
    callers = await _presence_callers(prefer_ids)
    ids = [c["id"] for c in callers]
    if not ids:
        return None
    ptr = await next_id("any_assign_pointer")
    return ids[(ptr - 1) % len(ids)]


async def queue_lead_for_assignment(lead_id: int):
    """No caller was available when this lead arrived — park it (FIFO) so it is
    auto-assigned the moment a caller becomes Available/On Call."""
    await db.lead_queue.update_one(
        {"lead_id": lead_id},
        {"$setOnInsert": {"lead_id": lead_id, "queued_at": now_utc_str()}},
        upsert=True,
    )


_drain_running = False


async def drain_lead_queue():
    """Assign queued leads (arrived while all callers were offline) round-robin across the
    callers who are CURRENTLY available (FIFO). SINGLE-FLIGHT (only one drain runs at a time
    across the whole pod) + BOUNDED batches + per-query timeouts, so the morning "mark
    Available" rush by 24 callers can't stampede the DB / exhaust the connection pool."""
    global _drain_running
    if _drain_running:
        return 0  # a drain is already processing the queue; the running pass covers new arrivals
    _drain_running = True
    total = 0
    try:
        for _ in range(50):  # up to 50 * 200 = 10k leads per trigger, then yield
            callers = await _presence_callers()
            available = [c["id"] for c in callers if (c.get("status") or "Offline") in AVAILABLE_STATUSES]
            if not available:
                break
            batch = await db.lead_queue.find({}, {"_id": 0}).sort("lead_id", 1).limit(200).max_time_ms(8000).to_list(200)
            if not batch:
                break
            for i, item in enumerate(batch):
                lead_id = item["lead_id"]
                try:
                    lead = await db.leads.find_one(
                        {"id": lead_id},
                        {"_id": 0, "id": 1, "active": 1, "user_id": 1, "phone_digits": 1, "original_user_id": 1},
                        max_time_ms=8000)
                    if not lead or not lead.get("active") or lead.get("user_id"):
                        await db.lead_queue.delete_one({"lead_id": lead_id})
                        continue
                    cid = available[total % len(available)]
                    # Atomic guard: only assign if still unassigned (prevents double-assign).
                    res = await db.leads.update_one(
                        {"id": lead_id, "$or": [{"user_id": None}, {"user_id": {"$exists": False}}]},
                        {"$set": {"user_id": cid, "original_user_id": lead.get("original_user_id") or cid,
                                  "write_date": now_utc_str()}})
                    await db.lead_queue.delete_one({"lead_id": lead_id})
                    if res.modified_count == 0:
                        continue
                    await sync_channel_owner(lead.get("phone_digits"), cid)
                    await log_message(lead_id, "Auto-assigned from the waiting queue (a caller became Available)")
                    total += 1
                except Exception:
                    # never let one bad lead abort the whole drain (runs as a background task)
                    continue
            if len(batch) < 200:
                break
    finally:
        _drain_running = False
    return total


def _secs_since_utc(start: str) -> int:
    try:
        s = datetime.strptime(start, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - s).total_seconds()))
    except Exception:
        return 0


async def reset_stale_statuses():
    """Case 2 (choice 3a) — everyone starts each day Offline and must re-mark Available.
    Once per IST day, close any still-open status log and force every non-Offline user to
    Offline. Idempotent, guarded by settings.status_reset.last_reset_date."""
    today = today_ist()
    guard = await db.settings.find_one({"key": "status_reset"})
    if guard and guard.get("last_reset_date") == today:
        return 0
    now = now_utc_str()
    async for lg in db.status_logs.find(
            {"end": None}, {"_id": 0, "id": 1, "start": 1}).limit(20000).max_time_ms(15000):
        await db.status_logs.update_one(
            {"id": lg["id"]}, {"$set": {"end": now, "duration_sec": _secs_since_utc(lg["start"])}})
    res = await db.users.update_many(
        {"status": {"$ne": "Offline"}}, {"$set": {"status": "Offline", "status_since": now}})
    await db.settings.update_one(
        {"key": "status_reset"},
        {"$set": {"key": "status_reset", "last_reset_date": today, "reset_at": now}}, upsert=True)
    return res.modified_count



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


async def log_audit(lead_id: int, user: dict = None, action: str = "", field: str = None,
                    old=None, new=None, detail: str = None):
    """Case change 1 — structured per-lead audit trail (who / what / old→new / when).
    Multiple callers may now edit any lead, so every change is recorded here."""
    aid = await next_id("audit")
    doc = {
        "id": aid, "lead_id": lead_id,
        "user_id": user.get("id") if user else None,
        "user_name": user.get("name") if user else "System",
        "action": action, "field": field, "old": old, "new": new, "detail": detail,
        "at": now_utc_str(),
    }
    await db.audit_logs.insert_one(doc)
    doc.pop("_id", None)
    return doc


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
                wa_configured = await wac.is_configured()
                res = {}
                if wa_configured and tmpl and phone:
                    res = await wac.send_lead_template(lead, tmpl, require_template=True)
                    sent_live = res.get("ok", False)
                # A configured-but-failed send (e.g. template not linked to an approved
                # Meta template → error 131047) is a real FAILURE, not a pending queue item.
                wa_status = "sent" if sent_live else ("failed" if (wa_configured and res.get("error")) else "in_queue")
                track = None
                if tmpl:
                    track = await record_wa_outbound(
                        lead_id=lead["id"], template_id=int(value), template_name=tmpl.get("name") or str(value),
                        sent_to=phone or "", body=body_prev, created_by=f"Automation: {rule['name']}",
                        status=wa_status, wamid=res.get("wamid") if sent_live else None,
                        source="automation", error=(res.get("error") if not sent_live else None))
                    await log_message(
                        lead["id"],
                        f"Automation '{rule['name']}': WhatsApp template <b>{tmpl['name']}</b> "
                        + ("sent via Cloud API" if sent_live else (f"failed — {str(res.get('error'))[:240]}" if wa_status == "failed" else "queued")),
                        extra={"kind": "wa_template", "channel": "whatsapp", "preview": body_prev,
                               "template_name": tmpl.get("name"), "track_id": track["id"],
                               "status": wa_status})
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
                if is_wa:
                    # Only re-queue WhatsApp when it's genuinely pending (API not connected).
                    # A configured-but-failed send (unlinked template / error 131047) is
                    # already recorded as 'failed' above — don't also show it as pending.
                    if wa_status == "in_queue":
                        await db.outbound_queue.insert_one({
                            "lead_id": lead["id"], "channel": "whatsapp", "template_id": value,
                            "status": "pending_api_credentials", "automation": rule["name"],
                            "created_at": now_utc_str(),
                        })
                else:
                    await db.outbound_queue.insert_one({
                        "lead_id": lead["id"], "channel": "email", "template_id": value,
                        "status": "pending_api_credentials", "automation": rule["name"],
                        "created_at": now_utc_str(),
                    })
    if updates:
        await db.leads.update_one({"id": lead["id"]}, {"$set": updates})
        lead.update(updates)
        await log_message(lead["id"], f"Automation '{rule['name']}' applied: {', '.join(updates.keys())}")



# Keep hard references so fire-and-forget tasks aren't garbage-collected mid-flight.
_bg_tasks: set = set()


def schedule_automations(trigger: str, lead: dict, extra: dict = None):
    """Run on_create/on_update automations in the BACKGROUND so an ingestion request
    (Ozonetel CDR / website / Meta webhook) returns immediately and releases its pooled DB
    connection, instead of holding it while an automation makes an external WhatsApp/email
    send (which contributed to the 150s CDR requests → pool exhaustion → /api/leads 504)."""
    async def _safe():
        try:
            await run_automations(trigger, lead, extra)
        except Exception as e:  # never let a background automation crash silently-hard
            logger.warning(f"bg automation '{trigger}' for lead {lead.get('id')} failed: {str(e)[:160]}")
        finally:
            _bg_tasks.discard(t)
    t = asyncio.ensure_future(_safe())
    _bg_tasks.add(t)
    return t
