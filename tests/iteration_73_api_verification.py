#!/usr/bin/env python3
"""Focused bug verification for Iteration 73: Leads page constant 'Server is busy'.

This script exercises the production-like preview API through the public ingress.
It does not mutate product code. One PATCH regression check updates and then
restores a test lead's remark field.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path("/app")
FRONTEND_ENV = ROOT / "frontend" / ".env"
OUT = ROOT / "test_reports" / "iteration_73_api_results.json"


def env_value(path: Path, key: str, default: str = "") -> str:
    if not path.exists():
        return default
    for line in path.read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')
    return default


BASE = env_value(FRONTEND_ENV, "REACT_APP_BACKEND_URL", "https://homeivf-crm-2.preview.emergentagent.com")
API = BASE.rstrip("/") + "/api"


def login(email: str, password: str):
    s = requests.Session()
    t0 = time.perf_counter()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    elapsed = round((time.perf_counter() - t0) * 1000)
    record = {"name": f"login {email}", "status": r.status_code, "duration_ms": elapsed}
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text[:500]}
    token = data.get("access_token") if isinstance(data, dict) else None
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
        record["ok"] = True
        record["role"] = data.get("role")
    else:
        record["ok"] = False
        record["error"] = data
    return s, record


def get_leads(session, name, params, expect_items=True):
    p = {"bucket": "pipeline", "page": 1, "limit": 50, "sort": "create_date", "order": "desc", **params}
    t0 = time.perf_counter()
    try:
        r = session.get(f"{API}/leads", params=p, timeout=25)
        elapsed = round((time.perf_counter() - t0) * 1000)
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text[:500]}
        items = data.get("items", []) if isinstance(data, dict) else []
        total = data.get("total") if isinstance(data, dict) else None
        ok = r.status_code == 200 and (not expect_items or len(items) > 0)
        return {
            "name": name,
            "status": r.status_code,
            "duration_ms": elapsed,
            "item_count": len(items),
            "total": total,
            "params": p,
            "ok": ok,
            "detail": (data.get("detail") if isinstance(data, dict) else None),
            "first_id": items[0].get("id") if items else None,
            "sample": items[0] if items else None,
        }
    except Exception as e:
        return {"name": name, "params": p, "ok": False, "exception": repr(e)}


def api_call(session, method, path, **kwargs):
    t0 = time.perf_counter()
    r = session.request(method, f"{API}{path}", timeout=25, **kwargs)
    elapsed = round((time.perf_counter() - t0) * 1000)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text[:500]}
    return r.status_code, elapsed, data


def main():
    results = {
        "base_url": BASE,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "skill_lookup": "No relevant testing skill found.",
        "logins": [],
        "lead_list_cases": [],
        "count_decoupling": [],
        "lead_detail_api": [],
        "patch_regression": {},
        "verdict_basis": [],
    }

    admin, rec = login("admin@homeivf.com", "HomeIVF@2026")
    results["logins"].append(rec)
    caller, rec2 = login("caller16@homeivf.com", "TestPass@2026")
    results["logins"].append(rec2)
    if not rec.get("ok") or not rec2.get("ok"):
        results["overall_ok"] = False
        OUT.write_text(json.dumps(results, indent=2, default=str))
        print(json.dumps(results, indent=2, default=str))
        return 1

    # Admin default pipeline list: exact regression path for the bad hint.
    default = get_leads(admin, "admin default Leads in Pipeline (All)", {})
    results["lead_list_cases"].append(default)
    items = default.get("sample") and [default["sample"]] or []
    # Pull more rows to reliably find populated filter values without relying on catalogs alone.
    larger = get_leads(admin, "admin default sample page limit 200", {"limit": 200}, expect_items=True)
    sample_items = []
    if larger.get("ok") and larger.get("sample"):
        # Re-request directly to keep only one summary row above; capture all 200 from response here.
        r = admin.get(f"{API}/leads", params={"bucket": "pipeline", "page": 1, "limit": 200, "sort": "create_date", "order": "desc"}, timeout=25)
        if r.status_code == 200:
            sample_items = r.json().get("items", [])
    if not sample_items and default.get("sample"):
        sample_items = [default["sample"]]

    def first_nonempty(field):
        for it in sample_items:
            v = it.get(field)
            if v not in (None, "", False, []):
                return v
        return None

    lead_stage = first_nonempty("lead_stage")
    source = first_nonempty("source_lead")
    date_val = None
    for it in sample_items:
        cd = it.get("create_date_ist") or it.get("create_date")
        if cd:
            date_val = str(cd)[:10]
            break

    admin_cases = []
    if lead_stage:
        admin_cases.append(("admin lead_stage filter", {"lead_stage": lead_stage}))
    if source:
        admin_cases.append(("admin source filter", {"source_lead": source}))
    if date_val:
        admin_cases.append(("admin date range filter", {"date_from": date_val, "date_to": date_val}))
    for sort in ["contact_name", "phone", "create_date", "user_id"]:
        admin_cases.append((f"admin sort {sort}", {"sort": sort, "order": "desc"}))
    # Also hit the opposite direction because the create_date column toggles to ASC from the
    # default UI state and still exercises the hint path without relying on index names.
    for sort in ["contact_name", "phone", "create_date", "user_id"]:
        admin_cases.append((f"admin sort {sort} asc", {"sort": sort, "order": "asc"}))
    for page in [1, 2, 3]:
        admin_cases.append((f"admin pagination page {page}", {"page": page}))

    for name, params in admin_cases:
        results["lead_list_cases"].append(get_leads(admin, name, params))

    # Caller default My leads and All scope.
    results["lead_list_cases"].append(get_leads(caller, "caller default Leads in Pipeline (My leads)", {}))
    results["lead_list_cases"].append(get_leads(caller, "caller Leads in Pipeline (All) scope", {"scope": "all"}))

    # Count decoupling: use a populated source filter if possible; otherwise default list.
    count_params = {"source_lead": source} if source else {}
    first_count = get_leads(admin, "count decoupling first load", count_params)
    results["count_decoupling"].append(first_count)
    second_count = None
    for _ in range(5):
        time.sleep(1)
        second_count = get_leads(admin, "count decoupling repeat load", count_params)
        if isinstance(second_count.get("total"), int) and second_count["total"] >= 0:
            break
    results["count_decoupling"].append(second_count)

    # Lead core detail endpoints for the requested test leads.
    for lid in [500210, 600027]:
        st, ms, data = api_call(admin, "GET", f"/leads/{lid}")
        results["lead_detail_api"].append({
            "lead_id": lid,
            "status": st,
            "duration_ms": ms,
            "ok": st == 200 and isinstance(data, dict) and data.get("id") == lid,
            "name": data.get("contact_name") or data.get("name") if isinstance(data, dict) else None,
        })

    # PATCH regression: update then restore remark on lead 500210.
    st, ms, before = api_call(admin, "GET", "/leads/500210")
    original_remark = before.get("remark") if isinstance(before, dict) else None
    marker = f"QA iter73 patch regression {int(time.time())}"
    st1, ms1, patched = api_call(admin, "PATCH", "/leads/500210", json={"updates": {"remark": marker}})
    st2, ms2, after = api_call(admin, "GET", "/leads/500210")
    restored_status = None
    if st1 == 200:
        restored_status, _, _ = api_call(admin, "PATCH", "/leads/500210", json={"updates": {"remark": original_remark}})
    results["patch_regression"] = {
        "lead_id": 500210,
        "patch_status": st1,
        "patch_duration_ms": ms1,
        "get_after_status": st2,
        "restored_status": restored_status,
        "ok": st1 == 200 and st2 == 200 and isinstance(after, dict) and after.get("remark") == marker and restored_status == 200,
    }

    # Overall backend pass criteria for the reported bug.
    list_failures = [c for c in results["lead_list_cases"] if not c.get("ok") or c.get("status") == 504]
    detail_failures = [c for c in results["lead_detail_api"] if not c.get("ok")]
    count_ok = all(c and c.get("status") == 200 and c.get("item_count", 0) > 0 for c in results["count_decoupling"])
    count_ok = count_ok and isinstance(results["count_decoupling"][-1].get("total"), int) and results["count_decoupling"][-1].get("total") >= 0
    results["overall_ok"] = not list_failures and not detail_failures and count_ok and results["patch_regression"].get("ok")
    results["verdict_basis"] = [
        f"lead_list_failures={len(list_failures)}",
        f"detail_failures={len(detail_failures)}",
        f"count_decoupling_ok={count_ok}",
        f"patch_ok={results['patch_regression'].get('ok')}",
    ]
    OUT.write_text(json.dumps(results, indent=2, default=str))
    print(json.dumps(results, indent=2, default=str))
    return 0 if results["overall_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())