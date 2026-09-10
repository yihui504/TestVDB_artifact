#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: malformed_input fuzzing (strategy 7) — raw bytes on create-collection body
Constraint: qdrant_type_collections_create_001/002 (serde robustness behind the enums)
Endpoint: PUT /collections/{collection_name} (contract path: collections+create)
exploration_target: novel_candidate
Block: chunk_collections+create-1of2
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned)
# Blindspot: BS-01
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
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""


CRASH_KEYS = ["panic", "internal", "serde", "utf", "decode", "backtrace"]


def test_malformed_bodies():
    cname = "bnd_crt_mf"
    bodies = [
        ("truncated json", b'{"vectors": {"size": 4'),
        ("trailing comma", b'{"vectors": {"size": 4, "distance": "Cosine",},}'),
        ("illegal escape", b'{"vectors": {"size": 4, "distance": "\\q"}}'),
        ("single quotes", b"{'vectors': {'size': 4}}"),
        ("comment injection", b'{"vectors": {"size": 4}, // c\n "distance": "Cosine"}'),
        ("NUL byte in distance", b'{"vectors": {"size": 4, "distance": "Cos\\u0000ine"}}'),
        ("lone surrogate in name field", b'{"vectors": {"size": 4, "distance": "Cosine"}, "metadata": {"k": "\\ud800"}}'),
        ("deep nesting 5000", b'{"vectors": {"size": 4, "distance": "Cosine"}, "metadata": ' + b'[' * 5000 + b']' * 5000 + b'}'),
        ("1MB string in metadata", b'{"vectors": {"size": 4, "distance": "Cosine"}, "metadata": {"k": "' + b'a' * 1000000 + b'"}}'),
        ("top-level array", b'[{"vectors": {"size": 4, "distance": "Cosine"}}]'),
        ("top-level string", b'"hello"'),
        ("empty body", b''),
    ]
    defect = False
    for name, body in bodies:
        status, _, raw = safe_request("PUT", f"/collections/{cname}", data=body)
        if status == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            return
        print(f"CASE {name}: status={status} body={raw[:300]}")
        if status in (500, 502, 503, 504) or any(k in raw.lower() for k in CRASH_KEYS):
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {name} triggered 5xx/panic")
            defect = True
        elif status in (200, 201):
            # silent accept of malformed/unicode-hostile body — flag for judge-doc
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {name} accepted with 200 (silent accept, judge-doc to verify)")
            defect = True
            try:
                safe_request("DELETE", f"/collections/{cname}")
            except Exception:
                pass
    if not defect:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        test_malformed_bodies()
    finally:
        try:
            safe_request("DELETE", "/collections/bnd_crt_mf")
        except Exception:
            pass
