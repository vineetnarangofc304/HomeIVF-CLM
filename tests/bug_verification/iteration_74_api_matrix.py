#!/usr/bin/env python3
"""Focused verification for Leads tag+stage 504 / pool-exhaustion regression.

Runs real preview API calls with admin and caller credentials, checks the new
compound index exists, verifies hinted explain plans for the exact admin/all
tag+stage query, exercises the requested filter matrix, and runs a small
concurrency/cascade probe against /leads plus related polled endpoints.
"""

import concurrent.futures
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests


ROOT = Path("/app")
OUT = ROOT / "test_reports" / "iteration_74_api_results.json"
FRONTEND_ENV = ROOT / "frontend" / ".env"

ADMIN = {"email": "admin@homeivf.com", "password": "HomeIVF@2026"}
CALLER = {"email": "caller16@homeivf.com", "password": "TestPass@2026"}


def read_base_url() -> str:
    for line in FRONTEND_ENV.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


BASE = read_base_url()
API = BASE + "/api"


def login(creds):
    started = time.perf_counter()
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    dur = int((time.perf_counter() - started) * 1000)
    r.raise_for_status()
    token = r.json()["access_token"]
    return token, r.json(), dur


def get(token, path, params=None, timeout=25):
    url = f"{API}{path}"
    started = time.perf_counter()
    try:
        r = requests.get(url, params=params or {}, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
        dur = int((time.perf_counter() - started) * 1000)
        payload = None
        try:
            payload = r.json()
        except Exception:
            payload = r.text[:300]
        return {
            "path": path,
            "params": params or {},
            "url": r.url,
            "status": r.status_code,
            "duration_ms": dur,
            "ok": r.status_code == 200 and dur < 10000,
            "payload_summary": summarize_payload(payload),
            "error": None if r.status_code == 200 else payload,
        }
    except Exception as e:
        dur = int((time.perf_counter() - started) * 1000)
        return {
            "path": path,
            "params": params or {},
            "url": url + ("?" + urlencode(params or {}) if params else ""),
            "status": None,
            "duration_ms": dur,
            "ok": False,
            "payload_summary": None,
            "error": repr(e),
        }


def summarize_payload(payload):
    if isinstance(payload, dict) and "items" in payload:
        items = payload.get("items") or []
        return {
            "items_len": len(items),
            "total": payload.get("total"),
            "page": payload.get("page"),
            "limit": payload.get("limit"),
            "first_ids": [it.get("id") for it in items[:5] if isinstance(it, dict)],
            "first_user_ids": [it.get("user_id") for it in items[:5] if isinstance(it, dict)],
        }
    if isinstance(payload, dict):
        return {k: payload.get(k) for k in list(payload.keys())[:8]}
    if isinstance(payload, list):
        return {"list_len": len(payload), "first": payload[:2]}
    return str(payload)[:250]


def check_index_and_explain():
    result = {"checked": False, "index_present": False, "explain": {}, "error": None}
    try:
        from dotenv import load_dotenv
        from pymongo import MongoClient

        load_dotenv(ROOT / "backend" / ".env")
        client = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)
        coll = client[os.environ["DB_NAME"]].leads
        target = [("active", 1), ("lead_stage", 1), ("tags", 1), ("create_date", -1), ("id", -1)]
        indexes = list(coll.list_indexes())
        result["checked"] = True
        result["index_present"] = any(list(ix.get("key", {}).items()) == target for ix in indexes)

        def stages(plan):
            out = []
            if isinstance(plan, dict):
                if "stage" in plan:
                    out.append(plan["stage"])
                for v in plan.values():
                    out.extend(stages(v))
            elif isinstance(plan, list):
                for v in plan:
                    out.extend(stages(v))
            return out

        projection = {"_id": 0, "id": 1, "lead_stage": 1, "tags": 1, "create_date": 1}
        cases = {
            "single_tag_contacted_32_desc": {"active": True, "pipeline": {"$ne": False}, "lead_stage": "Contacted", "tags": {"$in": [32]}},
            "multi_tag_contacted_32_33_26_desc": {"active": True, "pipeline": {"$ne": False}, "lead_stage": "Contacted", "tags": {"$in": [32, 33, 26]}},
        }
        for name, query in cases.items():
            exp = coll.find(query, projection).sort([("create_date", -1), ("id", -1)]).hint(target).limit(50).explain()
            st = stages(exp.get("queryPlanner", {}).get("winningPlan", {}))
            result["explain"][name] = {
                "stages": st,
                "has_blocking_sort_stage": "SORT" in st,
                "has_ixscan": "IXSCAN" in st,
            }
    except Exception as e:
        result["error"] = repr(e)
    return result


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    started_utc = (datetime.now(timezone.utc) - timedelta(seconds=2)).strftime("%Y-%m-%d %H:%M:%S")
    results = {
        "base_url": BASE,
        "started_utc": started_utc,
        "auth": {},
        "index_and_explain": check_index_and_explain(),
        "admin_matrix": [],
        "caller_scope": {},
        "concurrency_cascade": {},
        "error_logs_after": {},
        "overall_pass": False,
    }

    admin_token, admin_user, admin_login_ms = login(ADMIN)
    caller_token, caller_user, caller_login_ms = login(CALLER)
    results["auth"] = {
        "admin": {"id": admin_user.get("id"), "role": admin_user.get("role"), "login_ms": admin_login_ms},
        "caller": {"id": caller_user.get("id"), "role": caller_user.get("role"), "login_ms": caller_login_ms},
    }

    admin_cases = [
        ("default_pipeline_all_desc", {"bucket": "pipeline", "scope": "all", "sort": "create_date", "order": "desc"}),
        ("lead_stage_contacted_desc", {"bucket": "pipeline", "scope": "all", "lead_stage": "Contacted", "sort": "create_date", "order": "desc"}),
        ("lead_stage_converted_desc", {"bucket": "pipeline", "scope": "all", "lead_stage": "Converted", "sort": "create_date", "order": "desc"}),
        ("lead_stage_contact_attempt_desc", {"bucket": "pipeline", "scope": "all", "lead_stage": "Contact Attempt", "sort": "create_date", "order": "desc"}),
        ("tags_32_alone", {"bucket": "pipeline", "scope": "all", "tags": "32", "sort": "create_date", "order": "desc"}),
        ("exact_repro_contacted_tag32_desc_p1", {"bucket": "pipeline", "scope": "all", "lead_stage": "Contacted", "tags": "32", "sort": "create_date", "order": "desc", "page": 1}),
        ("exact_repro_contacted_tag32_desc_p2", {"bucket": "pipeline", "scope": "all", "lead_stage": "Contacted", "tags": "32", "sort": "create_date", "order": "desc", "page": 2}),
        ("exact_repro_contacted_tag32_desc_p3", {"bucket": "pipeline", "scope": "all", "lead_stage": "Contacted", "tags": "32", "sort": "create_date", "order": "desc", "page": 3}),
        ("fallback_contacted_tag32_asc", {"bucket": "pipeline", "scope": "all", "lead_stage": "Contacted", "tags": "32", "sort": "create_date", "order": "asc"}),
        ("multi_tag_contacted_desc", {"bucket": "pipeline", "scope": "all", "lead_stage": "Contacted", "tags": "32,33,26", "sort": "create_date", "order": "desc"}),
        ("stage_tag_followup_reported_case", {"bucket": "pipeline", "scope": "all", "lead_stage": "Contact Attempt", "tags": "26", "follow_up_tag": "Follow UP 1", "sort": "create_date", "order": "desc"}),
        ("stage_tag_followup_contacted", {"bucket": "pipeline", "scope": "all", "lead_stage": "Contacted", "tags": "32", "follow_up_tag": "Follow UP 1", "sort": "create_date", "order": "desc"}),
        ("stage_source_filter", {"bucket": "pipeline", "scope": "all", "lead_stage": "Contacted", "source_lead": "Website AI Agent", "sort": "create_date", "order": "desc"}),
        ("stage_date_range", {"bucket": "pipeline", "scope": "all", "lead_stage": "Contacted", "date_from": "2020-01-01", "date_to": "2026-12-31", "sort": "create_date", "order": "desc"}),
    ]
    for name, params in admin_cases:
        rec = get(admin_token, "/leads", params=params)
        rec["case"] = name
        results["admin_matrix"].append(rec)

    # Caller My-leads: first verify default page is scoped, then exercise a filtered query.
    caller_default = get(caller_token, "/leads", params={"bucket": "pipeline", "limit": 200, "sort": "create_date", "order": "desc"})
    caller_filtered_required = get(caller_token, "/leads", params={"bucket": "pipeline", "lead_stage": "Contacted", "tags": "32", "sort": "create_date", "order": "desc"})
    caller_user_id = caller_user.get("id")
    caller_default_items = []
    try:
        caller_default_items = requests.get(
            f"{API}/leads",
            params={"bucket": "pipeline", "limit": 200, "sort": "create_date", "order": "desc"},
            headers={"Authorization": f"Bearer {caller_token}"},
            timeout=25,
        ).json().get("items", [])
    except Exception:
        caller_default_items = []
    positive_params = None
    for item in caller_default_items:
        if item.get("lead_stage") and item.get("tags"):
            positive_params = {"bucket": "pipeline", "lead_stage": item["lead_stage"], "tags": str(item["tags"][0]), "sort": "create_date", "order": "desc"}
            break
    caller_positive = get(caller_token, "/leads", params=positive_params) if positive_params else None
    results["caller_scope"] = {
        "caller_user_id": caller_user_id,
        "default": caller_default,
        "required_contacted_tag32": caller_filtered_required,
        "positive_scoped_params": positive_params,
        "positive_scoped_result": caller_positive,
    }

    # Concurrency/cascade probe: the historic failure showed /leads 504s and polled endpoints
    # hanging/503ing behind the slow query. This keeps load bounded but verifies no 504 cascade.
    concurrent_jobs = []
    exact_params = {"bucket": "pipeline", "scope": "all", "lead_stage": "Contacted", "tags": "32", "sort": "create_date", "order": "desc"}
    for i in range(24):
        concurrent_jobs.append((f"leads_exact_{i+1}", "/leads", exact_params, 25))
    for i in range(4):
        concurrent_jobs.append((f"whatsapp_unread_{i+1}", "/whatsapp/unread-summary", {}, 25))
        concurrent_jobs.append((f"calls_active_{i+1}", "/calls/active", {}, 25))
    concurrent_jobs.append(("reports_dashboard_kpis", "/reports/dashboard", {"section": "kpis"}, 25))
    concurrent_jobs.append(("reports_dashboard_panels", "/reports/dashboard", {"section": "panels"}, 30))

    started = time.perf_counter()
    conc_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futs = {pool.submit(get, admin_token, path, params, timeout): name for name, path, params, timeout in concurrent_jobs}
        for fut in concurrent.futures.as_completed(futs):
            rec = fut.result()
            rec["case"] = futs[fut]
            conc_results.append(rec)
    results["concurrency_cascade"] = {
        "total_duration_ms": int((time.perf_counter() - started) * 1000),
        "results": sorted(conc_results, key=lambda r: r["case"]),
        "status_counts": {},
    }
    for rec in conc_results:
        key = str(rec["status"])
        results["concurrency_cascade"]["status_counts"][key] = results["concurrency_cascade"]["status_counts"].get(key, 0) + 1

    # Check app System Health logs created after this run for new /api/leads 5xx/slow entries.
    logs = get(admin_token, "/admin/error-logs", params={"limit": 300})
    recent_bad_leads = []
    if logs["status"] == 200:
        try:
            raw = requests.get(f"{API}/admin/error-logs", params={"limit": 300}, headers={"Authorization": f"Bearer {admin_token}"}, timeout=15).json()["logs"]
            for l in raw:
                if l.get("ts", "") >= started_utc and l.get("path") == "/api/leads" and int(l.get("status") or 0) >= 500:
                    recent_bad_leads.append({k: l.get(k) for k in ("ts", "kind", "path", "status", "duration_ms", "query")})
        except Exception as e:
            recent_bad_leads.append({"error_reading_logs": repr(e)})
    results["error_logs_after"] = {"query_status": logs["status"], "recent_bad_leads_5xx": recent_bad_leads}

    all_records = results["admin_matrix"] + [caller_default, caller_filtered_required] + ([caller_positive] if caller_positive else []) + conc_results
    caller_scope_ok = True
    for res in [caller_default, caller_filtered_required] + ([caller_positive] if caller_positive else []):
        summary = res.get("payload_summary") or {}
        first_user_ids = summary.get("first_user_ids") or []
        if any(uid not in (None, caller_user_id) for uid in first_user_ids):
            caller_scope_ok = False
    results["overall_pass"] = (
        results["auth"]["admin"]["role"] == "admin"
        and results["auth"]["caller"]["role"] == "caller"
        and results["index_and_explain"].get("index_present") is True
        and all(not v.get("has_blocking_sort_stage") and v.get("has_ixscan") for v in results["index_and_explain"].get("explain", {}).values())
        and all(r.get("status") == 200 and r.get("duration_ms", 999999) < 10000 for r in all_records)
        and caller_scope_ok
        and not recent_bad_leads
    )

    OUT.write_text(json.dumps(results, indent=2, sort_keys=True))
    print(json.dumps({
        "overall_pass": results["overall_pass"],
        "admin_cases": len(results["admin_matrix"]),
        "concurrency_status_counts": results["concurrency_cascade"]["status_counts"],
        "index_present": results["index_and_explain"].get("index_present"),
        "output": str(OUT),
    }, indent=2))
    if not results["overall_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()