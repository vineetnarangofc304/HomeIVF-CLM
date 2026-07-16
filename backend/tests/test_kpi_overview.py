"""KPI Overview endpoint tests (iter57)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ivf-pipeline.preview.emergentagent.com").rstrip("/")

ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
AGENT = {"email": "agent@homeivf.com", "password": "Agent@2026"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def agent_token():
    return _login(AGENT)


def test_kpi_admin_returns_200_and_shape(admin_token):
    r = requests.get(
        f"{BASE_URL}/api/reports/kpi-overview",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    # top-level shape
    for k in ("total", "sections", "conversion", "today", "month_start", "year_start"):
        assert k in d, f"missing key {k}"
    for k in ("ftd", "mtd", "ytd"):
        assert k in d["total"]
        assert isinstance(d["total"][k], int)
    # 5 sections
    assert len(d["sections"]) == 5
    keys = [s["key"] for s in d["sections"]]
    assert keys[0] == "valid"
    # normalised keys for the 4 stages
    expected_stage_keys = {"contactattempt", "contacted", "converted", "closed"}
    assert expected_stage_keys.issubset(set(keys))
    for s in d["sections"]:
        assert "title" in s and "color" in s and "rows" in s and "totals" in s
        for row in s["rows"]:
            for k in ("ftd", "mtd", "ytd", "label"):
                assert k in row
    # conversion has 4 items
    assert len(d["conversion"]) == 4
    for c in d["conversion"]:
        for k in ("label", "num", "den", "pct"):
            assert k in c
    print("TOTALS:", d["total"])
    print("VALID totals:", d["sections"][0]["totals"])
    print("CONV:", d["conversion"])


def test_kpi_seeded_test_data_counted(admin_token):
    r = requests.get(
        f"{BASE_URL}/api/reports/kpi-overview",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=60,
    )
    d = r.json()
    # Seeded expectations: ~5 FTD, ~18 MTD, ~23 YTD (plus pre-existing 2026 leads)
    assert d["total"]["ftd"] >= 5, f"expected FTD >=5, got {d['total']}"
    assert d["total"]["mtd"] >= 18, f"expected MTD >=18, got {d['total']}"
    assert d["total"]["ytd"] >= 23, f"expected YTD >=23, got {d['total']}"

    valid = d["sections"][0]
    assert valid["totals"]["mtd"] >= 5, f"expected valid mtd >=5, got {valid['totals']}"

    # BOTH int-id (Ringing=26) and string-name (Busy) tags should have rows > 0
    def find_row(label):
        for s in d["sections"]:
            for row in s["rows"]:
                if row["label"].lower() == label.lower():
                    return row
        return None

    ringing = find_row("Ringing")
    busy = find_row("Busy")
    assert ringing is not None, "Ringing row missing"
    assert busy is not None, "Busy row missing"
    assert ringing["ytd"] > 0, f"Ringing YTD should be >0, got {ringing}"
    assert busy["ytd"] > 0, f"Busy YTD should be >0 (string tag test), got {busy}"

    conv0 = d["conversion"][0]
    assert conv0["label"].startswith("Valid"), conv0
    # sensible pct — Valid MTD=5 and OPD Booked MTD ~= 2 -> ~40%
    assert 0 <= conv0["pct"] <= 100


def test_kpi_caller_forbidden(agent_token):
    r = requests.get(
        f"{BASE_URL}/api/reports/kpi-overview",
        headers={"Authorization": f"Bearer {agent_token}"},
        timeout=30,
    )
    assert r.status_code == 403, f"expected 403 for caller, got {r.status_code} {r.text}"


def test_kpi_unauthenticated():
    r = requests.get(f"{BASE_URL}/api/reports/kpi-overview", timeout=15)
    assert r.status_code in (401, 403)
