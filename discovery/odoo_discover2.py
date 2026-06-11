"""Odoo deep discovery v2: resilient field fetching"""
import xmlrpc.client
import json, os

URL = "https://homeivf.odoo.com"
DB = "homeivf"
PASSWORD = "Home25!@#123"
LOGIN = "homeivfofficial@gmail.com"

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid = common.authenticate(DB, LOGIN, PASSWORD, {})
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def call(model, method, *args, **kwargs):
    return models.execute_kw(DB, uid, PASSWORD, model, method, list(args), kwargs)

OUT = "/app/discovery/out"
os.makedirs(OUT, exist_ok=True)

def dump(name, data):
    with open(f"{OUT}/{name}.json", "w") as f:
        json.dump(data, f, indent=1, default=str)
    print(name, "->", len(data) if isinstance(data, list) else "ok")

def safe_read(model, wanted, name, domain=None):
    try:
        avail = call(model, "fields_get", [], attributes=["type"])
        flds = [f for f in wanted if f in avail]
        d = call(model, "search_read", domain or [], fields=flds)
        dump(name, d)
        return d
    except Exception as e:
        print(name, "ERR", str(e)[:200])
        return []

safe_read("crm.stage", ["name", "sequence", "is_won", "fold", "requirements", "team_ids"], "stages")
safe_read("crm.lost.reason", ["name", "active"], "lost_reasons")
safe_read("crm.tag", ["name", "color"], "tags")
safe_read("crm.team", ["name", "member_ids", "user_id", "active", "assignment_domain"], "teams")
safe_read("res.users", ["name", "login", "active", "group_ids", "groups_id", "share"], "users", [["share", "=", False]])
safe_read("mail.activity.type", ["name", "delay_count", "delay_unit", "category", "res_model"], "activity_types")
safe_read("utm.source", ["name"], "utm_sources")
safe_read("utm.medium", ["name"], "utm_mediums")
safe_read("utm.campaign", ["name"], "utm_campaigns")
safe_read("ir.filters", ["name", "domain", "context", "sort", "user_id", "is_default", "model_id"], "crm_saved_filters", [["model_id", "=", "crm.lead"]])
safe_read("mail.template", ["name", "model", "subject", "email_from", "use_default_to", "active"], "mail_templates")
safe_read("ir.model", ["model", "name"], "custom_models", [["model", "like", "x_%"]])

for m in ["crm.lead", "res.partner", "mail.message", "mail.activity", "mail.template", "discuss.channel", "crm.lead.scoring.frequency"]:
    try:
        c = call(m, "search_count", [])
        print("COUNT", m, c)
    except Exception as e:
        print("COUNT", m, "ERR", str(e)[:100])

# crm.lead counts active vs inactive (lost leads are active=False)
try:
    print("COUNT crm.lead all(incl lost):", call("crm.lead", "search_count", [["active", "in", [True, False]]]))
except Exception as e:
    print("ERR", e)
