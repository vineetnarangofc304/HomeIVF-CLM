"""Iteration 54 — Validate USER'S REAL prod WhatsApp new-lead automation.

Scenario (per user's decision):
  - CRM template id 4 'New Lead - Message' linked to Meta template 'new_lead_message' (en).
  - Automation id 1 'Whatsapp New Lead - Welcome Message' on_create action
    send_whatsapp_template value=4.
  - Creating a new lead must trigger a real TEMPLATE send (type:template) — NOT free-text —
    and NOT return the "not linked to an approved Meta template" / 131047 actionable error.

Preview Meta token is invalid → the Meta call will fail with an AUTH error (that's expected
and PROVES a template send was attempted).
"""
import time
import pytest
import requests

BASE_URL = "https://homeivf-crm-1.preview.emergentagent.com"
ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
TEMPLATE_ID = 4
AUTOMATION_ID = 1
WA_TEMPLATE_NAME = "new_lead_message"


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=30)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s


@pytest.fixture(scope="module")
def cleanup_registry():
    reg = {"leads": []}
    yield reg
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=30)
    if r.status_code == 200:
        s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
        for lid in reg["leads"]:
            try:
                s.post(f"{BASE_URL}/api/leads/{lid}/lost", json={}, timeout=15)
            except Exception:
                pass


# ---------- Regression sanity ----------

class TestRegressionSanity:
    def test_admin_login_ok(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("access_token")

    def test_leads_list_ok(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads?limit=5&page=1", timeout=30)
        assert r.status_code == 200, r.text

    def test_leads_search_ok(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads?search=test&limit=5&page=1", timeout=30)
        assert r.status_code == 200, r.text


# ---------- Baseline: automation & template present as user described ----------

class TestConfigPresent:
    def test_automation_id_1_points_to_template_4(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/automations", timeout=30)
        assert r.status_code == 200, r.text
        autos = r.json()
        a = next((x for x in autos if x.get("id") == AUTOMATION_ID), None)
        assert a is not None, f"automation id 1 missing: {autos}"
        assert a.get("active") is True, a
        assert a.get("trigger") == "on_create", a
        actions = a.get("actions") or []
        assert any(ac.get("type") == "send_whatsapp_template" and int(ac.get("value")) == TEMPLATE_ID
                   for ac in actions), f"automation actions not pointing to tmpl {TEMPLATE_ID}: {actions}"

    def test_template_id_4_linked(self, admin):
        r = admin.get(f"{BASE_URL}/api/templates/whatsapp", timeout=30)
        assert r.status_code == 200, r.text
        tmpls = r.json()
        t = next((x for x in tmpls if x.get("id") == TEMPLATE_ID), None)
        assert t is not None, f"template id 4 missing: {[x.get('id') for x in tmpls]}"
        assert t.get("wa_template_name") == WA_TEMPLATE_NAME, t
        assert (t.get("lang") or "").lower() == "en", t


# ---------- Sync re-links after unset ----------

class TestSyncRelinksTemplate:
    def test_sync_relinks_template_4(self, admin):
        """UNSET template 4's wa_template_name via a direct DB update, then run the
        sync endpoint and confirm it re-links to 'new_lead_message'."""
        import motor.motor_asyncio, os, asyncio
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "test_database")

        async def unset():
            client = motor.motor_asyncio.AsyncIOMotorClient(mongo_url)
            db = client[db_name]
            res = await db.templates_whatsapp.update_one(
                {"id": TEMPLATE_ID}, {"$unset": {"wa_template_name": "", "lang": ""}})
            client.close()
            return res.modified_count

        # Only run DB tweak if MONGO_URL points to a reachable db from test host
        try:
            mc = asyncio.run(unset())
        except Exception as e:
            pytest.skip(f"cannot access mongo directly to unset: {e}")

        # Confirm it's now unlinked
        r = admin.get(f"{BASE_URL}/api/templates/whatsapp", timeout=30)
        t = next((x for x in r.json() if x.get("id") == TEMPLATE_ID), None)
        assert t is not None
        assert not t.get("wa_template_name"), f"unset failed: {t}"

        # Run the sync (hits live Odoo, ~4s)
        r = admin.post(f"{BASE_URL}/api/admin/whatsapp/sync-odoo-templates", timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True, body
        assert body.get("linked_updated", 0) > 0, f"sync did not link anything: {body}"

        # Confirm template 4 is re-linked
        r = admin.get(f"{BASE_URL}/api/templates/whatsapp", timeout=30)
        t = next((x for x in r.json() if x.get("id") == TEMPLATE_ID), None)
        assert t is not None
        assert t.get("wa_template_name") == WA_TEMPLATE_NAME, f"not re-linked: {t}"
        assert (t.get("lang") or "").lower() == "en", t


# ---------- E2E: creating a lead attempts a TEMPLATE send (not free-text, not 131047) ----------

def _wa_track_for_lead(admin, lead_id):
    r = admin.get(f"{BASE_URL}/api/wa/lead/{lead_id}/messages", timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


class TestNewLeadWelcomeAutomationE2E:
    def test_new_lead_triggers_template_send(self, admin, cleanup_registry):
        # Confirm template 4 is linked (should be after previous class ran; still verify)
        r = admin.get(f"{BASE_URL}/api/templates/whatsapp", timeout=30)
        t4 = next((x for x in r.json() if x.get("id") == TEMPLATE_ID), None)
        assert t4 and t4.get("wa_template_name") == WA_TEMPLATE_NAME, f"prereq: tmpl 4 must be linked; got {t4}"

        # Create the lead
        contact_name = "Test Welcome"
        phone = "919999000011"
        payload = {"name": f"TEST_WELCOME_{int(time.time()*1000)}",
                   "contact_name": contact_name, "phone": phone,
                   "email_from": f"welcome_{int(time.time()*1000)}@example.com"}
        r = admin.post(f"{BASE_URL}/api/leads", json=payload, timeout=30)
        assert r.status_code == 200, r.text
        lead = r.json()
        cleanup_registry["leads"].append(lead["id"])

        # Give the automation a beat
        time.sleep(1.5)

        tracks = _wa_track_for_lead(admin, lead["id"])
        # Find automation-source track for template 4
        auto_tracks = [x for x in tracks if x.get("source") == "automation" and x.get("template_id") == TEMPLATE_ID]
        assert auto_tracks, f"no automation wa_tracking for tmpl {TEMPLATE_ID}: {tracks}"
        t = auto_tracks[0]

        # Basic identity assertions
        assert t.get("template_name") == "New Lead - Message", t
        assert t.get("sent_to") in (phone, "+" + phone), t

        # Body preview should include contact_name substituted for {{1}}
        body = t.get("body") or ""
        assert contact_name in body, f"contact name not substituted in body preview: {body!r}"

        # THE CORE ASSERTION: this attempted a real TEMPLATE send, NOT free-text.
        # → Error (if any) must NOT be the "not linked" actionable error AND must NOT
        #   mention 131047.
        err = (t.get("error") or "")
        assert "not linked to an approved Meta template" not in err, (
            f"linked prod template hit the actionable-block path — indicates it fell through "
            f"to require_template unlinked branch. err={err!r}"
        )
        assert "131047" not in err, f"prod template send unexpectedly mentions 131047: {err!r}"

        # Status is expected to be 'failed' in preview (invalid Meta token) OR 'sent'.
        # It MUST NOT be 'in_queue' — that would mean wa_configured was False (misconfig).
        assert t.get("status") in ("failed", "sent"), (
            f"expected sent/failed (preview token invalid → failed OK); got {t.get('status')}, "
            f"err={t.get('error')!r}. in_queue means WA not configured; sent means success."
        )


# ---------- Unit-ish: send_lead_template takes the template branch for linked doc ----------

class TestSendLeadTemplateBranch:
    def test_send_template_called_not_send_text(self):
        """Directly patch send_template / send_text and call send_lead_template with
        template id 4's doc + require_template=True. send_template must be invoked
        exactly once with 'new_lead_message' and body param = contact name; send_text
        must NOT be called."""
        import asyncio
        import sys, os
        # Make backend importable
        sys.path.insert(0, "/app/backend")
        from core import whatsapp_cloud as wac

        calls = {"template": [], "text": []}

        async def fake_send_template(phone, name, lang, params):
            calls["template"].append({"phone": phone, "name": name, "lang": lang, "params": params})
            return {"ok": False, "error": "fake meta auth error (preview token invalid)"}

        async def fake_send_text(phone, body):
            calls["text"].append({"phone": phone, "body": body})
            return {"ok": False, "error": "should not have been called"}

        # Monkey-patch
        orig_tmpl = wac.send_template
        orig_text = wac.send_text
        wac.send_template = fake_send_template
        wac.send_text = fake_send_text

        try:
            lead = {"id": 999999, "phone": "919999000011", "contact_name": "Test Welcome",
                    "name": "TEST_UNIT"}
            template = {"id": TEMPLATE_ID, "name": "New Lead - Message",
                        "wa_template_name": WA_TEMPLATE_NAME, "lang": "en",
                        "body": "Dear {{1}}, Thank you for choosing HomeIVF by Dr. Gauri Agarwal..."}
            res = asyncio.run(wac.send_lead_template(lead, template, require_template=True))
        finally:
            wac.send_template = orig_tmpl
            wac.send_text = orig_text

        assert len(calls["template"]) == 1, f"send_template should be called exactly once: {calls}"
        assert len(calls["text"]) == 0, f"send_text must NOT be called for linked tmpl: {calls}"
        c = calls["template"][0]
        assert c["name"] == WA_TEMPLATE_NAME, c
        assert c["lang"] == "en", c
        assert c["params"] == ["Test Welcome"], c
        assert c["phone"] == "919999000011", c
