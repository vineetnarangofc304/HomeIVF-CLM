#!/usr/bin/env python3
"""Focused bug-verification checks for iteration 68.

Verifies /api/leads correctness/performance, global search, and the cross-caller
lead edit/assignment-lock regression using real preview APIs.
"""
import json
import os
import re
import time
from datetime import datetime, timezone

import requests


ROOT = "/app"
FRONTEND_ENV = os.path.join(ROOT, "frontend", ".env")


def read_backend_url():
    with open(FRONTEND_ENV, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.strip().split("=", 1)[1].strip().strip('"')
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


BASE = read_backend_url().rstrip("/") + "/api"
ADMIN = ("admin@homeivf.com", "HomeIVF@2026")
CALLER = ("caller16@homeivf.com", "TestPass@2026")  # Himani Sharma, id 8
LEAD_ID = 600027
SEARCH_PHONE = "5770614172"


def timed_request(session, method, path, **kwargs):
    t0 = time.perf_counter()
    resp = session.request(method, BASE + path, timeout=30, **kwargs)
    elapsed = time.perf_counter() - t0
    try:
        body = resp.json()
    except Exception:
        body = resp.text[:500]
    return resp, body, elapsed


def login(email, password):
    s = requests.Session()
    resp, body, elapsed = timed_request(s, "POST", "/auth/login", json={"email": email, "password": password})
    token = body.get("access_token") if isinstance(body, dict) else None
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s, resp.status_code, body, elapsed


def check_leads(session, label, params, expected_total=None, expected_len=None, max_seconds=2.0):
    resp, body, elapsed = timed_request(session, "GET", "/leads", params=params)
    items = body.get("items", []) if isinstance(body, dict) else []
    ok = resp.status_code == 200 and isinstance(body, dict)
    if expected_total is not None:
        ok = ok and body.get("total") == expected_total
    if expected_len is not None:
        ok = ok and len(items) == expected_len
    ok = ok and elapsed < max_seconds
    return {
        "label": label,
        "ok": ok,
        "status": resp.status_code,
        "elapsed_ms": round(elapsed * 1000, 1),
        "total": body.get("total") if isinstance(body, dict) else None,
        "item_count": len(items),
        "first_ids": [x.get("id") for x in items[:5]],
        "error": None if resp.status_code == 200 else body,
    }, body


def main():
    results = {"base": BASE, "started_at": datetime.now(timezone.utc).isoformat(), "checks": []}
    admin, st, body, elapsed = login(*ADMIN)
    results["checks"].append({"label": "admin login", "ok": st == 200, "status": st, "elapsed_ms": round(elapsed * 1000, 1), "user": body.get("email") if isinstance(body, dict) else None})
    caller, st, body, elapsed = login(*CALLER)
    results["checks"].append({"label": "caller login", "ok": st == 200, "status": st, "elapsed_ms": round(elapsed * 1000, 1), "user": body.get("email") if isinstance(body, dict) else None})

    # PERF-CORRECTNESS list matrix from review request.
    admin_p1, admin_body_p1 = check_leads(admin, "admin default pipeline list", {"bucket": "pipeline", "limit": 50}, expected_total=119813)
    results["checks"].append(admin_p1)
    caller_default, _ = check_leads(caller, "caller default own book", {"bucket": "pipeline", "limit": 50}, expected_total=5144)
    results["checks"].append(caller_default)
    caller_all, _ = check_leads(caller, "caller scope=all", {"bucket": "pipeline", "scope": "all", "limit": 50}, expected_total=119813)
    results["checks"].append(caller_all)
    admin_mine, _ = check_leads(admin, "admin scope=mine", {"bucket": "pipeline", "scope": "mine", "limit": 50}, expected_total=0, expected_len=0)
    results["checks"].append(admin_mine)
    admin_contacted, _ = check_leads(admin, "admin lead_stage=Contacted", {"bucket": "pipeline", "lead_stage": "Contacted", "limit": 50}, expected_total=24020)
    results["checks"].append(admin_contacted)
    admin_p3, admin_body_p3 = check_leads(admin, "admin page=3", {"bucket": "pipeline", "page": 3, "limit": 50}, expected_total=119813, expected_len=50)
    p1_ids = [x.get("id") for x in admin_body_p1.get("items", [])] if isinstance(admin_body_p1, dict) else []
    p3_ids = [x.get("id") for x in admin_body_p3.get("items", [])] if isinstance(admin_body_p3, dict) else []
    admin_p3["different_from_page1"] = bool(p1_ids and p3_ids and p1_ids != p3_ids)
    admin_p3["ok"] = admin_p3["ok"] and admin_p3["different_from_page1"]
    results["checks"].append(admin_p3)

    # group_counts speed on admin default pipeline list.
    for group_by in ["lead_stage", "user_id"]:
        resp, body, elapsed = timed_request(admin, "GET", "/leads/group_counts", params={"bucket": "pipeline", "group_by": group_by})
        results["checks"].append({
            "label": f"admin group_counts {group_by}",
            "ok": resp.status_code == 200 and isinstance(body, list) and len(body) > 0 and elapsed < 2.0,
            "status": resp.status_code,
            "elapsed_ms": round(elapsed * 1000, 1),
            "row_count": len(body) if isinstance(body, list) else None,
            "sample": body[:3] if isinstance(body, list) else body,
        })

    # Endpoints that were failing behind the slow /api/leads load should still fail-open/fast in preview.
    for label, sess, path, validator in [
        ("caller /agent/me poll", caller, "/agent/me", lambda b: isinstance(b, dict) and "status" in b),
        ("caller /calls/active poll", caller, "/calls/active", lambda b: isinstance(b, dict) and "active" in b),
        ("caller /whatsapp/unread-summary poll", caller, "/whatsapp/unread-summary", lambda b: isinstance(b, dict) and "total_unread" in b),
    ]:
        resp, body, elapsed = timed_request(sess, "GET", path)
        results["checks"].append({
            "label": label,
            "ok": resp.status_code == 200 and validator(body) and elapsed < 2.0,
            "status": resp.status_code,
            "elapsed_ms": round(elapsed * 1000, 1),
            "body_shape": list(body.keys()) if isinstance(body, dict) else type(body).__name__,
        })

    # Search must be global from caller default My Leads tab and find raw Ozonetel lead owned by another caller.
    resp, body, elapsed = timed_request(caller, "GET", "/leads", params={"bucket": "pipeline", "search": SEARCH_PHONE, "limit": 50})
    items = body.get("items", []) if isinstance(body, dict) else []
    found = next((x for x in items if x.get("id") == LEAD_ID), None)
    results["checks"].append({
        "label": "caller global search from default tab finds lead 600027",
        "ok": resp.status_code == 200 and found is not None and found.get("user_id") == 5,
        "status": resp.status_code,
        "elapsed_ms": round(elapsed * 1000, 1),
        "total": body.get("total") if isinstance(body, dict) else None,
        "ids": [x.get("id") for x in items[:10]],
        "found_user_id": found.get("user_id") if found else None,
        "found_pipeline": found.get("pipeline") if found else None,
    })

    # Cross-caller edit regression: patch city/stage and post a note as Himani (caller id 8), verify assignment unchanged.
    resp, before, elapsed = timed_request(caller, "GET", f"/leads/{LEAD_ID}")
    original_city = before.get("city") if isinstance(before, dict) else None
    original_stage = before.get("lead_stage") if isinstance(before, dict) else None
    new_city = f"QA City {int(time.time())}"
    new_stage = "Contacted" if original_stage != "Contacted" else "New"
    edit_ok = False
    note_ok = False
    verify_ok = False
    restore_ok = False
    audit_ok = False
    edit_detail = {}
    if resp.status_code == 200:
        resp_patch, patched, patch_elapsed = timed_request(caller, "PATCH", f"/leads/{LEAD_ID}", json={"updates": {"city": new_city, "lead_stage": new_stage, "user_id": 8, "original_user_id": 8}})
        edit_ok = resp_patch.status_code == 200 and patched.get("city") == new_city and patched.get("lead_stage") == new_stage and patched.get("user_id") == 5 and patched.get("original_user_id") == 5
        note_text = f"QA iteration 68 note by Himani {datetime.now(timezone.utc).isoformat()}"
        resp_note, note_body, note_elapsed = timed_request(caller, "POST", f"/leads/{LEAD_ID}/messages", json={"body": note_text, "subtype": "note"})
        note_ok = resp_note.status_code == 200 and note_body.get("author_name") == "Himani Sharma" and note_text in note_body.get("body", "")
        resp_verify, verified, verify_elapsed = timed_request(caller, "GET", f"/leads/{LEAD_ID}")
        verify_ok = resp_verify.status_code == 200 and verified.get("user_id") == 5 and verified.get("original_user_id") == 5 and verified.get("city") == new_city and verified.get("lead_stage") == new_stage
        resp_audit, audit, audit_elapsed = timed_request(caller, "GET", f"/leads/{LEAD_ID}/audit")
        recent_audit = audit[:10] if isinstance(audit, list) else []
        audit_ok = resp_audit.status_code == 200 and any(a.get("user_name") == "Himani Sharma" and a.get("field") in ["City", "Lead Stage"] for a in recent_audit)
        # Restore changed fields only, while leaving audit/note proof intact.
        restore_updates = {"city": original_city, "lead_stage": original_stage}
        resp_restore, restored, restore_elapsed = timed_request(caller, "PATCH", f"/leads/{LEAD_ID}", json={"updates": restore_updates})
        restore_ok = resp_restore.status_code == 200 and restored.get("user_id") == 5 and restored.get("original_user_id") == 5
        edit_detail = {
            "before_user_id": before.get("user_id"), "before_original_user_id": before.get("original_user_id"),
            "patch_status": resp_patch.status_code, "patch_elapsed_ms": round(patch_elapsed * 1000, 1),
            "post_note_status": resp_note.status_code, "note_elapsed_ms": round(note_elapsed * 1000, 1),
            "verify_status": resp_verify.status_code, "verify_elapsed_ms": round(verify_elapsed * 1000, 1),
            "audit_status": resp_audit.status_code, "audit_elapsed_ms": round(audit_elapsed * 1000, 1),
            "restore_status": resp_restore.status_code, "restore_elapsed_ms": round(restore_elapsed * 1000, 1),
            "recent_audit_sample": recent_audit[:3],
        }
    results["checks"].append({
        "label": "caller edits lead 600027 while assignment remains locked",
        "ok": edit_ok and note_ok and verify_ok and audit_ok and restore_ok,
        "edit_ok": edit_ok,
        "note_ok": note_ok,
        "verify_ok": verify_ok,
        "audit_ok": audit_ok,
        "restore_ok": restore_ok,
        **edit_detail,
    })

    results["passed"] = sum(1 for c in results["checks"] if c.get("ok"))
    results["total"] = len(results["checks"])
    results["ok"] = results["passed"] == results["total"]
    with open("/app/test_reports/iteration_68_api_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(json.dumps(results, indent=2, default=str))
    raise SystemExit(0 if results["ok"] else 1)


if __name__ == "__main__":
    main()