#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: type_confusion (strategy 2)
Constraint: qdrant_state_aliases_update_001 + behavioral_contracts::qdrant_bc_alias_atomic_switch_001
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


def setup():
    ok = True
    for i in (1, 2):
        s, _, raw = safe_request("PUT", f"/collections/bnd_ali_tc_c{i}",
                                 json={"vectors": {"size": 4, "distance": "Cosine"}})
        if s not in (200, 201):
            print(f"setup create c{i} failed: {s} {raw[:200]}")
            ok = False
    return ok


def cleanup():
    for i in (1, 2):
        try:
            safe_request("POST", "/collections/aliases",
                         json={"actions": [{"delete_alias": {"alias": f"bnd_ali_tc_x{i}"}}]})
        except Exception:
            pass
    for i in (1, 2):
        try:
            safe_request("DELETE", f"/collections/bnd_ali_tc_c{i}")
        except Exception:
            pass


def test_type_confusion():
    setup_ok = setup()
    # Act: type-confused actions payloads (each should be 4xx rejected)
    cases = [
        ("actions=null", {"actions": None}),
        ("actions=object", {"actions": {"create_alias": {"collection_name": "bnd_ali_tc_c1", "alias": "bnd_ali_tc_x1"}}}),
        ("actions=empty_array", {"actions": []}),
        ("actions=array_of_null", {"actions": [None]}),
        ("actions=array_of_string", {"actions": ["create_alias"]}),
        ("create_alias.alias=null", {"actions": [{"create_alias": {"collection_name": "bnd_ali_tc_c1", "alias": None}}]}),
        ("create_alias.alias=object", {"actions": [{"create_alias": {"collection_name": "bnd_ali_tc_c1", "alias": {"a": 1}}}]}),
        ("create_alias.alias=empty_str", {"actions": [{"create_alias": {"collection_name": "bnd_ali_tc_c1", "alias": ""}}]}),
        ("rename_alias.old_alias=null", {"actions": [{"rename_alias": {"old_alias": None, "new_alias": "bnd_ali_tc_x2"}}]}),
        ("delete_alias.alias=array", {"actions": [{"delete_alias": {"collection_name": "bnd_ali_tc_c1", "alias": ["x"]}}]}),
    ]
    defect = False
    for name, payload in cases:
        status, body, raw = safe_request("POST", "/collections/aliases", json=payload)
        print(f"CASE {name}: status={status} body={raw[:300]}")
        if status == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            return
        if status in (200, 201) and not setup_ok:
            # setup failed; cannot distinguish — do not flag
            continue
        if status in (200, 201) and name not in ("actions=empty_array",):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {name} accepted with 200")
            defect = True
    if not defect:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        test_type_confusion()
    finally:
        cleanup()
