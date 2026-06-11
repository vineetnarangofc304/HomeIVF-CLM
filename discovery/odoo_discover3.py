"""Odoo deep discovery v3: field usage, samples, automations, whatsapp, calls"""
import xmlrpc.client
import json, os
from collections import Counter

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

def dump(name, data):
    with open(f"{OUT}/{name}.json", "w") as f:
        json.dump(data, f, indent=1, default=str)
    print(name, "->", len(data) if isinstance(data, list) else "ok")

# 1. Saved filters properly
filt = call("ir.filters", "search_read", [["model_id", "=", "crm.lead"]])
dump("crm_saved_filters_full", filt)

# 2. Sample 300 recent leads, all fields -> usage stats
flds = call("crm.lead", "fields_get", [], attributes=["type", "string"])
storable = [k for k, v in flds.items() if v["type"] not in ("binary",)]
sample = call("crm.lead", "search_read", [["active", "in", [True, False]]],
              fields=storable, limit=300, order="id desc")
dump("lead_sample", sample[:20])
usage = Counter()
for rec in sample:
    for k, v in rec.items():
        if v not in (False, None, "", [], 0):
            usage[k] += 1
dump("lead_field_usage", dict(usage.most_common()))

# 3. Custom line models
for m in ["x_crm_lead_line_7cae5", "x_prescription", "x_tag", "x_tags"]:
    try:
        ff = call(m, "fields_get", [], attributes=["string", "type", "relation"])
        recs = call(m, "search_read", [], limit=20)
        cnt = call(m, "search_count", [])
        dump(f"model_{m}", {"count": cnt, "fields": ff, "sample": recs[:10]})
    except Exception as e:
        print(m, "ERR", str(e)[:150])

# 4. Automations
try:
    autos = call("base.automation", "search_read", [], fields=["name", "model_id", "trigger", "filter_domain", "active"])
    dump("automations", autos)
except Exception as e:
    print("automations ERR", str(e)[:150])

# 5. WhatsApp templates
try:
    wa = call("whatsapp.template", "search_read", [], fields=["name", "body", "status", "template_type", "model"])
    dump("whatsapp_templates", wa)
except Exception as e:
    print("wa ERR", str(e)[:150])

# 6. MyOperator / voip models
mo_models = call("ir.model", "search_read", [["model", "like", "%operator%"]], fields=["model", "name"])
dump("myoperator_models", mo_models)
voip = call("ir.model", "search_read", [["model", "like", "voip%"]], fields=["model", "name"])
dump("voip_models", voip)
try:
    calls_cnt = call("voip.call", "search_count", [])
    print("voip.call count:", calls_cnt)
    vc = call("voip.call", "search_read", [], limit=10, order="id desc")
    dump("voip_call_sample", vc)
except Exception as e:
    print("voip.call ERR", str(e)[:150])

# 7. Discuss channel types
ch = call("discuss.channel", "read_group", [], ["channel_type"], ["channel_type"])
print("channel types:", ch)

# 8. Lead counts by stage / by user / created per month (recent)
by_stage = call("crm.lead", "read_group", [["active", "in", [True, False]]], ["stage_id"], ["stage_id"])
dump("leads_by_stage", by_stage)
by_user = call("crm.lead", "read_group", [], ["user_id"], ["user_id"])
dump("leads_by_user", by_user)
