"""
Odoo -> HomeIVF CRM full data migration.
Resumable: progress checkpointed in `migration_status` collection.
Run: cd /app/backend && nohup python migration/odoo_migrate.py > /var/log/odoo_migration.log 2>&1 &
"""
import os
import re
import sys
import time
import traceback
import xmlrpc.client
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import bcrypt
from pymongo import MongoClient, UpdateOne

ODOO_URL = os.environ["ODOO_URL"]
ODOO_DB = os.environ["ODOO_DB"]
ODOO_LOGIN = os.environ["ODOO_LOGIN"]
ODOO_PASSWORD = os.environ["ODOO_PASSWORD"]
DEFAULT_USER_PASSWORD = os.environ["DEFAULT_USER_PASSWORD"]

mongo = MongoClient(os.environ["MONGO_URL"])
db = mongo[os.environ["DB_NAME"]]

common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
UID = common.authenticate(ODOO_DB, ODOO_LOGIN, ODOO_PASSWORD, {})
models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

IST = timedelta(hours=5, minutes=30)


def call(model, method, *args, retries=5, **kwargs):
    for attempt in range(retries):
        try:
            return models.execute_kw(ODOO_DB, UID, ODOO_PASSWORD, model, method, list(args), kwargs)
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 5 * (attempt + 1)
            log(f"  retry {attempt+1} after error: {str(e)[:150]} (waiting {wait}s)")
            time.sleep(wait)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def checkpoint(entity, **kw):
    db.migration_status.update_one({"entity": entity}, {"$set": {"entity": entity, "updated_at": datetime.utcnow().isoformat(), **kw}}, upsert=True)


def get_checkpoint(entity):
    return db.migration_status.find_one({"entity": entity}) or {}


def m2o(val):
    """Odoo many2one [id, name] -> id"""
    return val[0] if isinstance(val, (list, tuple)) and val else None


def m2o_name(val):
    return val[1] if isinstance(val, (list, tuple)) and len(val) > 1 else None


def s(val):
    """Odoo False -> None, else str"""
    if val is False or val is None:
        return None
    return str(val)


def to_ist(utc_str):
    if not utc_str:
        return None
    try:
        return (datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S") + IST).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return utc_str


def phone_digits(val):
    if not val:
        return ""
    return re.sub(r"\D", "", str(val))[-10:]


def coalesce(rec, fields):
    for f in fields:
        v = rec.get(f)
        if v not in (False, None, "", 0):
            if isinstance(v, (list, tuple)):
                return m2o_name(v)
            return str(v)
    return None


# ---------------- Catalogs ----------------

def migrate_catalogs():
    if get_checkpoint("catalogs").get("state") == "done":
        return
    checkpoint("catalogs", state="running")
    specs = [
        ("crm.stage", "stage", ["name", "sequence", "is_won", "fold", "requirements"]),
        ("crm.tag", "tag", ["name", "color"]),
        ("crm.lost.reason", "lost_reason", ["name", "active"]),
        ("utm.source", "utm_source", ["name"]),
        ("utm.medium", "utm_medium", ["name"]),
        ("utm.campaign", "utm_campaign", ["name"]),
        ("mail.activity.type", "activity_type", ["name", "delay_count", "delay_unit", "category"]),
    ]
    for model, ctype, fields in specs:
        avail = call(model, "fields_get", [], attributes=["type"])
        flds = [f for f in fields if f in avail]
        recs = call(model, "search_read", [], fields=flds)
        ops = []
        max_id = 0
        for r in recs:
            max_id = max(max_id, r["id"])
            doc = {"id": r["id"], "type": ctype, "active": r.get("active", True)}
            for f in flds:
                if f != "active":
                    doc[f] = r[f] if r[f] is not False else None
            ops.append(UpdateOne({"type": ctype, "id": r["id"]}, {"$set": doc}, upsert=True))
        if ops:
            db.catalogs.bulk_write(ops)
        db.counters.update_one({"_id": f"catalog_{ctype}"}, {"$max": {"seq": max_id + 100}}, upsert=True)
        log(f"catalogs/{ctype}: {len(recs)}")
    checkpoint("catalogs", state="done")


# ---------------- Users ----------------

MANAGER_LOGINS = {"kishore@homeivf.com", "minakshi@homeivf.com", "rishabh.choudhary@homeivf.com",
                  "vikas.chauhan@homeivf.com"}


def migrate_users():
    if get_checkpoint("users").get("state") == "done":
        return
    checkpoint("users", state="running")
    recs = call("res.users", "search_read", [["share", "=", False]], fields=["name", "login", "active"])
    default_hash = bcrypt.hashpw(DEFAULT_USER_PASSWORD.encode(), bcrypt.gensalt()).decode()
    ops = []
    for r in recs:
        login = r["login"].strip().lower()
        if login in ("__system__", "default", "public"):
            continue
        role = "caller"
        if r["id"] == 2:
            role = "admin"
        elif login in MANAGER_LOGINS:
            role = "manager"
        existing = db.users.find_one({"email": login})
        if existing and existing.get("id") != r["id"]:
            continue
        ops.append(UpdateOne(
            {"id": r["id"]},
            {"$set": {"id": r["id"], "name": r["name"], "email": login, "role": role,
                      "active": bool(r["active"]), "odoo_user": True},
             "$setOnInsert": {"password_hash": default_hash, "created_at": datetime.utcnow().isoformat()}},
            upsert=True))
    if ops:
        db.users.bulk_write(ops)
    log(f"users: {len(ops)}")
    checkpoint("users", state="done", total=len(ops), done=len(ops))


# ---------------- Templates ----------------

def migrate_templates():
    if get_checkpoint("templates").get("state") == "done":
        return
    checkpoint("templates", state="running")
    avail = call("mail.template", "fields_get", [], attributes=["type"])
    flds = [f for f in ["name", "subject", "body_html", "model", "lang", "email_from"] if f in avail]
    recs = call("mail.template", "search_read", [], fields=flds)
    ops = [UpdateOne({"id": r["id"]}, {"$set": {
        "id": r["id"], "name": s(r.get("name")), "subject": s(r.get("subject")),
        "body": s(r.get("body_html")) or "", "model": s(r.get("model")),
        "lang": s(r.get("lang")), "active": True, "migrated": True}}, upsert=True) for r in recs]
    if ops:
        db.templates_email.bulk_write(ops)
    db.counters.update_one({"_id": "template_email"}, {"$max": {"seq": max([r["id"] for r in recs] or [0]) + 100}}, upsert=True)
    log(f"templates_email: {len(recs)}")

    avail = call("whatsapp.template", "fields_get", [], attributes=["type"])
    flds = [f for f in ["name", "body", "status", "template_type", "lang_code", "header_text", "footer_text", "template_name"] if f in avail]
    recs = call("whatsapp.template", "search_read", [], fields=flds)
    ops = [UpdateOne({"id": r["id"]}, {"$set": {
        "id": r["id"], "name": s(r.get("name")), "body": s(r.get("body")) or "",
        "status": s(r.get("status")), "template_type": s(r.get("template_type")),
        "lang": s(r.get("lang_code")), "header_text": s(r.get("header_text")),
        "footer_text": s(r.get("footer_text")), "active": True, "migrated": True}}, upsert=True) for r in recs]
    if ops:
        db.templates_whatsapp.bulk_write(ops)
    db.counters.update_one({"_id": "template_whatsapp"}, {"$max": {"seq": max([r["id"] for r in recs] or [0]) + 100}}, upsert=True)
    log(f"templates_whatsapp: {len(recs)}")
    checkpoint("templates", state="done")

    # raw odoo saved filters for reference
    filt = call("ir.filters", "search_read", [["model_id", "=", "crm.lead"]])
    db.saved_filters_odoo.delete_many({})
    for f in filt:
        f.pop("_id", None)
    if filt:
        db.saved_filters_odoo.insert_many(filt)
    log(f"saved_filters_odoo: {len(filt)}")


# ---------------- Leads ----------------

COALESCE_MAP = {
    "lead_stage": ["x_studio_lead_stage", "x_studio_lead_stage_1", "x_studio_lead_stage_2",
                   "x_studio_lead_stage_3", "x_studio_lead_stage_4", "x_studio_lead_stage_5",
                   "x_studio_lead_stage_6"],
    "follow_up_date": ["x_studio_follow_up_date", "x_studio_follow_up_date_1", "x_studio_follow_up_date_2",
                       "x_studio_related_field_4t_1ivv4crsa"],
    "follow_up_tag": ["x_studio_follow_up_tag"],
    "appointment_date": ["x_studio_appointment_date"],
    "gender": ["x_studio_gender_6", "x_studio_gender_5", "x_studio_sex", "x_studio_sex_1", "x_studio_sex_2",
               "x_studio_sex_3", "x_studio_gender_7", "x_studio_gender_8", "x_studio_gender",
               "x_studio_gender_1", "x_studio_gender_2", "x_studio_sex_type"],
    "male_age": ["x_studio_male_age", "x_studio_male_age_1", "x_studio_male_age_2", "x_studio_male_age_3",
                 "x_studio_male_age_4", "x_studio_male_age_5", "x_studio_male_age_6"],
    "female_age": ["x_studio_female_age", "x_studio_female_age_1", "x_studio_female_age_2",
                   "x_studio_female_age_3", "x_studio_female_age_4", "x_studio_female_age_5",
                   "x_studio_female_age_6", "x_studio_female_age_7"],
    "age": ["x_studio_age"],
    "spouse_name": ["x_studio_spouse_name"],
    "spouse_age": ["x_studio_spouse_age"],
    "spouse_alternate_no": ["x_studio_spouse_alternate_no"],
    "query": ["x_studio_query", "x_studio_query_1", "x_studio_query_2", "x_studio_query_3", "x_studio_query_info"],
    "remark": ["x_studio_remark_1", "x_studio_char_field_9mt_1j046mc8o", "x_studio_remark_info"],
    "source_lead": ["x_studio_source_lead", "x_studio_source", "x_studio_source_1", "x_studio_source_2",
                    "x_studio_source_3", "x_studio_source_type", "x_studio_source_type_1"],
    "ads_platform": ["x_studio_ads_platform", "x_studio_ads_platform_1"],
    "ads_campaign_name": ["x_studio_ads_campaign_name", "x_studio_ads_campaign_name_1"],
    "ads_name": ["x_studio_ads_name", "x_studio_related_field_5ec_1j182jh8o"],
    "campaign_name": ["x_studio_campaign_name", "x_studio_related_field_7pj_1iv3qbuct"],
    "doctor_name": ["x_studio_doctor_name"],
    "pre_conditions": ["x_studio_pre_conditions_1"],
}

STD_FIELDS = ["name", "contact_name", "partner_id", "phone", "mobile", "email_from", "city",
              "state_id", "country_id", "street", "zip", "stage_id", "tag_ids", "user_id", "team_id",
              "active", "type", "priority", "probability", "lost_reason_id", "description", "referred",
              "source_id", "medium_id", "campaign_id", "date_open", "date_closed",
              "date_last_stage_update", "create_date", "write_date", "create_uid"]


def migrate_leads():
    cp = get_checkpoint("leads")
    if cp.get("state") == "done":
        return
    avail = call("crm.lead", "fields_get", [], attributes=["type"])
    x_fields = [f for f in avail if f.startswith("x_") and avail[f]["type"] not in ("binary", "one2many", "many2many")]
    x_o2m = [f for f in avail if f.startswith("x_") and avail[f]["type"] == "one2many"]
    std = [f for f in STD_FIELDS if f in avail]
    fields = std + x_fields
    domain = [["active", "in", [True, False]]]
    total = call("crm.lead", "search_count", domain)
    last_id = cp.get("last_id", 0)
    done = cp.get("done", 0)
    checkpoint("leads", state="running", total=total, done=done)
    log(f"leads: total={total}, resuming after id={last_id}")
    batch = 500
    while True:
        recs = call("crm.lead", "search_read", domain + [["id", ">", last_id]],
                    fields=fields, limit=batch, order="id asc")
        if not recs:
            break
        ops = []
        for r in recs:
            custom = {}
            for f in x_fields:
                v = r.get(f)
                if v not in (False, None, "", []):
                    custom[f] = list(v) if isinstance(v, (list, tuple)) else v
            doc = {
                "id": r["id"],
                "name": s(r.get("name")),
                "contact_name": s(r.get("contact_name")),
                "partner_id": m2o(r.get("partner_id")),
                "phone": s(r.get("phone")),
                "mobile": s(r.get("mobile")),
                "email_from": s(r.get("email_from")),
                "city": s(r.get("city")),
                "street": s(r.get("street")),
                "zip": s(r.get("zip")),
                "country": m2o_name(r.get("country_id")),
                "stage_id": m2o(r.get("stage_id")),
                "tags": list(r.get("tag_ids") or []),
                "user_id": m2o(r.get("user_id")),
                "team_id": m2o(r.get("team_id")),
                "active": bool(r.get("active")),
                "type": s(r.get("type")),
                "priority": s(r.get("priority")),
                "probability": r.get("probability") if r.get("probability") is not False else None,
                "lost_reason_id": m2o(r.get("lost_reason_id")),
                "description": s(r.get("description")),
                "referred": s(r.get("referred")),
                "source_id": m2o_name(r.get("source_id")),
                "medium_id": m2o_name(r.get("medium_id")),
                "campaign_id": m2o_name(r.get("campaign_id")),
                "date_open": s(r.get("date_open")),
                "date_closed": s(r.get("date_closed")),
                "date_last_stage_update": s(r.get("date_last_stage_update")),
                "create_date": s(r.get("create_date")),
                "create_date_ist": to_ist(s(r.get("create_date"))),
                "write_date": s(r.get("write_date")),
                "create_uid": m2o(r.get("create_uid")),
                "custom": custom,
                "phone_digits": phone_digits(r.get("phone") or r.get("mobile")),
                "migrated": True,
            }
            state_name = coalesce(r, ["x_studio_state_5"]) or m2o_name(r.get("state_id")) or coalesce(
                r, ["x_studio_state", "x_studio_state_1", "x_studio_state_2", "x_studio_state_3",
                    "x_studio_state_4", "x_studio_state_6"])
            doc["state_name"] = state_name
            for target, sources in COALESCE_MAP.items():
                doc[target] = coalesce(r, sources)
            ops.append(UpdateOne({"id": r["id"]}, {"$set": doc}, upsert=True))
        db.leads.bulk_write(ops)
        last_id = recs[-1]["id"]
        done += len(recs)
        checkpoint("leads", state="running", total=total, done=done, last_id=last_id)
        if done % 5000 < batch:
            log(f"leads: {done}/{total}")
    checkpoint("leads", state="done", total=total, done=done, last_id=last_id)
    log(f"leads DONE: {done}")


# ---------------- Lead chatter messages ----------------

def migrate_lead_messages():
    cp = get_checkpoint("lead_messages")
    if cp.get("state") == "done":
        return
    domain = [["model", "=", "crm.lead"], ["body", "!=", ""]]
    total = call("mail.message", "search_count", domain)
    last_id = cp.get("last_id", 0)
    done = cp.get("done", 0)
    checkpoint("lead_messages", state="running", total=total, done=done)
    log(f"lead_messages: total={total}, resuming after id={last_id}")
    fields = ["res_id", "body", "author_id", "date", "message_type", "subtype_id", "subject"]
    batch = 2000
    while True:
        recs = call("mail.message", "search_read", domain + [["id", ">", last_id]],
                    fields=fields, limit=batch, order="id asc")
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
        db.messages.bulk_write(ops)
        last_id = recs[-1]["id"]
        done += len(recs)
        checkpoint("lead_messages", state="running", total=total, done=done, last_id=last_id)
        if done % 20000 < batch:
            log(f"lead_messages: {done}/{total}")
    checkpoint("lead_messages", state="done", total=total, done=done, last_id=last_id)
    log(f"lead_messages DONE: {done}")


# ---------------- Activities ----------------

def migrate_activities():
    if get_checkpoint("activities").get("state") == "done":
        return
    checkpoint("activities", state="running")
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
            "state": "scheduled", "migrated": True,
        }}, upsert=True))
    if ops:
        db.activities.bulk_write(ops)
    log(f"activities: {len(ops)}")
    checkpoint("activities", state="done", total=len(ops), done=len(ops))


# ---------------- WhatsApp channels + messages ----------------

def migrate_wa_channels():
    if get_checkpoint("wa_channels").get("state") == "done":
        return
    checkpoint("wa_channels", state="running")
    avail = call("discuss.channel", "fields_get", [], attributes=["type"])
    flds = [f for f in ["name", "create_date", "write_date", "whatsapp_number", "channel_type"] if f in avail]
    domain = [["channel_type", "=", "whatsapp"]]
    total = call("discuss.channel", "search_count", domain)
    done, last_id = 0, 0
    while True:
        recs = call("discuss.channel", "search_read", domain + [["id", ">", last_id]],
                    fields=flds, limit=1000, order="id asc")
        if not recs:
            break
        ops = []
        for r in recs:
            number = s(r.get("whatsapp_number")) or s(r.get("name"))
            ops.append(UpdateOne({"id": r["id"]}, {"$set": {
                "id": r["id"], "name": s(r.get("name")), "whatsapp_number": s(r.get("whatsapp_number")),
                "phone_digits": phone_digits(number),
                "create_date": s(r.get("create_date")), "last_message_date": s(r.get("write_date")),
                "migrated": True,
            }}, upsert=True))
        db.wa_channels.bulk_write(ops)
        last_id = recs[-1]["id"]
        done += len(recs)
        checkpoint("wa_channels", state="running", total=total, done=done, last_id=last_id)
    checkpoint("wa_channels", state="done", total=total, done=done)
    log(f"wa_channels DONE: {done}")


def migrate_wa_messages():
    cp = get_checkpoint("wa_messages")
    if cp.get("state") == "done":
        return
    wa_ids = set(c["id"] for c in db.wa_channels.find({}, {"id": 1}))
    domain = [["model", "=", "discuss.channel"], ["body", "!=", ""]]
    total = call("mail.message", "search_count", domain)
    last_id = cp.get("last_id", 0)
    done = cp.get("done", 0)
    checkpoint("wa_messages", state="running", total=total, done=done)
    log(f"wa_messages: total={total} (incl non-WA channels), resuming after id={last_id}")
    fields = ["res_id", "body", "author_id", "date", "message_type"]
    batch = 2000
    while True:
        recs = call("mail.message", "search_read", domain + [["id", ">", last_id]],
                    fields=fields, limit=batch, order="id asc")
        if not recs:
            break
        ops = []
        for r in recs:
            if r["res_id"] not in wa_ids:
                continue
            ops.append(UpdateOne({"id": r["id"]}, {"$set": {
                "id": r["id"], "channel_id": r["res_id"], "body": s(r.get("body")) or "",
                "author_id": m2o(r.get("author_id")), "author_name": m2o_name(r.get("author_id")) or "Customer",
                "date": s(r.get("date")), "message_type": s(r.get("message_type")), "migrated": True,
            }}, upsert=True))
        if ops:
            db.wa_messages.bulk_write(ops)
        last_id = recs[-1]["id"]
        done += len(recs)
        checkpoint("wa_messages", state="running", total=total, done=done, last_id=last_id)
        if done % 20000 < batch:
            log(f"wa_messages: {done}/{total}")
    checkpoint("wa_messages", state="done", total=total, done=done, last_id=last_id)
    log(f"wa_messages DONE: {done}")


# ---------------- Contacts ----------------

def migrate_contacts():
    cp = get_checkpoint("contacts")
    if cp.get("state") == "done":
        return
    total = call("res.partner", "search_count", [])
    last_id = cp.get("last_id", 0)
    done = cp.get("done", 0)
    checkpoint("contacts", state="running", total=total, done=done)
    log(f"contacts: total={total}, resuming after id={last_id}")
    fields = ["name", "phone", "mobile", "email", "city", "state_id", "create_date"]
    batch = 2000
    while True:
        recs = call("res.partner", "search_read", [["id", ">", last_id]],
                    fields=fields, limit=batch, order="id asc")
        if not recs:
            break
        ops = []
        for r in recs:
            ops.append(UpdateOne({"id": r["id"]}, {"$set": {
                "id": r["id"], "name": s(r.get("name")), "phone": s(r.get("phone")),
                "mobile": s(r.get("mobile")), "email": s(r.get("email")), "city": s(r.get("city")),
                "state_name": m2o_name(r.get("state_id")), "create_date": s(r.get("create_date")),
                "phone_digits": phone_digits(r.get("phone") or r.get("mobile")), "migrated": True,
            }}, upsert=True))
        db.contacts.bulk_write(ops)
        last_id = recs[-1]["id"]
        done += len(recs)
        checkpoint("contacts", state="running", total=total, done=done, last_id=last_id)
        if done % 20000 < batch:
            log(f"contacts: {done}/{total}")
    checkpoint("contacts", state="done", total=total, done=done, last_id=last_id)
    log(f"contacts DONE: {done}")


if __name__ == "__main__":
    log(f"Migration starting. Odoo UID={UID}")
    steps = [migrate_catalogs, migrate_users, migrate_templates, migrate_leads,
             migrate_activities, migrate_wa_channels, migrate_wa_messages,
             migrate_lead_messages, migrate_contacts]
    for step in steps:
        try:
            step()
        except Exception:
            log(f"ERROR in {step.__name__}:\n{traceback.format_exc()}")
            checkpoint(step.__name__.replace("migrate_", ""), state="error", error=traceback.format_exc()[-500:])
    log("Migration run complete.")
