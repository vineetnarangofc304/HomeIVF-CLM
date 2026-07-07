import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ivf-crm-preview.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@homeivf.com"
ADMIN_PASS = "HomeIVF@2026"
CALLER_EMAIL = "caller1@homeivf.com"
CALLER_PASS = "HomeIVF@123"
MANAGER_EMAIL = "kishore@homeivf.com"
MANAGER_PASS = "HomeIVF@123"


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code == 200:
        tok = r.json().get("access_token")
        s.headers.update({"Authorization": f"Bearer {tok}"})
        return s, r.json()
    return None, r


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def admin_client():
    s, info = _login(ADMIN_EMAIL, ADMIN_PASS)
    if s is None:
        pytest.skip(f"Admin login failed: {info.status_code} {info.text}")
    return s


@pytest.fixture(scope="session")
def caller_client():
    s, info = _login(CALLER_EMAIL, CALLER_PASS)
    if s is None:
        pytest.skip(f"Caller login failed: {info.status_code} {info.text}")
    return s


@pytest.fixture(scope="session")
def caller_user():
    s, info = _login(CALLER_EMAIL, CALLER_PASS)
    if s is None:
        pytest.skip("Caller login failed")
    return info
