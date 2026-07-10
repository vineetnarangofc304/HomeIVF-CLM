import os, xmlrpc.client
from dotenv import load_dotenv
load_dotenv()
URL, DB, LOGIN, PWD = os.environ["ODOO_URL"], os.environ["ODOO_DB"], os.environ["ODOO_LOGIN"], os.environ["ODOO_PASSWORD"]
common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common", allow_none=True)
uid = common.authenticate(DB, LOGIN, PWD, {})
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)
def call(model, method, *a, **k):
    return models.execute_kw(DB, uid, PWD, model, method, list(a), k)

# find a Kamlesh Yadav lead
ids = call("crm.lead", "search", [["name", "ilike", "kamlesh yadav"]], limit=5)
print("kamlesh lead ids:", ids)
if ids:
    rec = call("crm.lead", "read", [ids[0]])[0]
    # print only fields with x_studio_lead_stage or tag or stage
    print("\n--- stage_id:", rec.get("stage_id"))
    print("--- tag_ids:", rec.get("tag_ids"))
    print("\n--- ALL x_studio fields that look like stage/tag/status and are set ---")
    for k, v in sorted(rec.items()):
        if v in (False, None, "", []):
            continue
        kl = k.lower()
        if "stage" in kl or "tag" in kl or "status" in kl or "disposition" in kl or "follow" in kl:
            print(f"  {k} = {v!r}")
    # resolve tag names
    if rec.get("tag_ids"):
        tags = call("crm.tag", "read", [rec["tag_ids"]], fields=["id", "name"])
        print("\n--- tag names:", tags)
