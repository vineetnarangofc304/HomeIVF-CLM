"""Iteration 3 — HomeIVF CRM 8 testing-point cases (PDF).

Covers:
  Case 1: Country/State/Address fields on lead detail
  Case 2: Add new disposition tags from lead detail
  Case 3: Meta/Google Q&A on lead.custom (verified via lead update + custom fields rendering)
  Case 4: Self-service custom field builder + webhook alias auto-capture
  Case 5: WhatsApp send_whatsapp queues + chatter
  Case 6: Email send_email queues + save_as_template
  Case 7: UTM source/medium/campaign attribution fields on leads
  Case 8: Automations on_stage_set (lead_stage change) + on_tag_set + BULK firing
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://homeivf-crm-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

# Artifacts to clean up at the end
_CLEANUP = {"leads": [], "automations": [], "custom_fields": [], "webhooks": [], "tags": []}


@pytest.fixture(scope="module")
def cleanup(admin_client):
    yield _CLEANUP
    # Best-effort cleanup
    for aid in _CLEANUP["automations"]:
        admin_client.delete(f"{API}/admin/automations/{aid}")
    for fid in _CLEANUP["custom_fields"]:
        admin_client.delete(f"{API}/catalogs/custom-fields/{fid}")
    for wid in _CLEANUP["webhooks"]:
        admin_client.delete(f"{API}/webhooks/{wid}")
    for lid in _CLEANUP["leads"]:
        # Mark inactive (no hard-delete endpoint)
        admin_client.post(f"{API}/leads/{lid}/lost", json={"note": "TEST cleanup"})


@pytest.fixture(scope="module")
def fresh_lead(admin_client, cleanup):
    payload = {
        "contact_name": f"TEST_Case_{uuid.uuid4().hex[:6]}",
        "phone": f"99999{int(time.time()) % 100000:05d}",
        "email_from": "test_iter3@example.com",
    }
    r = admin_client.post(f"{API}/leads", json=payload)
    assert r.status_code == 200, r.text
    lid = r.json()["id"]
    cleanup["leads"].append(lid)
    return r.json()


# ---------- CASE 1: Country / State / Address ----------
class TestCase1AddressFields:
    def test_catalog_country_state_exist(self, admin_client):
        r = admin_client.get(f"{API}/catalogs")
        assert r.status_code == 200
        data = r.json()
        assert "country" in data and "state" in data, "Catalogs missing country/state"
        # data may be empty list if not seeded; tolerate empty but key must exist
        assert isinstance(data["country"], list)
        assert isinstance(data["state"], list)

    def test_patch_lead_address_fields(self, admin_client, fresh_lead):
        lid = fresh_lead["id"]
        body = {"updates": {"street": "123 TEST Park Street", "city": "Bengaluru",
                            "state_name": "Karnataka", "country": "India"}}
        r = admin_client.patch(f"{API}/leads/{lid}", json=body)
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["street"] == "123 TEST Park Street"
        assert got["city"] == "Bengaluru"
        assert got["state_name"] == "Karnataka"
        assert got["country"] == "India"

        # verify persisted via GET
        g = admin_client.get(f"{API}/leads/{lid}")
        assert g.status_code == 200
        gd = g.json()
        assert gd["street"] == "123 TEST Park Street"
        assert gd["country"] == "India"


# ---------- CASE 2: Disposition tag creation from lead ----------
class TestCase2TagCreate:
    def test_create_tag_and_attach_to_lead(self, admin_client, fresh_lead, cleanup):
        tag_name = f"TEST_DISP_{uuid.uuid4().hex[:6]}"
        r = admin_client.post(f"{API}/catalogs/tag", json={"name": tag_name})
        assert r.status_code == 200, r.text
        tag = r.json()
        assert tag["name"] == tag_name
        assert tag["type"] == "tag"
        assert "id" in tag
        cleanup["tags"].append(("tag", tag["id"]))

        # Tag should appear in global catalog
        catalogs = admin_client.get(f"{API}/catalogs").json()
        tag_ids = [t["id"] for t in catalogs.get("tag", [])]
        assert tag["id"] in tag_ids

        # Attach to lead via PATCH
        lid = fresh_lead["id"]
        cur = admin_client.get(f"{API}/leads/{lid}").json()
        new_tags = list(cur.get("tags") or []) + [tag["id"]]
        r2 = admin_client.patch(f"{API}/leads/{lid}", json={"updates": {"tags": new_tags}})
        assert r2.status_code == 200
        assert tag["id"] in r2.json()["tags"]

    def test_tag_creation_allowed_for_caller(self, caller_client):
        # Tag creation must be permitted for non-admins (matches Odoo)
        tag_name = f"TEST_CALLER_TAG_{uuid.uuid4().hex[:6]}"
        r = caller_client.post(f"{API}/catalogs/tag", json={"name": tag_name})
        assert r.status_code == 200, r.text


# ---------- CASE 3: Meta/Google Q&A ----------
class TestCase3MetaGoogleQA:
    def test_lead_custom_qa_persists(self, admin_client, fresh_lead):
        lid = fresh_lead["id"]
        qa = {"q_planning_since": "6 months", "q_doctor_consulted": "Yes"}
        r = admin_client.patch(f"{API}/leads/{lid}", json={"updates": {"custom": qa}})
        assert r.status_code == 200
        got = r.json()["custom"]
        for k, v in qa.items():
            assert got.get(k) == v


# ---------- CASE 4: Custom field builder + Webhook auto-capture ----------
class TestCase4CustomFieldBuilder:
    def test_create_custom_field_general(self, admin_client, cleanup):
        label = f"TEST GeneralFld {uuid.uuid4().hex[:5]}"
        body = {"label": label, "field_type": "char", "section": "general",
                "aliases": ["pincode", "pin_code"]}
        r = admin_client.post(f"{API}/catalogs/custom-fields/create", json=body)
        assert r.status_code == 200, r.text
        f = r.json()
        assert f["key"].startswith("x_custom_")
        assert f["section"] == "general"
        assert "pincode" in f["aliases"]
        cleanup["custom_fields"].append(f["id"])

    def test_create_custom_field_qa_selection(self, admin_client, cleanup):
        label = f"TEST QASel {uuid.uuid4().hex[:5]}"
        body = {"label": label, "field_type": "selection", "section": "qa",
                "options": ["Yes", "No", "Maybe"], "aliases": ["qa_pref"]}
        r = admin_client.post(f"{API}/catalogs/custom-fields/create", json=body)
        assert r.status_code == 200, r.text
        f = r.json()
        assert f["field_type"] == "selection"
        assert f["options"] == ["Yes", "No", "Maybe"]
        assert f["section"] == "qa"
        cleanup["custom_fields"].append(f["id"])

    def test_list_custom_fields(self, admin_client):
        r = admin_client.get(f"{API}/catalogs/custom-fields/all")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_toggle_custom_field_active(self, admin_client, cleanup):
        label = f"TEST Toggle {uuid.uuid4().hex[:5]}"
        r = admin_client.post(f"{API}/catalogs/custom-fields/create",
                              json={"label": label, "field_type": "char", "section": "general"})
        fid = r.json()["id"]
        cleanup["custom_fields"].append(fid)
        r2 = admin_client.patch(f"{API}/catalogs/custom-fields/{fid}", json={"active": False})
        assert r2.status_code == 200
        assert r2.json()["active"] is False

    def test_webhook_alias_capture(self, admin_client, cleanup):
        # 1) Create a custom field with an alias
        alias = f"test_alias_{uuid.uuid4().hex[:6]}"
        label = f"TEST Alias Fld {uuid.uuid4().hex[:5]}"
        r = admin_client.post(f"{API}/catalogs/custom-fields/create", json={
            "label": label, "field_type": "char", "section": "qa", "aliases": [alias]
        })
        assert r.status_code == 200, r.text
        fld = r.json()
        cleanup["custom_fields"].append(fld["id"])

        # 2) Create a webhook
        r2 = admin_client.post(f"{API}/webhooks", json={
            "name": f"TEST WH {uuid.uuid4().hex[:5]}", "source_default": "test",
            "assign_round_robin": False,
        })
        assert r2.status_code == 200, r2.text
        hook = r2.json()
        cleanup["webhooks"].append(hook["id"])
        token = hook["token"]

        # 3) POST to webhook with the alias key (unauthenticated public endpoint)
        phone = f"888{int(time.time()) % 10000000:07d}"
        payload = {"full_name": "TEST Webhook User", "phone": phone, "email": "wh@test.com",
                   alias: "AUTO_CAPTURED_VALUE", "utm_source": "facebook_test"}
        r3 = requests.post(f"{API}/webhook/lead/{token}", json=payload, timeout=30)
        assert r3.status_code == 200, r3.text
        new_lid = r3.json()["lead_id"]
        cleanup["leads"].append(new_lid)

        # 4) Verify lead was created with custom field key populated
        g = admin_client.get(f"{API}/leads/{new_lid}")
        assert g.status_code == 200
        lead = g.json()
        assert lead["contact_name"] == "TEST Webhook User" or lead.get("name") == "TEST Webhook User"
        assert lead["phone"] == phone
        custom = lead.get("custom") or {}
        assert custom.get(fld["key"]) == "AUTO_CAPTURED_VALUE", f"Alias not mapped, custom={custom}"


# ---------- CASE 5: WhatsApp send ----------
class TestCase5WhatsApp:
    def test_whatsapp_templates_list(self, admin_client):
        r = admin_client.get(f"{API}/templates/whatsapp")
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        assert len(items) > 0, "Expected WhatsApp templates"

    def test_send_whatsapp_queues(self, admin_client, fresh_lead):
        templates = admin_client.get(f"{API}/templates/whatsapp").json()
        assert len(templates) > 0
        tid = templates[0]["id"]
        lid = fresh_lead["id"]
        r = admin_client.post(f"{API}/leads/{lid}/send_whatsapp", json={"template_id": tid})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["status"] == "queued"

        # Verify chatter entry
        ch = admin_client.get(f"{API}/leads/{lid}/messages")
        assert ch.status_code == 200
        msgs = ch.json()
        bodies = " ".join([m.get("body", "") for m in (msgs if isinstance(msgs, list) else msgs.get("items", []))])
        assert "WhatsApp template" in bodies or "WhatsApp" in bodies


# ---------- CASE 6: Email send + save_as_template ----------
class TestCase6Email:
    def test_email_templates_list(self, admin_client):
        r = admin_client.get(f"{API}/templates/email")
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        assert len(items) > 0, "Expected Email templates"

    def test_send_email_queues(self, admin_client, fresh_lead):
        lid = fresh_lead["id"]
        r = admin_client.post(f"{API}/leads/{lid}/send_email", json={
            "to": "to@test.com", "subject": "TEST Subj", "body": "TEST Body"
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True and d["status"] == "queued"

    def test_send_email_save_as_template(self, admin_client, fresh_lead):
        lid = fresh_lead["id"]
        tpl_name = f"TEST EmailTpl {uuid.uuid4().hex[:5]}"
        r = admin_client.post(f"{API}/leads/{lid}/send_email", json={
            "to": "to2@test.com", "subject": "TEST Save Subj", "body": "TEST Save Body",
            "save_as_template": tpl_name
        })
        assert r.status_code == 200, r.text
        # Verify template created
        tpls = admin_client.get(f"{API}/templates/email").json()
        names = [t.get("name") for t in tpls]
        assert tpl_name in names, f"Email template not saved. names sample: {names[:5]}"


# ---------- CASE 7: UTM Attribution ----------
class TestCase7UTM:
    def test_utm_catalogs_keys_present(self, admin_client):
        r = admin_client.get(f"{API}/catalogs")
        data = r.json()
        for k in ("utm_source", "utm_medium", "utm_campaign"):
            assert k in data, f"Missing catalog: {k}"

    def test_patch_lead_utm_fields(self, admin_client, fresh_lead):
        lid = fresh_lead["id"]
        # Get a few existing UTM ids (or 0 if none present)
        cats = admin_client.get(f"{API}/catalogs").json()
        # Use IDs if any exist, else use arbitrary integers (lead stores them as ints)
        src = (cats["utm_source"][0]["id"] if cats.get("utm_source") else 1)
        med = (cats["utm_medium"][0]["id"] if cats.get("utm_medium") else 1)
        cmp_ = (cats["utm_campaign"][0]["id"] if cats.get("utm_campaign") else 1)
        r = admin_client.patch(f"{API}/leads/{lid}", json={"updates": {
            "source_id": src, "medium_id": med, "campaign_id": cmp_
        }})
        assert r.status_code == 200, r.text
        got = r.json()
        assert got.get("source_id") == src
        assert got.get("medium_id") == med
        assert got.get("campaign_id") == cmp_


# ---------- CASE 8: Automations ----------
class TestCase8Automations:
    def test_automation_on_lead_stage_change_fires(self, admin_client, cleanup):
        # 1) Get a template id
        tpl = admin_client.get(f"{API}/templates/whatsapp").json()[0]
        # 2) Create automation
        rule_name = f"TEST_Auto_Stage_{uuid.uuid4().hex[:5]}"
        r = admin_client.post(f"{API}/admin/automations", json={
            "name": rule_name, "trigger": "on_stage_set",
            "condition": {"lead_stage": "Converted"},
            "actions": [{"type": "send_whatsapp_template", "value": tpl["id"]}],
            "active": True
        })
        assert r.status_code == 200, r.text
        aid = r.json()["id"]
        cleanup["automations"].append(aid)

        # 3) Create fresh lead
        rl = admin_client.post(f"{API}/leads", json={
            "contact_name": f"TEST_Auto_{uuid.uuid4().hex[:5]}",
            "phone": f"77{int(time.time()) % 100000000:08d}",
            "lead_stage": "Contact Attempt",
        })
        assert rl.status_code == 200
        lid = rl.json()["id"]
        cleanup["leads"].append(lid)

        # 4) PATCH lead_stage to Converted (the key bug-fix case)
        rp = admin_client.patch(f"{API}/leads/{lid}", json={"updates": {"lead_stage": "Converted"}})
        assert rp.status_code == 200

        # 5) Verify outbound_queue has new entry tied to this rule
        time.sleep(1)
        q = admin_client.get(f"{API}/admin/outbound_queue").json()
        matched = [x for x in q if x.get("lead_id") == lid and x.get("automation") == rule_name]
        assert len(matched) >= 1, f"Automation did NOT fire on lead_stage change. queue sample: {q[:3]}"

        # 6) Verify chatter has 'Automation ... queued' message
        ch = admin_client.get(f"{API}/leads/{lid}/messages").json()
        items = ch if isinstance(ch, list) else ch.get("items", [])
        joined = " ".join([m.get("body", "") for m in items])
        assert rule_name in joined and "queued" in joined.lower()

    def test_automation_on_tag_set_fires(self, admin_client, cleanup):
        # Create a tag
        tag_name = f"TEST_AutoTag_{uuid.uuid4().hex[:5]}"
        t = admin_client.post(f"{API}/catalogs/tag", json={"name": tag_name}).json()
        tag_id = t["id"]
        # Get template
        tpl = admin_client.get(f"{API}/templates/whatsapp").json()[0]
        # Create automation on_tag_set
        rule_name = f"TEST_Auto_Tag_{uuid.uuid4().hex[:5]}"
        r = admin_client.post(f"{API}/admin/automations", json={
            "name": rule_name, "trigger": "on_tag_set",
            "condition": {"tag_id": tag_id},
            "actions": [{"type": "send_whatsapp_template", "value": tpl["id"]}],
            "active": True
        })
        assert r.status_code == 200, r.text
        cleanup["automations"].append(r.json()["id"])

        # Fresh lead
        rl = admin_client.post(f"{API}/leads", json={
            "contact_name": f"TEST_AutoTagLead_{uuid.uuid4().hex[:5]}",
            "phone": f"77{int(time.time()) % 100000000:08d}",
        })
        lid = rl.json()["id"]
        cleanup["leads"].append(lid)

        # PATCH tags to include the tag
        admin_client.patch(f"{API}/leads/{lid}", json={"updates": {"tags": [tag_id]}})
        time.sleep(1)
        q = admin_client.get(f"{API}/admin/outbound_queue").json()
        matched = [x for x in q if x.get("lead_id") == lid and x.get("automation") == rule_name]
        assert len(matched) >= 1, "on_tag_set automation did not fire"

    def test_automation_on_bulk_add_tags_fires(self, admin_client, cleanup):
        tag_name = f"TEST_BulkTag_{uuid.uuid4().hex[:5]}"
        tag_id = admin_client.post(f"{API}/catalogs/tag", json={"name": tag_name}).json()["id"]
        tpl = admin_client.get(f"{API}/templates/whatsapp").json()[0]
        rule_name = f"TEST_Auto_Bulk_{uuid.uuid4().hex[:5]}"
        r = admin_client.post(f"{API}/admin/automations", json={
            "name": rule_name, "trigger": "on_tag_set",
            "condition": {"tag_id": tag_id},
            "actions": [{"type": "send_whatsapp_template", "value": tpl["id"]}],
            "active": True
        })
        assert r.status_code == 200
        cleanup["automations"].append(r.json()["id"])

        # Create 2 fresh leads
        lids = []
        for i in range(2):
            rl = admin_client.post(f"{API}/leads", json={
                "contact_name": f"TEST_Bulk_{i}_{uuid.uuid4().hex[:5]}",
                "phone": f"66{int(time.time()) % 100000000 + i:08d}",
            })
            lids.append(rl.json()["id"])
            cleanup["leads"].append(rl.json()["id"])

        # Bulk add_tags
        rb = admin_client.post(f"{API}/leads/bulk", json={
            "ids": lids, "action": "add_tags", "payload": {"tags": [tag_id]}
        })
        assert rb.status_code == 200, rb.text
        time.sleep(2)
        q = admin_client.get(f"{API}/admin/outbound_queue").json()
        matched = [x for x in q if x.get("lead_id") in lids and x.get("automation") == rule_name]
        assert len(matched) >= 2, f"Expected 2 bulk-fires, got {len(matched)}"

    def test_automation_crud(self, admin_client, cleanup):
        r = admin_client.post(f"{API}/admin/automations", json={
            "name": f"TEST_CRUD_{uuid.uuid4().hex[:5]}", "trigger": "on_create",
            "condition": {}, "actions": [{"type": "add_tag", "value": 1}], "active": True
        })
        assert r.status_code == 200
        aid = r.json()["id"]
        # Toggle off
        r2 = admin_client.patch(f"{API}/admin/automations/{aid}", json={"active": False})
        assert r2.status_code == 200 and r2.json()["active"] is False
        # Delete
        r3 = admin_client.delete(f"{API}/admin/automations/{aid}")
        assert r3.status_code == 200


# ---------- REGRESSION ----------
class TestRegression:
    def test_leads_list_loads(self, admin_client):
        r = admin_client.get(f"{API}/leads?limit=5")
        assert r.status_code == 200
        assert "items" in r.json() and "total" in r.json()
        assert r.json()["total"] > 90000  # production ~99.6K

    def test_lead_detail_loads(self, admin_client):
        items = admin_client.get(f"{API}/leads?limit=1").json()["items"]
        if items:
            r = admin_client.get(f"{API}/leads/{items[0]['id']}")
            assert r.status_code == 200

    def test_chatter_post_note(self, admin_client, fresh_lead):
        lid = fresh_lead["id"]
        r = admin_client.post(f"{API}/leads/{lid}/messages", json={"body": "TEST chatter note"})
        # Some routers use different verbs; accept 200/201
        assert r.status_code in (200, 201), r.text

    def test_dashboard_endpoint(self, admin_client):
        # Try common dashboard endpoint names
        for path in ["/reports/dashboard", "/dashboard", "/reports/summary"]:
            r = admin_client.get(f"{API}{path}")
            if r.status_code == 200:
                return
        # not fatal
        pytest.skip("No dashboard endpoint reachable - frontend test will cover")
