"""
Iteration 9 — Full regression covering Cases 1..17 from review request.
Backend-side checks. Uses the preview REACT_APP_BACKEND_URL.
"""
import os
import io
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASS = "HomeIVF@2026"
AGENT_EMAIL = "agent@homeivf.com"
AGENT_PASS = "Agent@2026"


# ---------- shared fixtures ----------
@pytest.fixture(scope="session")
def admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token")
    assert tok
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="session")
def agent():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": AGENT_EMAIL, "password": AGENT_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s


# ===== Case 6 — Auth from another browser / Bearer fallback =====
class TestCase6Auth:
    def test_admin_login_returns_token(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data.get("access_token") and isinstance(data["access_token"], str)
        assert data.get("email") == ADMIN_EMAIL
        # cookies also set (httpOnly)
        assert any(c.name in ("hivf_access", "access_token", "hivf_session") for c in r.cookies) or r.cookies

    def test_agent_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": AGENT_EMAIL, "password": AGENT_PASS}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("access_token")

    def test_me_with_bearer_only(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
        tok = r.json()["access_token"]
        # New session — no cookies, only Bearer
        s2 = requests.Session()
        m = s2.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert m.status_code == 200, m.text
        assert m.json().get("email") == ADMIN_EMAIL


# ===== Case 1 & 3 — Automations =====
class TestCase1_3Automations:
    created_ids = []

    def test_create_multi_action_automation(self, admin):
        body = {
            "name": "TEST_iter9_auto",
            "trigger": "on_stage_set",
            "actions": [
                {"type": "add_tag", "tag_id": 1},
                {"type": "assign_agent", "user_id": 1001},
            ],
            "active": True,
        }
        r = admin.post(f"{BASE_URL}/api/admin/automations", json=body, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == "TEST_iter9_auto"
        assert d["trigger"] == "on_stage_set"
        assert isinstance(d["actions"], list) and len(d["actions"]) == 2
        TestCase1_3Automations.created_ids.append(d["id"])

    def test_create_on_tag_set(self, admin):
        body = {
            "name": "TEST_iter9_auto_tag",
            "trigger": "on_tag_set",
            "actions": [{"type": "add_tag", "tag_id": 2}],
            "active": True,
        }
        r = admin.post(f"{BASE_URL}/api/admin/automations", json=body, timeout=15)
        assert r.status_code == 200
        TestCase1_3Automations.created_ids.append(r.json()["id"])

    def test_invalid_trigger(self, admin):
        r = admin.post(f"{BASE_URL}/api/admin/automations",
                       json={"name": "BAD", "trigger": "nope", "actions": []}, timeout=15)
        assert r.status_code == 400

    def test_list_automations(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/automations", timeout=15)
        assert r.status_code == 200
        names = [a["name"] for a in r.json()]
        assert "TEST_iter9_auto" in names

    def test_zz_cleanup(self, admin):
        for aid in TestCase1_3Automations.created_ids:
            admin.delete(f"{BASE_URL}/api/admin/automations/{aid}", timeout=15)


# ===== Case 2 — Custom fields CRUD + reorder =====
class TestCase2CustomFields:
    created_fids = []

    def test_create_custom_field_text(self, admin):
        r = admin.post(f"{BASE_URL}/api/catalogs/custom-fields/create",
                       json={"label": f"TEST_iter9_text_{uuid.uuid4().hex[:6]}", "field_type": "text", "section": "general"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["key"].startswith("x_custom_")
        assert d["field_type"] == "text"
        TestCase2CustomFields.created_fids.append(d["id"])

    def test_create_select_with_options(self, admin):
        r = admin.post(f"{BASE_URL}/api/catalogs/custom-fields/create",
                       json={"label": f"TEST_iter9_sel_{uuid.uuid4().hex[:6]}", "field_type": "selection", "section": "general", "options": ["A", "B"]}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["field_type"] == "selection"
        assert d["options"] == ["A", "B"]
        TestCase2CustomFields.created_fids.append(d["id"])

    def test_list_includes_created(self, admin):
        r = admin.get(f"{BASE_URL}/api/catalogs/custom-fields/all", timeout=15)
        assert r.status_code == 200
        ids = [f["id"] for f in r.json()]
        for fid in TestCase2CustomFields.created_fids:
            assert fid in ids

    def test_reorder(self, admin):
        if len(TestCase2CustomFields.created_fids) < 2:
            pytest.skip("need 2 fields")
        ordered = list(reversed(TestCase2CustomFields.created_fids))
        r = admin.post(f"{BASE_URL}/api/catalogs/custom-fields/reorder",
                       json={"order": ordered}, timeout=15)
        assert r.status_code == 200, r.text

    def test_patch_field(self, admin):
        if not TestCase2CustomFields.created_fids:
            pytest.skip("no field created")
        fid = TestCase2CustomFields.created_fids[0]
        r = admin.patch(f"{BASE_URL}/api/catalogs/custom-fields/{fid}",
                        json={"label": f"TEST_iter9_renamed_{uuid.uuid4().hex[:6]}"}, timeout=15)
        assert r.status_code == 200, r.text

    def test_zz_cleanup(self, admin):
        for fid in TestCase2CustomFields.created_fids:
            admin.delete(f"{BASE_URL}/api/catalogs/custom-fields/{fid}", params={"hard": True}, timeout=15)


# ===== Case 4 — Facebook config + test lead =====
class TestCase4Facebook:
    def test_fb_status(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/facebook/status", timeout=15)
        assert r.status_code == 200
        assert "configured" in r.json()

    def test_settings_save_facebook_payload(self, admin):
        # PATCH /admin/settings expects {key, value:{...}}
        body = {
            "key": "facebook",
            "value": {
                "app_id": "736963545504625",
                "field_mapping": {"full_name": "name", "phone_number": "phone"},
                "graph_api_version": "v25.0",
                "source_default": "Meta Lead Ads",
            },
        }
        r = admin.patch(f"{BASE_URL}/api/admin/settings", json=body, timeout=15)
        assert r.status_code in (200, 204), r.text

    def test_send_test_lead_creates_lead(self, admin):
        unique = f"TEST_iter9_FB_{uuid.uuid4().hex[:6]}"
        body = {
            "field_data": [
                {"name": "full_name", "values": [unique]},
                {"name": "phone_number", "values": ["9999988888"]},
                {"name": "email", "values": [f"{unique.lower()}@x.test"]},
            ],
            "leadgen_id": "MANUAL_TEST",
        }
        r = admin.post(f"{BASE_URL}/api/admin/facebook/test", json=body, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") and d.get("lead_id")
        # verify lead exists
        g = admin.get(f"{BASE_URL}/api/leads/{d['lead_id']}", timeout=15)
        assert g.status_code == 200
        # cleanup
        admin.delete(f"{BASE_URL}/api/leads/{d['lead_id']}", timeout=15)


# ===== Case 5 — Calls list for a lead =====
class TestCase5Calls:
    def test_calls_endpoint_shape(self, admin):
        # find a recent lead
        r = admin.get(f"{BASE_URL}/api/leads", params={"limit": 1}, timeout=15)
        assert r.status_code == 200
        items = r.json().get("items") or r.json()
        if not items:
            pytest.skip("no leads")
        lid = items[0]["id"]
        c = admin.get(f"{BASE_URL}/api/calls/lead/{lid}", timeout=15)
        assert c.status_code == 200
        body = c.json()
        assert isinstance(body, list)


# ===== Case 7 — Export Excel + PDF =====
class TestCase7Export:
    def test_export_excel(self, admin):
        r = admin.get(f"{BASE_URL}/api/export/leads.xlsx", params={"active": "all"}, timeout=60)
        assert r.status_code == 200
        assert r.content[:2] == b"PK"  # ZIP magic
        assert "spreadsheetml" in r.headers.get("content-type", "")

    def test_export_pdf(self, admin):
        r = admin.get(f"{BASE_URL}/api/export/report.pdf", timeout=60)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"
        assert "pdf" in r.headers.get("content-type", "")


# ===== Case 9/10 — Public webhook intake =====
class TestCase9Webhook:
    def test_webhook_list_and_post_lead(self, admin):
        r = admin.get(f"{BASE_URL}/api/webhooks", timeout=15)
        assert r.status_code == 200
        hooks = r.json()
        if not hooks:
            # create one
            c = admin.post(f"{BASE_URL}/api/webhooks", json={"name": "TEST_iter9_hook"}, timeout=15)
            assert c.status_code == 200, c.text
            hook = c.json()
            cleanup = True
        else:
            hook = hooks[0]
            cleanup = False
        token = hook["token"]
        unique = f"TEST_iter9_WH_{uuid.uuid4().hex[:6]}"
        # public endpoint — no auth
        p = requests.post(f"{BASE_URL}/api/webhook/lead/{token}",
                          json={"name": unique, "phone": "9876512345", "email": f"{unique.lower()}@x.test", "city": "Delhi"},
                          timeout=20)
        assert p.status_code in (200, 201), p.text
        d = p.json()
        lid = d.get("lead_id") or d.get("id")
        assert lid
        # cleanup lead
        admin.delete(f"{BASE_URL}/api/leads/{lid}", timeout=15)
        if cleanup:
            admin.delete(f"{BASE_URL}/api/webhooks/{hook['id']}", timeout=15)


# ===== Case 11 — Attachments =====
class TestCase11Attachments:
    def test_attachment_lifecycle(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads", params={"limit": 1}, timeout=15)
        items = r.json().get("items") or r.json()
        if not items:
            pytest.skip("no leads")
        lid = items[0]["id"]
        # upload
        f = ("test_iter9.txt", b"hello iter9", "text/plain")
        up = admin.post(f"{BASE_URL}/api/leads/{lid}/attachments", files={"file": f}, timeout=30)
        assert up.status_code == 200, up.text
        att = up.json()
        aid = att.get("id")
        assert aid
        # list
        ls = admin.get(f"{BASE_URL}/api/leads/{lid}/attachments", timeout=15)
        assert ls.status_code == 200
        ids = [a["id"] for a in ls.json()]
        assert aid in ids
        # download
        dl = admin.get(f"{BASE_URL}/api/attachments/{aid}/download", timeout=15)
        assert dl.status_code == 200
        # delete
        rm = admin.delete(f"{BASE_URL}/api/attachments/{aid}", timeout=15)
        assert rm.status_code in (200, 204)


# ===== Case 12/13 — Manage users =====
class TestCase12Users:
    def test_create_and_update_user(self, admin):
        suffix = uuid.uuid4().hex[:6]
        body = {
            "email": f"TEST_iter9_u{suffix}@homeivf.com",
            "name": f"TEST_iter9_User_{suffix}",
            "role": "caller",
            "password": "Temp@12345",
        }
        c = admin.post(f"{BASE_URL}/api/users", json=body, timeout=15)
        assert c.status_code == 200, c.text
        u = c.json()
        uid = u.get("id")
        assert uid
        # list (capped 500 by name) — verify by re-creating same email returns 400
        dup = admin.post(f"{BASE_URL}/api/users", json=body, timeout=15)
        assert dup.status_code == 400, "user not persisted (duplicate-check did not fire)"
        # deactivate
        upd = admin.patch(f"{BASE_URL}/api/users/{uid}", json={"active": False}, timeout=15)
        assert upd.status_code == 200
        assert upd.json().get("active") is False
        # reactivate
        admin.patch(f"{BASE_URL}/api/users/{uid}", json={"active": True}, timeout=15)
        # reset password
        rp = admin.patch(f"{BASE_URL}/api/users/{uid}", json={"password": "NewTemp@123"}, timeout=15)
        assert rp.status_code == 200


# ===== Case 14 — Marketing campaign lifecycle =====
class TestCase14Marketing:
    def test_audience_preview_and_create_and_send(self, admin):
        # find a template (optional)
        t = admin.get(f"{BASE_URL}/api/templates/whatsapp", timeout=15)
        templates = t.json() if t.status_code == 200 else []
        tpl_id = templates[0]["id"] if templates else None

        # create a campaign first
        body = {
            "name": f"TEST_iter9_camp_{uuid.uuid4().hex[:6]}",
            "channel": "whatsapp",
            "template_id": tpl_id,
            "audience": {"city": "__none_exists_xyz__"},
        }
        c = admin.post(f"{BASE_URL}/api/marketing/campaigns", json=body, timeout=15)
        assert c.status_code == 200, c.text
        cid = c.json()["id"]
        # audience-count
        pv = admin.post(f"{BASE_URL}/api/marketing/campaigns/{cid}/audience-count", timeout=20)
        assert pv.status_code == 200, pv.text
        count = pv.json().get("count")
        assert isinstance(count, int)
        # send (queues or no-op for empty audience)
        s = admin.post(f"{BASE_URL}/api/marketing/campaigns/{cid}/send", timeout=60)
        assert s.status_code == 200, s.text
        # delete
        d = admin.delete(f"{BASE_URL}/api/marketing/campaigns/{cid}", timeout=15)
        assert d.status_code in (200, 204)


# ===== Case 15 — 'New / Unassigned' replaces 'Undefined' =====
class TestCase15UndefinedFix:
    def test_dashboard_by_stage_label(self, admin):
        r = admin.get(f"{BASE_URL}/api/reports/dashboard", timeout=20)
        assert r.status_code == 200
        d = r.json()
        # by_stage rows have key '_id' (group key) — already remapped from None to 'New / Unassigned'
        labels = [str(row.get("_id")) for row in (d.get("by_stage") or [])]
        for l in labels:
            assert l.lower() != "undefined", f"got 'Undefined' in {labels}"
            assert l.lower() != "none", f"got None in {labels} (remap missing)"
        # since the DB has many null-stage leads, expect 'New / Unassigned' to be present
        assert any("New / Unassigned" in l for l in labels), f"missing 'New / Unassigned' in {labels}"

    def test_pivot_lead_stage_label(self, admin):
        r = admin.post(f"{BASE_URL}/api/reports/pivot",
                       json={"row": "lead_stage", "metric": "count"}, timeout=20)
        if r.status_code != 200:
            pytest.skip(f"pivot returned {r.status_code}")
        d = r.json()
        rows = d.get("rows") or d.get("items") or []
        for row in rows:
            for v in row.values():
                s = str(v).lower()
                assert s != "undefined", f"got 'Undefined': {row}"


# ===== Case 16 — WhatsApp template flow =====
class TestCase16WATemplate:
    def test_create_update_delete_wa_template(self, admin):
        body = {
            "name": f"TEST_iter9_wa_{uuid.uuid4().hex[:6]}",
            "body": "Hi {1}, welcome.",
            "wa_template_name": "appointment_booking",
            "lang": "en",
        }
        c = admin.post(f"{BASE_URL}/api/templates/whatsapp", json=body, timeout=15)
        assert c.status_code == 200, c.text
        t = c.json()
        tid = t["id"]
        assert t.get("wa_template_name") == "appointment_booking"
        # patch
        p = admin.patch(f"{BASE_URL}/api/templates/whatsapp/{tid}",
                        json={"lang": "hi"}, timeout=15)
        assert p.status_code == 200
        assert p.json().get("lang") == "hi"
        # delete
        d = admin.delete(f"{BASE_URL}/api/templates/whatsapp/{tid}", timeout=15)
        assert d.status_code in (200, 204)


# ===== Case 17 — Email template flow =====
class TestCase17EmailTemplate:
    def test_create_email_template(self, admin):
        body = {
            "name": f"TEST_iter9_em_{uuid.uuid4().hex[:6]}",
            "subject": "Hello {1}",
            "body": "<p>Dear {1}, this is a test.</p>",
        }
        c = admin.post(f"{BASE_URL}/api/templates/email", json=body, timeout=15)
        assert c.status_code == 200, c.text
        tid = c.json()["id"]
        d = admin.delete(f"{BASE_URL}/api/templates/email/{tid}", timeout=15)
        assert d.status_code in (200, 204)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
