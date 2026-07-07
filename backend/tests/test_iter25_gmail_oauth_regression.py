"""Iteration 25 — Gmail OAuth scope-relax fix + RBAC/follow-ups regression."""
import os
import sys
import subprocess
from urllib.parse import urlparse, parse_qs

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ivf-crm-preview.preview.emergentagent.com").rstrip("/")
# Load from frontend .env if not set
try:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
except Exception:
    pass

ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
CALLER = {"email": "agent@homeivf.com", "password": "Agent@2026"}


def _login(creds):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def admin():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def caller():
    return _login(CALLER)


# -------------------- Gmail OAuth tests --------------------

class TestGmailAuthUrl:
    def test_auth_url_requires_admin(self):
        r = requests.get(f"{BASE_URL}/api/admin/gmail/auth-url", params={"origin": BASE_URL}, timeout=15)
        assert r.status_code in (401, 403)

    def test_auth_url_returns_google_url_with_correct_redirect_and_scopes(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/gmail/auth-url", params={"origin": BASE_URL}, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "url" in data
        url = data["url"]
        assert url.startswith("https://accounts.google.com/"), f"unexpected auth url: {url}"
        q = parse_qs(urlparse(url).query)
        assert q.get("redirect_uri", [""])[0] == f"{BASE_URL}/api/oauth/gmail/callback"
        scope_str = q.get("scope", [""])[0]
        assert "https://www.googleapis.com/auth/gmail.send" in scope_str
        assert "openid" in scope_str
        assert "userinfo.email" in scope_str
        assert q.get("access_type", [""])[0] == "offline"
        assert q.get("prompt", [""])[0] == "consent"


class TestGmailCallback:
    def test_callback_error_surfaces_reason(self):
        r = requests.get(f"{BASE_URL}/api/oauth/gmail/callback",
                         params={"error": "access_denied", "error_description": "test"},
                         allow_redirects=False, timeout=15)
        assert r.status_code in (302, 307)
        loc = r.headers.get("location", "")
        assert "gmail=error" in loc
        assert "reason=test" in loc, f"reason not surfaced: {loc}"

    def test_callback_bad_state_redirects_badstate(self):
        r = requests.get(f"{BASE_URL}/api/oauth/gmail/callback",
                         params={"code": "bogus_code_xyz", "state": "nonexistent_state_xyz"},
                         allow_redirects=False, timeout=15)
        assert r.status_code in (302, 307)
        loc = r.headers.get("location", "")
        assert "gmail=badstate" in loc, f"expected badstate, got: {loc}"


class TestOauthlibScopeRelaxation:
    """Verify that importing core.gmail_send sets the OAUTHLIB relax flags."""

    def test_oauthlib_env_flags_set_on_import(self):
        script = (
            "import os, sys;"
            "sys.path.insert(0, '/app/backend');"
            "os.environ.pop('OAUTHLIB_RELAX_TOKEN_SCOPE', None);"
            "os.environ.pop('OAUTHLIB_IGNORE_SCOPE_CHANGE', None);"
            "from dotenv import load_dotenv;"
            "load_dotenv('/app/backend/.env');"
            "import core.gmail_send;"
            "print(os.environ.get('OAUTHLIB_RELAX_TOKEN_SCOPE'), os.environ.get('OAUTHLIB_IGNORE_SCOPE_CHANGE'))"
        )
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                              cwd="/app/backend", timeout=30)
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        out = proc.stdout.strip()
        assert out == "1 1", f"expected '1 1', got '{out}'"


# -------------------- RBAC regression --------------------

class TestRBACRegression:
    def test_admin_login_permissions(self, admin):
        r = admin.get(f"{BASE_URL}/api/auth/me", timeout=15)
        assert r.status_code == 200
        me = r.json()
        assert me.get("role") == "admin"
        perms = me.get("permissions") or {}
        assert isinstance(perms, dict) and len(perms) > 0

    def test_role_permissions_matrix(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/role-permissions", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        matrix = data.get("matrix", data)
        assert any(k in matrix for k in ("admin", "manager", "caller"))
        assert isinstance(matrix.get("admin"), dict) and len(matrix["admin"]) > 0

    def test_caller_forbidden_pivot(self, caller):
        r = caller.post(f"{BASE_URL}/api/reports/pivot", json={"rows": ["status"]}, timeout=15)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"

    def test_caller_forbidden_export_leads(self, caller):
        r = caller.get(f"{BASE_URL}/api/export/leads.xlsx", timeout=15)
        assert r.status_code == 403, f"expected 403, got {r.status_code}"


# -------------------- Follow-ups regression --------------------

class TestFollowupsRegression:
    def test_followups_crud(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads", timeout=20)
        assert r.status_code == 200
        items = r.json().get("items") or r.json()
        if isinstance(items, dict):
            items = items.get("items", [])
        assert len(items) > 0, "need at least one lead"
        lead_id = items[0]["id"]

        # POST
        r = admin.post(f"{BASE_URL}/api/leads/{lead_id}/followups",
                       json={"note": "TEST_iter25 followup", "when": "2026-02-01T10:00:00Z"}, timeout=15)
        assert r.status_code in (200, 201), r.text
        fu = r.json()
        fu_id = fu.get("id")
        assert fu_id is not None

        # GET
        r = admin.get(f"{BASE_URL}/api/leads/{lead_id}/followups", timeout=15)
        assert r.status_code == 200
        lst = r.json()
        assert any(x.get("id") == fu_id for x in lst)

        # PATCH
        r = admin.patch(f"{BASE_URL}/api/leads/{lead_id}/followups/{fu_id}",
                        json={"note": "TEST_iter25 updated"}, timeout=15)
        assert r.status_code == 200, r.text

        # DELETE
        r = admin.delete(f"{BASE_URL}/api/leads/{lead_id}/followups/{fu_id}", timeout=15)
        assert r.status_code in (200, 204)


# -------------------- Core endpoints --------------------

class TestCoreEndpoints:
    def test_leads_list(self, admin):
        r = admin.get(f"{BASE_URL}/api/leads", timeout=20)
        assert r.status_code == 200

    def test_admin_settings(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/settings", timeout=15)
        assert r.status_code == 200
