#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: type_confusion (strategy 2) — vectors.distance / vectors.size / invalid enum
Constraint: qdrant_type_collections_create_001 + 002 + 003
Endpoint: PUT /collections/{collection_name} (contract path: collections+create)
exploration_target: novel_candidate
Block: chunk_collections+create-1of2
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned)
# Blindspot: BS-01 Parameter Type Coercion Trust
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


def cleanup(names):
    for n in names:
        try:
            safe_request("DELETE", f"/collections/{n}")
        except Exception:
            pass


def test_vectors_type_confusion():
    cases = [
        # (name, payload, should_be_rejected, expect_param_hint)
        ("distance=Bogus", {"vectors": {"size": 4, "distance": "Bogus"}}, True, "distance"),
        ("distance=euclid lowercase", {"vectors": {"size": 4, "distance": "euclid"}}, True, "distance"),
        ("distance=null", {"vectors": {"size": 4, "distance": None}}, True, "distance"),
        ("distance=123", {"vectors": {"size": 4, "distance": 123}}, True, "distance"),
        ("size=0", {"vectors": {"size": 0, "distance": "Cosine"}}, True, "size"),
        ("size=-1", {"vectors": {"size": -1, "distance": "Cosine"}}, True, "size"),
        ("size=1.5 float", {"vectors": {"size": 1.5, "distance": "Cosine"}}, True, "size"),
        ("size='4' string", {"vectors": {"size": "4", "distance": "Cosine"}}, True, "size"),
        ("size=null", {"vectors": {"size": None, "distance": "Cosine"}}, True, "size"),
        ("vectors=null", {"vectors": None}, True, "vectors"),
        ("vectors={} empty", {"vectors": {}}, True, "vectors"),
        ("vectors missing entirely", {}, True, "vectors"),
    ]
    defect = False
    used = []
    for name, payload, should_reject, hint in cases:
        cname = f"bnd_crt_tc_{abs(hash(name)) % 100000}"
        used.append(cname)
        status, body, raw = safe_request("PUT", f"/collections/{cname}", json=payload)
        print(f"CASE {name}: status={status} body={raw[:300]}")
        if status == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            cleanup(used)
            return
        if should_reject and status in (200, 201):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {name} accepted with {status}")
            defect = True
        elif should_reject and status in (400, 422) and hint not in raw.lower():
            # Type-2: rejection ok but message does not name the offending field
            print(f"NOTE Type2 — {name} rejected but error does not mention '{hint}': {raw[:200]}")
    if not defect:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        test_vectors_type_confusion()
    finally:
        pass
