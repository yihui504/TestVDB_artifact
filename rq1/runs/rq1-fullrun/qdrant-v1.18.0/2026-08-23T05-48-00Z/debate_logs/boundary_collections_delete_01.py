#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: boundary (existence-state regression) — both halves of the two-sided status contract
Constraint: qdrant_state_collections_delete_001 ("DELETE existing => 200; DELETE missing => 404")
Endpoint: collections+delete -> DELETE /collections/{collection_name}
Round block: chunk_collections+delete
Coverage map: [strategy 1 boundary x state_collections_delete_001] baseline both halves
Unit: constraints::qdrant_state_collections_delete_001
"""

import requests, json, sys, os

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
    req_timeout = kwargs.pop("req_timeout", 60)
    try:
        resp = requests.request(method, url, headers=headers, timeout=req_timeout, **kwargs)
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


COL = "bd01_existing_col"
MISSING = "bd01_never_created_col"

def create_col(name):
    return safe_request("PUT", f"/collections/{name}",
                        json={"vectors": {"size": 4, "distance": "Cosine"}})

def verdict(defect, msg):
    print(f"VERDICT: {defect} {msg}")

try:
    # Arrange: create the collection and give it a point
    s, _, raw = create_col(COL)
    print(f"setup create: {s} {raw[:200]}")
    if s not in (200, 201):
        verdict("SCRIPT_ERROR", f"— cannot create fixture collection, got {s}")
        sys.exit(2)
    safe_request("PUT", f"/collections/{COL}/points?wait=true",
                 json={"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]})

    # Act & Assert — half 1: DELETE existing => 200
    s, _, raw = safe_request("DELETE", f"/collections/{COL}")
    print(f"DELETE existing: status={s} raw={raw[:300]}")
    if s == 0:
        verdict("SCRIPT_ERROR", "— connection failed on DELETE existing")
        sys.exit(2)
    if s != 200:
        verdict("DEFECT_FOUND (Type3_RuntimeFailure)",
                f"— contract says DELETE existing => 200, got {s}")
        sys.exit(0)

    # half 1 follow-up: collection must be gone (invariant qdrant_inv_collection_gone_after_delete_001)
    s_g, _, raw_g = safe_request("GET", f"/collections/{COL}")
    print(f"GET after delete: status={s_g} raw={raw_g[:200]}")
    if s_g == 200:
        verdict("DEFECT_FOUND (Type1_IllegalSuccess)",
                "— GET still 200 after successful DELETE (zombie collection)")
        sys.exit(0)

    # Act & Assert — half 2: DELETE missing => 404
    s, _, raw = safe_request("DELETE", f"/collections/{MISSING}")
    print(f"DELETE missing: status={s} raw={raw[:300]}")
    if s == 0:
        verdict("SCRIPT_ERROR", "— connection failed on DELETE missing")
        sys.exit(2)
    if s == 200:
        verdict("DEFECT_FOUND (Type1_IllegalSuccess)",
                "— contract says deleting non-existent collection returns 404, got 200")
        sys.exit(0)
    if s == 404:
        # Type-2 observation: does the 404 body identify the collection at all? (informational)
        low = raw.lower()
        has_hint = any(k in low for k in ("not found", "collection", "doesn't exist", "404"))
        print(f"TYPE2_OBSERVATION: 404 body mentions target/hint={has_hint} body={raw[:200]}")
        verdict("NO_DEFECT", "— 200 on existing, 404 on missing, gone after delete")
    elif s in (400, 422):
        verdict("NO_DEFECT", f"— 4xx ({s}) on missing collection also acceptable (explicit rejection)")
    else:
        verdict("DEFECT_FOUND (Type3_RuntimeFailure)",
                f"— unexpected status {s} for DELETE missing (expected 404)")
except SystemExit:
    raise
except Exception as e:
    verdict("SCRIPT_ERROR", f"— unhandled exception: {e}")
    sys.exit(2)
finally:
    try:
        safe_request("DELETE", f"/collections/{COL}")
    except Exception:
        pass
