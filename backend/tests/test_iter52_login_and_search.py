"""
Iteration 52 tests:
- Login stability (no 500s) for admin and caller
- Lead search: case-insensitive prefix, fast, correct
- Create/update propagates to search (name_lc)
- Regression: default list, buckets, sort/filter
"""
import os
import time
import uuid
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
CALLER = {"email": "agent@homeivf.com", "password": "Agent@2026"}


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=20)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data
    return data["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------- Auth ----------
class TestAuth:
    def test_admin_login_no_500(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("access_token")

    def test_auth_me_admin(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("email") == ADMIN["email"]

    def test_caller_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=CALLER, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json().get("access_token")

    def test_repeated_logins_stable(self):
        # Basic stability check: 10 sequential logins must not produce a 500
        for i in range(10):
            r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=20)
            assert r.status_code == 200, f"login #{i} => {r.status_code} {r.text}"


# ---------- Search ----------
class TestLeadSearch:
    def test_default_list_fast(self, admin_headers):
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/leads", headers=admin_headers, timeout=20)
        dt = time.time() - t0
        assert r.status_code == 200, r.text
        j = r.json()
        assert "items" in j and "total" in j
        assert dt < 3.0, f"default list too slow: {dt:.2f}s"

    def test_search_case_insensitive_same_results(self, admin_headers):
        results = {}
        for term in ["dha", "Dha", "DHA"]:
            t0 = time.time()
            r = requests.get(
                f"{BASE_URL}/api/leads",
                headers=admin_headers,
                params={"search": term, "limit": 50},
                timeout=20,
            )
            dt = time.time() - t0
            assert r.status_code == 200, r.text
            assert dt < 2.0, f"search '{term}' too slow: {dt:.2f}s"
            j = r.json()
            ids = sorted([str(x.get("id") or x.get("_id")) for x in j.get("items", [])])
            results[term] = (ids, j.get("total"))
        # All three should return the same set
        assert results["dha"][0] == results["Dha"][0] == results["DHA"][0], (
            f"case-insensitivity broken: {results}"
        )
        assert results["dha"][1] == results["Dha"][1] == results["DHA"][1]
        # Should have at least one match if seeded name 'Dhananjay Rai' exists
        # (soft assert — only warn if empty)
        if not results["dha"][0]:
            pytest.skip("No 'dha' prefix leads found — seed may differ")

    def test_search_phone(self, admin_headers):
        # First fetch any lead to get a phone number
        r = requests.get(f"{BASE_URL}/api/leads?limit=50", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        items = r.json().get("items", [])
        phone = None
        for it in items:
            for k in ("phone", "mobile", "contact_phone"):
                v = it.get(k)
                if v and str(v).strip():
                    phone = "".join(ch for ch in str(v) if ch.isdigit())
                    if len(phone) >= 6:
                        break
            if phone:
                break
        if not phone:
            pytest.skip("No phone found in sample leads")
        t0 = time.time()
        r = requests.get(
            f"{BASE_URL}/api/leads",
            headers=admin_headers,
            params={"search": phone[:6]},
            timeout=20,
        )
        dt = time.time() - t0
        assert r.status_code == 200, r.text
        assert dt < 2.0, f"phone search slow: {dt:.2f}s"

    def test_create_lead_appears_in_search(self, admin_headers):
        unique = f"Zztestlead{uuid.uuid4().hex[:8]}"
        payload = {
            "name": f"{unique} Kumar",
            "contact_name": f"{unique} Kumar",
            "phone": "9990001111",
            "email_from": f"mailz{uuid.uuid4().hex[:8]}@example.com",
        }
        r = requests.post(
            f"{BASE_URL}/api/leads", json=payload, headers=admin_headers, timeout=20
        )
        assert r.status_code in (200, 201), r.text
        lead = r.json()
        lead_id = lead.get("id") or lead.get("_id")
        assert lead_id, lead

        # Search by prefix (mixed case)
        prefix = unique[:6].upper()
        r = requests.get(
            f"{BASE_URL}/api/leads",
            headers=admin_headers,
            params={"search": prefix},
            timeout=20,
        )
        assert r.status_code == 200
        ids = [str(x.get("id") or x.get("_id")) for x in r.json().get("items", [])]
        assert str(lead_id) in ids, f"new lead {lead_id} not found searching {prefix}"

        # Update name and search by new prefix
        new_unique = f"Yynewname{uuid.uuid4().hex[:8]}"
        pr = requests.patch(
            f"{BASE_URL}/api/leads/{lead_id}",
            json={"updates": {"name": f"{new_unique} Kumar", "contact_name": f"{new_unique} Kumar"}},
            headers=admin_headers,
            timeout=20,
        )
        assert pr.status_code == 200, pr.text

        r_new = requests.get(
            f"{BASE_URL}/api/leads",
            headers=admin_headers,
            params={"search": new_unique[:6].lower()},
            timeout=20,
        )
        assert r_new.status_code == 200
        ids_new = [str(x.get("id") or x.get("_id")) for x in r_new.json().get("items", [])]
        assert str(lead_id) in ids_new, "lead not searchable under new name"

        # Old prefix should NOT return it anymore
        r_old = requests.get(
            f"{BASE_URL}/api/leads",
            headers=admin_headers,
            params={"search": unique[:6]},
            timeout=20,
        )
        ids_old = [str(x.get("id") or x.get("_id")) for x in r_old.json().get("items", [])]
        assert str(lead_id) not in ids_old, "lead still found under old name — name_lc not updated"

        # Archive test lead
        try:
            requests.post(
                f"{BASE_URL}/api/leads/{lead_id}/lost", json={}, headers=admin_headers, timeout=20
            )
        except Exception:
            pass


# ---------- Regression ----------
class TestRegression:
    def test_pipeline_bucket(self, admin_headers):
        t0 = time.time()
        r = requests.get(
            f"{BASE_URL}/api/leads?bucket=pipeline", headers=admin_headers, timeout=20
        )
        dt = time.time() - t0
        assert r.status_code == 200, r.text
        assert dt < 3.0

    def test_ozonetel_bucket(self, admin_headers):
        t0 = time.time()
        r = requests.get(
            f"{BASE_URL}/api/leads?bucket=ozonetel", headers=admin_headers, timeout=20
        )
        dt = time.time() - t0
        assert r.status_code == 200, r.text
        assert dt < 3.0

    def test_sort_and_filter(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/leads",
            headers=admin_headers,
            params={"sort": "create_date", "order": "desc", "limit": 10},
            timeout=20,
        )
        assert r.status_code == 200, r.text
