#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: special_value + resource_limit (strategy 4 + 6)
Constraint: qdrant_state_aliases_update_001
Endpoint: POST /collections/aliases (contract path: aliases+update)
exploration_target: novel_candidate
Block: chunk_aliases+update
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
doc_version: 1.18.x (versioned)
"""

import requests
import json
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")


def safe_request(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else {}
        except (json.JSONDecodeError, ValueError):
            print(f"JSON_DECODE_ERROR: {text[:200]}")
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""


def cleanup():
    try:
        safe_request("DELETE", "/collections/bnd_ali_sv_c1")
    except Exception:
        pass
    try:
        safe_request("POST", "/collections/aliases",
                     json={"actions": [{"delete_alias": {"alias": "bnd_ali_sv_x"}}]})
    except Exception:
        pass


def test_special_values():
    # setup
    s, _, raw = safe_request("PUT", "/collections/bnd_ali_sv_c1",
                             json={"vectors": {"size": 4, "distance": "Cosine"}})
    setup_ok = s in (200, 201)
    if not setup_ok:
        print(f"setup failed: {s} {raw[:200]}")

    cases = [
        ("alias=unicode", "中文测试🎯"),
        ("alias=sql_inject", "'; DROP TABLE--"),
        ("alias=json_inject", '{"$gt": ""}'),
        ("alias=dot_path", "../etc/passwd"),
        ("alias=leading_slash", "/x"),
        ("alias=very_long_10k", "a" * 10000),
    ]
    defect = False
    for name, alias_val in cases:
        payload = {"actions": [{"create_alias": {"collection_name": "bnd_ali_sv_c1", "alias": alias_val}}]}
        status, body, raw = safe_request("POST", "/collections/aliases", json=payload)
        print(f"CASE {name}: status={status} body={raw[:300]}")
        if status == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            return
        if status in (500, 502, 503, 504) or any(k in raw.lower() for k in ["panic", "out of memory", "capacity overflow"]):
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {name} triggered 5xx/crash")
            defect = True
        elif status in (200, 201) and setup_ok:
            # verify the alias is actually usable (resolve via list)
            s2, b2, r2 = safe_request("GET", "/aliases")
            if alias_val not in r2:
                print(f"NOTE {name}: 200 accepted but alias not listed (consistency check)")
        # cleanup per-case alias if created
        try:
            safe_request("POST", "/collections/aliases",
                         json={"actions": [{"delete_alias": {"collection_name": "bnd_ali_sv_c1", "alias": alias_val}}]})
        except Exception:
            pass

    # resource limit: huge actions array (10k create_alias ops on same target)
    payload = {"actions": [
        {"create_alias": {"collection_name": "bnd_ali_sv_c1", "alias": f"bnd_ali_sv_bulk_{i}"}}
        for i in range(10000)
    ]}
    status, body, raw = safe_request("POST", "/collections/aliases", json=payload)
    print(f"CASE actions_10k: status={status} body={raw[:300]}")
    if status in (500, 502, 503) or "panic" in raw.lower():
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 10k actions triggered 5xx")
        defect = True
    # cleanup bulk aliases
    try:
        safe_request("POST", "/collections/aliases", json={"actions": [
            {"delete_alias": {"alias": f"bnd_ali_sv_bulk_{i}"}} for i in range(10000)
        ]})
    except Exception:
        pass

    if not defect:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        test_special_values()
    finally:
        cleanup()
