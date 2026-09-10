#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: malformed_input / character fuzzing (strategy 7)
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
        safe_request("DELETE", "/collections/bnd_ali_mf_c1")
    except Exception:
        pass


def test_malformed():
    s, _, raw = safe_request("PUT", "/collections/bnd_ali_mf_c1",
                             json={"vectors": {"size": 4, "distance": "Cosine"}})
    setup_ok = s in (200, 201)

    # raw bodies — use data= to bypass client-side serialization
    raw_bodies = [
        ("truncated_json", '{"actions": [{"create_alias": '),
        ("trailing_comma", '{"actions": [{"create_alias": {"collection_name": "bnd_ali_mf_c1", "alias": "a1",}},]}'),
        ("illegal_escape", '{"actions": [{"create_alias": {"collection_name": "bnd_ali_mf_c1", "alias": "a\\q"}}]}'),
        ("single_quotes", "{'actions': []}"),
        ("nul_in_alias", '{"actions": [{"create_alias": {"collection_name": "bnd_ali_mf_c1", "alias": "a\\u0000b"}}]}'),
        ("lone_surrogate", '{"actions": [{"create_alias": {"collection_name": "bnd_ali_mf_c1", "alias": "a\\ud800b"}}]}'),
        ("nul_in_collection_name", '{"actions": [{"create_alias": {"collection_name": "bnd_ali_mf_c1\\u0000", "alias": "a3"}}]}'),
        ("rtl_control", '{"actions": [{"create_alias": {"collection_name": "bnd_ali_mf_c1", "alias": "a\\u202Eb"}}]}'),
        ("nan_value", '{"actions": [{"create_alias": {"collection_name": NaN, "alias": "a4"}}]}'),
    ]
    defect = False
    for name, body in raw_bodies:
        status, b, raw = safe_request("POST", "/collections/aliases",
                                      data=body.encode("utf-8"),
                                      headers={"Content-Type": "application/json"})
        print(f"CASE {name}: status={status} body={raw[:300]}")
        if status == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            return
        if status in (500, 502, 503) or any(k in raw.lower() for k in ["panic", "serde", "utf", "decode error", "internal error"]):
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {name} triggered 5xx/parser error leak")
            defect = True
    if not defect:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        test_malformed()
    finally:
        cleanup()
