"""Odoo deep discovery: dump structure to JSON files"""
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

# 1. Installed modules
mods = call("ir.module.module", "search_read", [["state", "=", "installed"]], fields=["name", "shortdesc"])
dump("modules", mods)

# 2. crm.lead fields
fields = call("crm.lead", "fields_get", [], attributes=["string", "type", "selection", "relation", "required", "readonly", "store", "help"])
dump("crm_lead_fields", fields)

# 3. Stages
stages = call("crm.stage", "search_read", [], fields=["name", "sequence", "is_won", "fold", "team_id", "requirements"])
dump("stages", stages)

# 4. Lost reasons
lost = call("crm.lost.reason", "search_read", [], fields=["name", "active"])
dump("lost_reasons", lost)

# 5. Tags
tags = call("crm.tag", "search_read", [], fields=["name", "color"])
dump("tags", tags)

# 6. Teams
teams = call("crm.team", "search_read", [], fields=["name", "member_ids", "user_id", "active"])
dump("teams", teams)

# 7. Users
users = call("res.users", "search_read", [], fields=["name", "login", "active", "groups_id"])
dump("users", users)

# 8. Activity types
act_types = call("mail.activity.type", "search_read", [], fields=["name", "delay_count", "delay_unit", "category", "res_model"])
dump("activity_types", act_types)

# 9. UTM
for m, n in [("utm.source", "utm_sources"), ("utm.medium", "utm_mediums"), ("utm.campaign", "utm_campaigns")]:
    try:
        d = call(m, "search_read", [], fields=["name"])
        dump(n, d)
    except Exception as e:
        print(n, "ERR", e)

# 10. Saved filters on crm.lead
filt = call("ir.filters", "search_read", [["model_id", "=", "crm.lead"]], fields=["name", "domain", "context", "sort", "user_id", "is_default"])
dump("crm_saved_filters", filt)

# 11. Record counts
for m in ["crm.lead", "res.partner", "mail.message", "mail.activity", "mail.template", "discuss.channel"]:
    try:
        c = call(m, "search_count", [])
        print("COUNT", m, c)
    except Exception as e:
        print("COUNT", m, "ERR", e)

# 12. Lead form builder / custom models (x_ models)
custom_models = call("ir.model", "search_read", [["model", "like", "x_%"]], fields=["model", "name"])
dump("custom_models", custom_models)
