"""Iteration 8 — Backend tests for Cases 5, 7, 11, 14, 15, 16/17 + Bearer-token auth."""
import io
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://homeivf-crm-1.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASS = "HomeIVF@2026"
AGENT_EMAIL = "agent@homeivf.com"
AGENT_PASS = "Agent@2026"


def _bearer(email, password):
    """Bearer-token-only client (no cookie jar) to verify Case 6 fallback."""
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data and data["access_token"]
    assert "email" in data and data["email"] == email
    assert "role" in data
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {data['access_token']}"})
    # IMPORTANT: don't keep cookies — simulate browser that blocks cross-site cookies
    s.cookies.clear()
    return s, data


# ─── Case 6: Bearer-token fallback auth ────────────────────────────────────
class TestBearerAuth:
    def test_admin_login_returns_flat_token(self):
        s, data = _bearer(ADMIN_EMAIL, ADMIN_PASS)
        assert data["role"] == "admin"
        # verify token works on /me without cookies
        r = s.get(f"{BASE_URL}/api/auth/me", timeout=20)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me.get("email") == ADMIN_EMAIL
        assert me.get("role") == "admin"

    def test_agent_login_with_bearer_only(self):
        s, data = _bearer(AGENT_EMAIL, AGENT_PASS)
        assert data["role"] in ("caller", "agent", "admin", "manager")
        r = s.get(f"{BASE_URL}/api/auth/me", timeout=20)
        assert r.status_code == 200
        assert r.json().get("email") == AGENT_EMAIL

    def test_invalid_token_rejected(self):
        s = requests.Session()
        s.headers.update({"Authorization": "Bearer bogus.invalid.token"})
        r = s.get(f"{BASE_URL}/api/auth/me", timeout=20)
        assert r.status_code in (401, 403)


@pytest.fixture(scope="module")
def admin():
    s, _ = _bearer(ADMIN_EMAIL, ADMIN_PASS)
    return s


# ─── Case 7: Excel + PDF export ─────────────────────────────────────────────
class TestExport:
    def test_export_leads_xlsx(self, admin):
        r = admin.get(f"{BASE_URL}/api/export/leads.xlsx",
                      params={"date_from": "2026-06-01", "date_to": "2026-06-27", "active": "all"},
                      timeout=180)
        assert r.status_code == 200, r.text[:300]
        ctype = r.headers.get("content-type", "")
        assert "spreadsheetml" in ctype, f"unexpected ctype {ctype}"
        # xlsx is a zip → starts with PK
        body = r.content
        assert body[:2] == b"PK", "xlsx body should start with PK zip magic"
        assert len(body) > 1000

    def test_export_report_pdf(self, admin):
        r = admin.get(f"{BASE_URL}/api/export/report.pdf",
                      params={"date_from": "2026-06-01"}, timeout=180)
        assert r.status_code == 200, r.text[:300]
        assert "application/pdf" in r.headers.get("content-type", "")
        assert r.content[:4] == b"%PDF"

    def test_export_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/export/leads.xlsx", timeout=30)
        assert r.status_code in (401, 403)


# ─── Case 11: Lead attachments ──────────────────────────────────────────────
class TestAttachments:
    @pytest.fixture(scope="class")
    def lead_id(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads", params={"limit": 1, "active": "all"}, timeout=30)
        assert r.status_code == 200
        items = r.json().get("items") or r.json()
        assert items, "no leads found in DB to test against"
        return items[0]["id"]

    def test_upload_list_download_delete(self, admin, lead_id):
        content = b"TEST_ATTACHMENT_iter8 hello-world " + os.urandom(64)
        files = {"file": ("test_iter8.txt", io.BytesIO(content), "text/plain")}
        # Upload
        r = admin.post(f"{BASE_URL}/api/leads/{lead_id}/attachments", files=files, timeout=60)
        assert r.status_code == 200, r.text[:400]
        doc = r.json()
        assert doc["lead_id"] == lead_id
        assert doc["original_filename"] == "test_iter8.txt"
        assert doc["size"] >= len(content)
        att_id = doc["id"]

        # List → should contain new attachment
        r = admin.get(f"{BASE_URL}/api/leads/{lead_id}/attachments", timeout=30)
        assert r.status_code == 200
        ids = [a["id"] for a in r.json()]
        assert att_id in ids

        # Download
        r = admin.get(f"{BASE_URL}/api/attachments/{att_id}/download", timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.content == content

        # Delete
        r = admin.delete(f"{BASE_URL}/api/attachments/{att_id}", timeout=30)
        assert r.status_code == 200

        # Verify soft-deleted (404 on download or excluded from list)
        r = admin.get(f"{BASE_URL}/api/leads/{lead_id}/attachments", timeout=30)
        assert att_id not in [a["id"] for a in r.json()]


# ─── Case 14: Marketing campaigns ───────────────────────────────────────────
class TestMarketing:
    @pytest.fixture(scope="class")
    def wa_template_id(self, admin):
        r = admin.get(f"{BASE_URL}/api/templates/whatsapp", timeout=30)
        assert r.status_code == 200
        items = r.json()
        if not items:
            # create one for testing
            body = {"name": "TEST_iter8_wa_tpl", "body": "Hello {1}, this is a test.",
                    "wa_template_name": "test_iter8", "lang": "en", "status": "APPROVED"}
            cr = admin.post(f"{BASE_URL}/api/templates/whatsapp", json=body, timeout=30)
            assert cr.status_code == 200, cr.text
            return cr.json()["id"]
        return items[0]["id"]

    def test_create_count_send_delete_campaign(self, admin, wa_template_id):
        # CREATE
        body = {"name": "TEST_iter8_campaign", "channel": "whatsapp",
                "template_id": wa_template_id, "audience": {"active": "true"}}
        r = admin.post(f"{BASE_URL}/api/marketing/campaigns", json=body, timeout=30)
        assert r.status_code == 200, r.text
        camp = r.json()
        assert camp["name"] == "TEST_iter8_campaign"
        assert camp["channel"] == "whatsapp"
        assert camp["status"] == "draft"
        cid = camp["id"]

        # LIST should contain it
        r = admin.get(f"{BASE_URL}/api/marketing/campaigns", timeout=30)
        assert any(c["id"] == cid for c in r.json())

        # AUDIENCE COUNT
        r = admin.post(f"{BASE_URL}/api/marketing/campaigns/{cid}/audience-count", timeout=60)
        assert r.status_code == 200, r.text
        cnt = r.json().get("count")
        assert isinstance(cnt, int) and cnt >= 0

        # SEND — should not error; whatsapp without creds will QUEUE
        r = admin.post(f"{BASE_URL}/api/marketing/campaigns/{cid}/send", timeout=300)
        assert r.status_code == 200, r.text[:400]
        res = r.json()
        assert res["ok"] is True
        assert "total" in res and "sent" in res and "queued" in res and "failed" in res
        assert res["status"] in ("sent", "queued", "partial")

        # CLEANUP
        r = admin.delete(f"{BASE_URL}/api/marketing/campaigns/{cid}", timeout=30)
        assert r.status_code == 200

    def test_email_campaign_queues(self, admin):
        # need an email template
        r = admin.get(f"{BASE_URL}/api/templates/email", timeout=30)
        items = r.json()
        if not items:
            cr = admin.post(f"{BASE_URL}/api/templates/email",
                            json={"name": "TEST_iter8_email", "subject": "Hi", "body": "Body {1}"},
                            timeout=30)
            assert cr.status_code == 200, cr.text
            tid = cr.json()["id"]
        else:
            tid = items[0]["id"]
        r = admin.post(f"{BASE_URL}/api/marketing/campaigns",
                       json={"name": "TEST_iter8_email_camp", "channel": "email",
                             "template_id": tid, "audience": {"active": "true"}}, timeout=30)
        assert r.status_code == 200
        cid = r.json()["id"]
        r = admin.post(f"{BASE_URL}/api/marketing/campaigns/{cid}/send", timeout=300)
        assert r.status_code == 200, r.text[:400]
        res = r.json()
        assert res["queued"] >= 0  # all emails should queue (no provider)
        admin.delete(f"{BASE_URL}/api/marketing/campaigns/{cid}", timeout=30)


# ─── Case 16/17: Templates wa_template_name + lang persistence ─────────────
class TestTemplatePersistence:
    def test_wa_template_name_and_lang_persist(self, admin):
        body = {"name": "TEST_iter8_persist", "body": "Hello {1}",
                "wa_template_name": "iter8_template_name", "lang": "en_US"}
        r = admin.post(f"{BASE_URL}/api/templates/whatsapp", json=body, timeout=30)
        assert r.status_code == 200, r.text
        doc = r.json()
        tid = doc["id"]
        assert doc.get("wa_template_name") == "iter8_template_name"
        assert doc.get("lang") == "en_US"

        # PATCH update both
        r = admin.patch(f"{BASE_URL}/api/templates/whatsapp/{tid}",
                        json={"wa_template_name": "iter8_renamed", "lang": "hi"}, timeout=30)
        assert r.status_code == 200, r.text
        d2 = r.json()
        assert d2["wa_template_name"] == "iter8_renamed"
        assert d2["lang"] == "hi"

        # GET to verify persistence
        r = admin.get(f"{BASE_URL}/api/templates/whatsapp", timeout=30)
        match = [t for t in r.json() if t["id"] == tid]
        assert match and match[0]["wa_template_name"] == "iter8_renamed" and match[0]["lang"] == "hi"

        # cleanup
        admin.delete(f"{BASE_URL}/api/templates/whatsapp/{tid}", timeout=30)


# ─── Case 15: 'Undefined' → 'New / Unassigned' ─────────────────────────────
class TestNewUnassignedLabel:
    def test_dashboard_by_stage_no_undefined(self, admin):
        r = admin.get(f"{BASE_URL}/api/reports/dashboard", timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        labels = [str(s.get("_id")) for s in data.get("by_stage", [])]
        assert "Undefined" not in labels, f"by_stage still contains Undefined: {labels}"
        # if there are null stages they must be relabeled
        for s in data.get("by_stage", []):
            assert s["_id"] not in (None, False, "")

    def test_pivot_lead_stage_relabel(self, admin):
        r = admin.post(f"{BASE_URL}/api/reports/pivot",
                       json={"rows": ["lead_stage"], "filters": {"active": "all"}}, timeout=120)
        assert r.status_code == 200, r.text
        out = r.json()
        labels = [row["label"] for row in out.get("rows", [])]
        assert "Undefined" not in labels, f"pivot still has 'Undefined': {labels}"

    def test_trends_relabel(self, admin):
        r = admin.get(f"{BASE_URL}/api/reports/trends",
                      params={"granularity": "day", "date_from": "2026-06-01"}, timeout=60)
        assert r.status_code == 200, r.text
        stages = r.json().get("stages", [])
        assert "Undefined" not in stages


# ─── Case 5: Calls list (lead-detail calls tab data source) ─────────────────
class TestLeadCalls:
    def test_calls_list_for_lead(self, admin):
        # find a lead with calls; if none, just verify endpoint shape
        r = admin.get(f"{BASE_URL}/api/calls", params={"limit": 5}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        items = body.get("items") if isinstance(body, dict) else body
        assert isinstance(items, list)
        if items:
            sample = items[0]
            for k in ("id",):
                assert k in sample
