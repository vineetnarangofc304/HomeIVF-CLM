"""
Odoo -> HomeIVF CRM DELTA SYNC.
Fetches records created/updated in Odoo since a given timestamp and upserts them.
Progress + results are tracked in the `sync_runs` collection (run_id).
Run: cd /app/backend && python migration/odoo_sync.py --run-id 1 --since "2026-06-11 12:00:00" --until "2026-06-12 09:00:00"
A since of "1970-01-01 00:00:00" performs a FULL import (used for fresh/production databases).
"""
import argparse
import time
import traceback
from datetime import datetime

from pymongo import UpdateOne
from pymongo.errors import AutoReconnect, NetworkTimeout, ConnectionFailure

from odoo_migrate import (  # noqa: E402  (same directory)
    DEFAULT_USER_PASSWORD, MANAGER_LOGINS, call, checkpoint, db, get_checkpoint,
    get_lead_fields, log, m2o, m2o_name, phone_digits, s, to_ist, transform_lead,
)
import bcrypt


def now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


class SyncRun:
    def __init__(self, run_id):
        self.run_id = run_id
        self.results = {}

    def update(self, **kw):
        db.sync_runs.update_one({"run_id": self.run_id}, {"$set": kw}, upsert=True)

    def record(self, entity, new=0, updated=0):
        self.results[entity] = {"new": new, "updated": updated}
        self.update(progress=self.results, current_entity=entity)
        log(f"{entity}: +{new} new, {updated} updated")


def bulk(coll, ops):
    """Returns (inserted, updated). Retries on transient MongoDB network drops
    (e.g. `write_command ... receive_message` connection resets seen on large
    writes in managed/production clusters). ordered=False so a single bad op
    can't abort the whole batch."""
    if not ops:
        return 0, 0
    for attempt in range(4):
        try:
            res = coll.bulk_write(ops, ordered=False)
            inserted = res.upserted_count
            return inserted, len(ops) - inserted
        except (AutoReconnect, NetworkTimeout, ConnectionFailure) as e:
            if attempt == 3:
                raise
            wait = 3 * (attempt + 1)
            log(f"  bulk_write transient error on {coll.name}: {str(e)[:120]} — retry {attempt+1} in {wait}s")
            time.sleep(wait)


def sync_catalogs(run):
    specs = [
        ("crm.stage", "stage", ["name", "sequence", "is_won", "fold"]),
        ("crm.tag", "tag", ["name", "color"]),
        ("crm.lost.reason", "lost_reason", ["name", "active"]),
        ("utm.source", "utm_source", ["name"]),
        ("utm.medium", "utm_medium", ["name"]),
        ("utm.campaign", "utm_campaign", ["name"]),
        ("mail.activity.type", "activity_type", ["name", "delay_count", "delay_unit", "category"]),
    ]
    new = upd = 0
    for model, ctype, fields in specs:
        avail = call(model, "fields_get", [], attributes=["type"])
        flds = [f for f in fields if f in avail]
        recs = call(model, "search_read", [], fields=flds)
        ops = []
        for r in recs:
            doc = {"id": r["id"], "type": ctype, "active": r.get("active", True)}
            for f in flds:
                if f != "active":
                    doc[f] = r[f] if r[f] is not False else None
            ops.append(UpdateOne({"type": ctype, "id": r["id"]}, {"$set": doc}, upsert=True))
        n, u = bulk(db.catalogs, ops)
        new += n
        upd += u
        if recs:
            db.counters.update_one({"_id": f"catalog_{ctype}"}, {"$max": {"seq": max(r["id"] for r in recs) + 100}}, upsert=True)
    # refresh lead field labels (used by Meta/Google Q&A panel)
    fields = call("crm.lead", "fields_get", [], attributes=["string", "type", "selection"])
    labels = {k: {"label": v.get("string") or k, "type": v.get("type"),
                  "selection": [sel[0] for sel in (v.get("selection") or [])]}
              for k, v in fields.items() if k.startswith("x_")}
    db.settings.update_one({"key": "lead_field_labels"}, {"$set": {"key": "lead_field_labels", "fields": labels}}, upsert=True)
    run.record("catalogs", new, upd)


def sync_users(run):
    """Insert-only: never overwrite roles/passwords/names managed in the CRM."""
    recs = call("res.users", "search_read", [["share", "=", False]], fields=["name", "login", "active"])
    default_hash = bcrypt.hashpw(DEFAULT_USER_PASSWORD.encode(), bcrypt.gensalt()).decode()
    new = 0
    for r in recs:
        login = r["login"].strip().lower()
        if login in ("__system__", "default", "public"):
            continue
        if db.users.find_one({"$or": [{"id": r["id"]}, {"email": login}]}):
            continue
        role = "admin" if r["id"] == 2 else ("manager" if login in MANAGER_LOGINS else "caller")
        db.users.insert_one({"id": r["id"], "name": r["name"], "email": login, "role": role,
                             "active": bool(r["active"]), "odoo_user": True,
                             "password_hash": default_hash, "created_at": now_str()})
        new += 1
    run.record("users", new, 0)


def sync_templates(run):
    """Insert-only: CRM-side template edits are preserved."""
    new = 0
    avail = call("mail.template", "fields_get", [], attributes=["type"])
    flds = [f for f in ["name", "subject", "body_html", "model", "lang"] if f in avail]
    for r in call("mail.template", "search_read", [], fields=flds):
        if not db.templates_email.find_one({"id": r["id"]}):
            db.templates_email.insert_one({"id": r["id"], "name": s(r.get("name")), "subject": s(r.get("subject")),
                                           "body": s(r.get("body_html")) or "", "model": s(r.get("model")),
                                           "lang": s(r.get("lang")), "active": True, "migrated": True})
            new += 1
    avail = call("whatsapp.template", "fields_get", [], attributes=["type"])
    flds = [f for f in ["name", "body", "status", "template_type", "lang_code", "header_text", "footer_text"] if f in avail]
    for r in call("whatsapp.template", "search_read", [], fields=flds):
        if not db.templates_whatsapp.find_one({"id": r["id"]}):
            db.templates_whatsapp.insert_one({"id": r["id"], "name": s(r.get("name")), "body": s(r.get("body")) or "",
                                              "status": s(r.get("status")), "template_type": s(r.get("template_type")),
                                              "lang": s(r.get("lang_code")), "header_text": s(r.get("header_text")),
                                              "footer_text": s(r.get("footer_text")), "active": True, "migrated": True})
            new += 1
    run.record("templates", new, 0)


def _next_id_sync(name):
    doc = db.counters.find_one_and_update(
        {"_id": name}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
    return doc["seq"]


def _ensure_followups(lead_docs):
    """Case 2 — mirror each lead's Odoo follow-up date into a real follow_ups entry
    so it shows in the Follow-ups list + reminders. Idempotent: keeps exactly ONE
    odoo-sourced entry per lead, updating its date if Odoo's follow-up date changes.
    Never touches manually-created (non-odoo) follow-ups."""
    created = updated = 0
    for t in lead_docs:
        raw = t.get("follow_up_date")
        if not raw:
            continue
        date = str(raw)[:10]
        lead_id = t["id"]
        tag = t.get("follow_up_tag")
        existing = db.follow_ups.find_one({"lead_id": lead_id, "source": "odoo"})
        if existing:
            if existing.get("follow_up_date") != date or existing.get("follow_up_tag") != tag:
                db.follow_ups.update_one({"id": existing["id"]},
                    {"$set": {"follow_up_date": date, "follow_up_tag": tag}})
                updated += 1
        else:
            db.follow_ups.insert_one({
                "id": _next_id_sync("follow_up"), "lead_id": lead_id, "follow_up_date": date,
                "follow_up_time": None, "follow_up_tag": tag,
                "note": "Imported from Odoo follow-up date", "status": None, "source": "odoo",
                "created_by": None, "created_by_name": "Odoo Sync", "created_at": now_str()})
            created += 1
    return created, updated


def _backfill_followups(run):
    """One-time backfill: create follow_ups entries for ALL already-synced leads that
    have an Odoo follow-up date but no odoo follow_ups entry yet. Uses a reserved id
    block + insert_many for speed."""
    have = set(db.follow_ups.distinct("lead_id", {"source": "odoo"}))
    to_insert = [l for l in db.leads.find(
        {"migrated": True, "follow_up_date": {"$nin": [None, ""]}},
        {"id": 1, "follow_up_date": 1, "follow_up_tag": 1}) if l["id"] not in have]
    if not to_insert:
        run.record("followups_backfill", 0, 0)
        return
    n = len(to_insert)
    blk = db.counters.find_one_and_update(
        {"_id": "follow_up"}, {"$inc": {"seq": n}}, upsert=True, return_document=True)
    start = blk["seq"] - n + 1
    now = now_str()
    docs = [{
        "id": start + i, "lead_id": l["id"], "follow_up_date": str(l["follow_up_date"])[:10],
        "follow_up_time": None, "follow_up_tag": l.get("follow_up_tag"),
        "note": "Imported from Odoo follow-up date", "status": None, "source": "odoo",
        "created_by": None, "created_by_name": "Odoo Sync", "created_at": now}
        for i, l in enumerate(to_insert)]
    done = 0
    for j in range(0, len(docs), 2000):
        chunk = docs[j:j + 2000]
        db.follow_ups.insert_many(chunk, ordered=False)
        done += len(chunk)
        run.record("followups_backfill", done, 0)
    run.record("followups_backfill", n, 0)


def sync_leads(run, since):
    fields, x_fields = get_lead_fields()
    domain = [["active", "in", [True, False]], ["write_date", ">=", since]]
    total = call("crm.lead", "search_count", domain)
    log(f"leads delta: {total} records changed in Odoo since {since}")
    new = upd = 0
    last_id = 0
    while True:
        recs = call("crm.lead", "search_read", domain + [["id", ">", last_id]],
                    fields=fields, limit=500, order="id asc")
        if not recs:
            break
        transformed = [transform_lead(r, x_fields) for r in recs]
        ops = [UpdateOne({"id": t["id"]}, {"$set": t}, upsert=True) for t in transformed]
        n, u = bulk(db.leads, ops)
        new += n
        upd += u
        _ensure_followups([t for t in transformed if t.get("follow_up_date")])
        last_id = recs[-1]["id"]
        run.record("leads", new, upd)
    cp = get_checkpoint("leads")
    checkpoint("leads", state="done", last_id=max(cp.get("last_id", 0), last_id), done=db.leads.count_documents({"migrated": True}))
    run.record("leads", new, upd)


def sync_lead_messages(run):
    cp = get_checkpoint("lead_messages")
    last_id = cp.get("last_id", 0)
    domain = [["model", "=", "crm.lead"], ["body", "!=", ""], ["id", ">", last_id]]
    new = 0
    while True:
        recs = call("mail.message", "search_read", domain, fields=["res_id", "body", "author_id", "date", "message_type", "subtype_id", "subject"], limit=500, order="id asc")
        if not recs:
            break
        ops = []
        for r in recs:
            subtype = (m2o_name(r.get("subtype_id")) or "").lower()
            ops.append(UpdateOne({"id": r["id"]}, {"$set": {
                "id": r["id"], "lead_id": r["res_id"], "body": s(r.get("body")) or "",
                "author_id": m2o(r.get("author_id")), "author_name": m2o_name(r.get("author_id")) or "System",
                "date": s(r.get("date")), "message_type": s(r.get("message_type")),
                "subtype": "note" if "note" in subtype else ("comment" if r.get("message_type") == "comment" else "tracking"),
                "subject": s(r.get("subject")), "migrated": True,
            }}, upsert=True))
        n, _ = bulk(db.messages, ops)
        new += n
        last_id = recs[-1]["id"]
        domain[-1] = ["id", ">", last_id]
        checkpoint("lead_messages", last_id=last_id)
        run.record("lead_messages", new, 0)
    run.record("lead_messages", new, 0)


def sync_wa(run, since):
    avail = call("discuss.channel", "fields_get", [], attributes=["type"])
    flds = [f for f in ["name", "create_date", "write_date", "whatsapp_number"] if f in avail]
    recs = call("discuss.channel", "search_read",
                [["channel_type", "=", "whatsapp"], ["write_date", ">=", since]], fields=flds)
    ops = []
    for r in recs:
        number = s(r.get("whatsapp_number")) or s(r.get("name"))
        ops.append(UpdateOne({"id": r["id"]}, {"$set": {
            "id": r["id"], "name": s(r.get("name")), "whatsapp_number": s(r.get("whatsapp_number")),
            "phone_digits": phone_digits(number), "create_date": s(r.get("create_date")),
            "last_message_date": s(r.get("write_date")), "migrated": True}}, upsert=True))
    n, u = bulk(db.wa_channels, ops)
    run.record("wa_channels", n, u)

    wa_ids = set(c["id"] for c in db.wa_channels.find({}, {"id": 1}))
    cp = get_checkpoint("wa_messages")
    last_id = cp.get("last_id", 0)
    new = 0
    while True:
        recs = call("mail.message", "search_read",
                    [["model", "=", "discuss.channel"], ["body", "!=", ""], ["id", ">", last_id]],
                    fields=["res_id", "body", "author_id", "date", "message_type"], limit=500, order="id asc")
        if not recs:
            break
        ops = []
        for r in recs:
            if r["res_id"] not in wa_ids:
                continue
            ops.append(UpdateOne({"id": r["id"]}, {"$set": {
                "id": r["id"], "channel_id": r["res_id"], "body": s(r.get("body")) or "",
                "author_id": m2o(r.get("author_id")), "author_name": m2o_name(r.get("author_id")) or "Customer",
                "date": s(r.get("date")), "message_type": s(r.get("message_type")), "migrated": True}}, upsert=True))
        n, _ = bulk(db.wa_messages, ops)
        new += n
        last_id = recs[-1]["id"]
        checkpoint("wa_messages", last_id=last_id)
        run.record("wa_messages", new, 0)
    run.record("wa_messages", new, 0)


def sync_contacts(run):
    cp = get_checkpoint("contacts")
    last_id = cp.get("last_id", 0)
    new = 0
    while True:
        recs = call("res.partner", "search_read", [["id", ">", last_id]],
                    fields=["name", "phone", "email", "city", "state_id", "create_date"], limit=2000, order="id asc")
        if not recs:
            break
        ops = [UpdateOne({"id": r["id"]}, {"$set": {
            "id": r["id"], "name": s(r.get("name")), "phone": s(r.get("phone")),
            "email": s(r.get("email")), "city": s(r.get("city")),
            "state_name": m2o_name(r.get("state_id")), "create_date": s(r.get("create_date")),
            "phone_digits": phone_digits(r.get("phone")), "migrated": True}}, upsert=True) for r in recs]
        n, _ = bulk(db.contacts, ops)
        new += n
        last_id = recs[-1]["id"]
        checkpoint("contacts", last_id=last_id)
        run.record("contacts", new, 0)
    run.record("contacts", new, 0)


def sync_activities(run):
    recs = call("mail.activity", "search_read", [["res_model", "=", "crm.lead"]],
                fields=["res_id", "activity_type_id", "summary", "note", "date_deadline", "user_id", "state"])
    ops = []
    for r in recs:
        lead = db.leads.find_one({"id": r["res_id"]}, {"name": 1})
        ops.append(UpdateOne({"id": r["id"]}, {"$set": {
            "id": r["id"], "lead_id": r["res_id"], "lead_name": (lead or {}).get("name"),
            "type_name": m2o_name(r.get("activity_type_id")) or "To-Do",
            "summary": s(r.get("summary")), "note": s(r.get("note")),
            "date_deadline": s(r.get("date_deadline")), "user_id": m2o(r.get("user_id")),
            "state": "scheduled", "migrated": True}}, upsert=True))
    n, u = bulk(db.activities, ops)
    run.record("open_activities", n, u)


def run_sync(run_id, since, until=None):
    """Run a full delta sync in-process (callable from the API in a background thread)."""
    run = SyncRun(run_id)
    until = until or now_str()
    run.update(status="running", since=since, until=until, started_at=now_str())
    log(f"SYNC run {run_id}: since={since} until={until}")
    try:
        sync_catalogs(run)
        sync_users(run)
        sync_templates(run)
        sync_leads(run, since)
        sync_lead_messages(run)
        sync_wa(run, since)
        sync_contacts(run)
        sync_activities(run)
        if not db.settings.find_one({"key": "followups_backfilled"}):
            _backfill_followups(run)
            db.settings.update_one({"key": "followups_backfilled"},
                {"$set": {"key": "followups_backfilled", "done_at": now_str()}}, upsert=True)
        totals = {
            "leads": db.leads.estimated_document_count(),
            "lead_messages": db.messages.estimated_document_count(),
            "wa_channels": db.wa_channels.estimated_document_count(),
            "wa_messages": db.wa_messages.estimated_document_count(),
            "contacts": db.contacts.estimated_document_count(),
            "users": db.users.estimated_document_count(),
        }
        finished = now_str()
        run.update(status="done", finished_at=finished, results=run.results, totals=totals)
        db.settings.update_one({"key": "last_sync"}, {"$set": {
            "key": "last_sync", "since": since, "until": until, "finished_at": finished,
            "results": run.results, "totals": totals, "run_id": run_id}}, upsert=True)
        log("SYNC complete.")
        return {"status": "done", "totals": totals}
    except Exception:
        err = traceback.format_exc()
        log(f"SYNC ERROR:\n{err}")
        run.update(status="error", error=err[-800:], finished_at=now_str())
        return {"status": "error", "error": err[-800:]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--until", default=None)
    args = parser.parse_args()
    run_sync(args.run_id, args.since, args.until)
