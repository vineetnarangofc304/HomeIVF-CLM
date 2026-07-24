"""Iteration 53 — WhatsApp 131047 automation fix.

Verifies that automations/marketing now require an approved-Meta-linked template
and return an actionable error (mentioning 131047) INSTEAD of sending a doomed
free-text message that Meta rejects with 131047 for new leads.
"""
import re
import time
import pytest
import requests

BASE_URL = "https://ivf-lead-ops.preview.emergentagent.com"


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "admin@homeivf.com", "password": "HomeIVF@2026"}, timeout=30)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s


@pytest.fixture(scope="module")
def wa_configured(admin):
    # WhatsApp Cloud must be configured (token+phone_number_id) for this suite
    r = admin.get(f"{BASE_URL}/api/wa-cloud/status", timeout=15)
    # endpoint name may differ; try alt
    if r.status_code == 404:
        r = admin.get(f"{BASE_URL}/api/admin/whatsapp/status", timeout=15)
    return r


@pytest.fixture(scope="module")
def cleanup_registry():
    reg = {"leads": [], "templates": [], "automations": []}
    yield reg
    # Teardown (best effort)
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "admin@homeivf.com", "password": "HomeIVF@2026"}, timeout=30)
    if r.status_code == 200:
        s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
        for aid in reg["automations"]:
            try:
                s.delete(f"{BASE_URL}/api/admin/automations/{aid}", timeout=15)
            except Exception:
                pass
        for tid in reg["templates"]:
            try:
                s.delete(f"{BASE_URL}/api/templates/whatsapp/{tid}", timeout=15)
            except Exception:
                pass
        for lid in reg["leads"]:
            try:
                s.post(f"{BASE_URL}/api/leads/{lid}/lost", json={}, timeout=15)
            except Exception:
                pass


def _make_unlinked_template(admin, cleanup_registry):
    body = {"name": f"TEST_UNLINKED_{int(time.time()*1000)}",
            "body": "Hello {{1}}, welcome to HomeIVF (test unlinked)",
            "template_type": "whatsapp"}
    r = admin.post(f"{BASE_URL}/api/templates/whatsapp", json=body, timeout=30)
    assert r.status_code == 200, r.text
    tmpl = r.json()
    cleanup_registry["templates"].append(tmpl["id"])
    # Ensure no wa_template_name (unlinked)
    assert not tmpl.get("wa_template_name")
    return tmpl


def _make_linked_template(admin, cleanup_registry):
    body = {"name": f"TEST_LINKED_{int(time.time()*1000)}",
            "body": "Hi {{1}}, this is a linked test template",
            "template_type": "whatsapp",
            "wa_template_name": "new_lead_message",
            "lang": "en"}
    r = admin.post(f"{BASE_URL}/api/templates/whatsapp", json=body, timeout=30)
    assert r.status_code == 200, r.text
    tmpl = r.json()
    cleanup_registry["templates"].append(tmpl["id"])
    assert tmpl.get("wa_template_name") == "new_lead_message"
    return tmpl


def _create_automation(admin, cleanup_registry, template_id, name_prefix):
    body = {"name": f"{name_prefix}_{int(time.time()*1000)}",
            "trigger": "on_create",
            "actions": [{"type": "send_whatsapp_template", "value": template_id}],
            "condition": {}, "active": True}
    r = admin.post(f"{BASE_URL}/api/admin/automations", json=body, timeout=30)
    assert r.status_code == 200, r.text
    a = r.json()
    cleanup_registry["automations"].append(a["id"])
    return a


def _create_lead(admin, cleanup_registry, name_suffix=""):
    phone = "9199" + str(int(time.time()) % 10_000_000).zfill(7)
    body = {"name": f"TEST_LEAD_131047_{name_suffix}_{int(time.time()*1000)}",
            "contact_name": "Test Person", "phone": phone,
            "email_from": f"test_{int(time.time()*1000)}@example.com"}
    r = admin.post(f"{BASE_URL}/api/leads", json=body, timeout=30)
    assert r.status_code == 200, r.text
    lead = r.json()
    cleanup_registry["leads"].append(lead["id"])
    return lead


def _wa_track_for_lead(admin, lead_id):
    r = admin.get(f"{BASE_URL}/api/wa/lead/{lead_id}/messages", timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Regression sanity (from iter 52) ----------

class TestRegressionSanity:
    def test_leads_list_ok(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads?limit=5&page=1", timeout=30)
        assert r.status_code == 200, r.text

    def test_leads_search_ok(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads?search=test&limit=5&page=1", timeout=30)
        assert r.status_code == 200, r.text


# ---------- Automation UNLINKED template ----------

class TestAutomationUnlinkedTemplate:
    def test_unlinked_returns_actionable_131047_error(self, admin, cleanup_registry):
        tmpl = _make_unlinked_template(admin, cleanup_registry)
        auto = _create_automation(admin, cleanup_registry, tmpl["id"], "TEST_AUTO_UNLINKED")
        lead = _create_lead(admin, cleanup_registry, "unlinked")

        # Wait briefly for automation run (in-process, should be sync but just in case)
        time.sleep(1.0)

        tracks = _wa_track_for_lead(admin, lead["id"])
        assert len(tracks) >= 1, f"expected wa_tracking record, got {tracks}"

        # Find the track for this template
        t = next((x for x in tracks if x.get("template_id") == tmpl["id"]), None)
        assert t is not None, f"no wa_tracking for template {tmpl['id']}: {tracks}"

        # Status MUST be failed (not in_queue/sent)
        assert t["status"] == "failed", f"expected status=failed, got {t['status']} track={t}"

        # Error text must mention 131047 (actionable)
        err = (t.get("error") or "").lower()
        assert "131047" in err, f"expected error to mention 131047, got: {t.get('error')}"

        # Source should be automation
        assert t.get("source") == "automation"

    def test_unlinked_chatter_log_shows_failed(self, admin, cleanup_registry):
        tmpl = _make_unlinked_template(admin, cleanup_registry)
        auto = _create_automation(admin, cleanup_registry, tmpl["id"], "TEST_AUTO_UNLINKED_CHAT")
        lead = _create_lead(admin, cleanup_registry, "unlinked_chat")
        time.sleep(1.0)

        # Fetch messages / chatter for lead
        r = admin.get(f"{BASE_URL}/api/chatter/{lead['id']}", timeout=30)
        if r.status_code == 404:
            r = admin.get(f"{BASE_URL}/api/leads/{lead['id']}/messages", timeout=30)
        assert r.status_code == 200, r.text
        msgs = r.json()
        if isinstance(msgs, dict):
            msgs = msgs.get("messages") or msgs.get("items") or []
        wa_msgs = [m for m in msgs if (m.get("kind") == "wa_template") or ("WhatsApp template" in (m.get("body") or ""))]
        assert wa_msgs, f"no WhatsApp automation entry in chatter: {msgs}"
        # At least one should indicate failure with actionable msg
        failed_msg = next((m for m in wa_msgs if "failed" in (m.get("body") or "").lower()), None)
        assert failed_msg is not None, f"WhatsApp chatter should show failed: {wa_msgs}"
        assert failed_msg.get("status") != "sent"


# ---------- Automation LINKED template ----------

class TestAutomationLinkedTemplate:
    def test_linked_attempts_template_send_not_freetext(self, admin, cleanup_registry):
        tmpl = _make_linked_template(admin, cleanup_registry)
        auto = _create_automation(admin, cleanup_registry, tmpl["id"], "TEST_AUTO_LINKED")
        lead = _create_lead(admin, cleanup_registry, "linked")
        time.sleep(1.0)

        tracks = _wa_track_for_lead(admin, lead["id"])
        t = next((x for x in tracks if x.get("template_id") == tmpl["id"]), None)
        assert t is not None, f"no wa_tracking for linked template {tmpl['id']}: {tracks}"

        # Since preview token is invalid, expect failed, but error must NOT be the
        # actionable "not linked / 131047" one — it should be an auth/token error from Meta.
        err = (t.get("error") or "")
        # The actionable message contains the phrase "not linked to an approved Meta template"
        assert "not linked to an approved Meta template" not in err, (
            f"linked template should NOT trigger 'not linked' actionable error; got: {err}"
        )
        # And 131047 must NOT be in error (that's the unlinked-freetext-only marker)
        assert "131047" not in err, f"linked template error unexpectedly mentions 131047: {err}"


# ---------- Manual per-lead send regression (free-text fallback preserved) ----------

class TestManualSendRegression:
    def test_manual_send_unlinked_template_does_not_raise(self, admin, cleanup_registry):
        tmpl = _make_unlinked_template(admin, cleanup_registry)
        lead = _create_lead(admin, cleanup_registry, "manual")

        r = admin.post(f"{BASE_URL}/api/leads/{lead['id']}/send_whatsapp",
                       json={"template_id": tmpl["id"]}, timeout=30)
        # Should not raise 5xx; either 200 (tracked) or a 400/etc but not a server error
        assert r.status_code < 500, f"manual send raised: {r.status_code} {r.text}"
        assert r.status_code == 200, r.text

        # A wa_tracking record should exist (either sent/failed — free-text path attempted)
        tracks = _wa_track_for_lead(admin, lead["id"])
        t = next((x for x in tracks if x.get("template_id") == tmpl["id"]), None)
        assert t is not None, f"manual send should record tracking: {tracks}"
        # Manual path uses require_template=False → free-text fallback. Error (if any)
        # must NOT be the actionable "not linked" msg (that would mean require_template
        # got wrongly forced on for manual)
        err = (t.get("error") or "")
        assert "not linked to an approved Meta template" not in err, (
            f"manual send should keep free-text fallback, but got actionable-block err: {err}"
        )
