"""KPI Overview endpoint tests (iter59 — new stages/months/prev_month shape)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")

ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
AGENT = {"email": "agent@homeivf.com", "password": "Agent@2026"}

EXPECTED_ROWS = {
    "attempt": ["Ringing", "Busy", "Phone Switched Off", "Not Reachable"],
    "contacted": ["Call back for first pitch", "Call back for appointment", "OPD Booked"],
    "converted": ["OPD Done", "Registration Done", "Blood Test Booked", "Kits Booked", "Treatment Started"],
    "closed": [
        "Age Issue", "Duplicate Lead", "Already Have kid", "Already Pregnant",
        "Clinic Not Available", "Gender Selection", "Incoming Not Available", "Invalid Number",
        "Job Enquiry", "Junk", "Language Barrier", "Not Contactable",
        "Not Interested (Fund Issue)", "Not Interested (Competition)", "Not looking for treatment",
        "Relative Related Enquiry", "Sperm/Egg Donor", "Unmarried", "Valid Not Interested",
        "Wrong Number", "Abusive Language", "Not Eligible For Treatment",
    ],
}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN)


def _get(token, params=None):
    return requests.get(
        f"{BASE_URL}/api/reports/kpi-overview",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=60,
    )


def test_kpi_current_month_shape(admin_token):
    r = _get(admin_token)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["is_current"] is True
    assert d["day_label"] == "FTD"
    assert d["month_label"] == "MTD"
    for k in ("ftd", "mtd", "ytd"):
        assert isinstance(d["total"][k], int)
    # months array Jan..current
    assert isinstance(d["months"], list) and len(d["months"]) >= 1
    labels = [m["label"] for m in d["months"]]
    assert labels[0].startswith("Jan")
    # 4 stages with expected fixed rows
    assert len(d["stages"]) == 4
    stage_by_key = {s["key"]: s for s in d["stages"]}
    for key, rows in EXPECTED_ROWS.items():
        assert key in stage_by_key, f"missing stage {key}"
        got = [r["name"] for r in stage_by_key[key]["rows"]]
        assert got == rows, f"stage {key} rows mismatch: {got}"
    assert len(stage_by_key["closed"]["rows"]) == 22
    print("Totals:", d["total"])


def test_kpi_seeded_totals_nonzero(admin_token):
    d = _get(admin_token).json()
    # Seed says total mtd ~4067, ytd ~8127
    assert d["total"]["mtd"] >= 1000, d["total"]
    assert d["total"]["ytd"] >= 5000, d["total"]


def test_kpi_month_param_past(admin_token):
    r = _get(admin_token, {"month": "2026-06"})
    assert r.status_code == 200
    d = r.json()
    assert d["is_current"] is False
    assert d["day_label"] == "Avg/Day"
    assert d["month_label"] == "Month"
    assert d["days_in_month"] == 30
    assert d["month"] == "2026-06"
    pm = d["prev_month"]
    assert pm is not None
    assert pm["label"] == "May 2026"
    assert pm["days"] == 31
    assert "stage_totals" in pm and set(pm["stage_totals"].keys()) == {"attempt", "contacted", "converted", "closed"}


def test_kpi_month_january_prev_null(admin_token):
    d = _get(admin_token, {"month": "2026-01"}).json()
    assert d["is_current"] is False
    assert d["prev_month"] is None
    assert d["days_in_month"] == 31


def test_kpi_invalid_month_falls_back(admin_token):
    d = _get(admin_token, {"month": "foo"}).json()
    assert d["is_current"] is True
    assert d["day_label"] == "FTD"


def test_kpi_unauthenticated():
    r = requests.get(f"{BASE_URL}/api/reports/kpi-overview", timeout=15)
    assert r.status_code in (401, 403)
