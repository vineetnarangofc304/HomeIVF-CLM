#!/usr/bin/env python3
"""Seeded caller-scope regression check.

Creates two temporary leads with the same lead_stage+tag filter, one assigned to
caller16 (id 8) and one to another caller (id 5). As caller16, /api/leads with
that filter must return only the own lead. The temporary leads are archived at
the end via bulk action.
"""

import json
import random
import time
from pathlib import Path

import requests

BASE = "https://homeivf-crm-2.preview.emergentagent.com/api"
OUT = Path("/app/test_reports/iteration_74_seeded_caller_scope.json")


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def auth_post(token, path, payload):
    r = requests.post(f"{BASE}{path}", json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=20)
    r.raise_for_status()
    return r.json()


def main():
    admin = login("admin@homeivf.com", "HomeIVF@2026")
    caller = login("caller16@homeivf.com", "TestPass@2026")
    suffix = random.randint(100000, 999999)
    created = []
    try:
        for owner, label in [(8, "own"), (5, "other")]:
            created.append(auth_post(admin, "/leads", {
                "contact_name": f"ITER74 Caller Scope {label} {suffix}",
                "phone": f"9907{suffix % 1000000:06d}{owner % 10}",
                "lead_stage": "Contacted",
                "tags": [32],
                "user_id": owner,
                "source_lead": "Website AI Agent",
            }))
        params = {"bucket": "pipeline", "lead_stage": "Contacted", "tags": "32", "sort": "create_date", "order": "desc", "limit": 200}
        st = time.perf_counter()
        r = requests.get(f"{BASE}/leads", params=params, headers={"Authorization": f"Bearer {caller}"}, timeout=25)
        duration_ms = int((time.perf_counter() - st) * 1000)
        data = r.json()
        ids = [it.get("id") for it in data.get("items", [])]
        created_ids = [c["id"] for c in created]
        own_id = created[0]["id"]
        other_id = created[1]["id"]
        result = {
            "status": r.status_code,
            "duration_ms": duration_ms,
            "params": params,
            "created_ids": created_ids,
            "own_id": own_id,
            "other_id": other_id,
            "returned_created_ids": [i for i in ids if i in created_ids],
            "scope_ok": r.status_code == 200 and own_id in ids and other_id not in ids,
            "items_len": len(data.get("items", [])),
            "first_user_ids": [it.get("user_id") for it in data.get("items", [])[:10]],
        }
    finally:
        if created:
            try:
                auth_post(admin, "/leads/bulk", {"ids": [c["id"] for c in created], "action": "archive", "payload": {}})
            except Exception as e:
                result = locals().get("result", {})
                result["cleanup_error"] = repr(e)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result.get("scope_ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()