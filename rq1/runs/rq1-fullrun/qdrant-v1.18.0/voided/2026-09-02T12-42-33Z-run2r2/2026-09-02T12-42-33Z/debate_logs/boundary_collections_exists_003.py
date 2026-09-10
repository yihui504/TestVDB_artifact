#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_exists_003
# strategy: strategy1_boundary_value
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value (collection_name min-1: empty path segment) x qdrant_behavioral_collections_exists_001 (endpoint collections+exists; GET /collections/{collection_name}/exists); round coverage list: {behavioral-positive 001, behavioral-negative 002, boundary min-1 003, special/malformed 004, lifecycle flip 005, resource-limit 006} x qdrant_behavioral_collections_exists_001
Oracle: collection_name='' (GET /collections//exists) -> 4xx reject (route 404 or validation 400); a 2xx = Type1_IllegalSuccess (empty identifier below the documented min length 1 accepted as a legal lookup), a 5xx = Type3_RuntimeFailure

Constraint (bare id): qdrant_behavioral_collections_exists_001 - the endpoint
contract is scoped to legal collection_name values (required:true string path
param, minimum length 1, per the published OpenAPI). The empty string sits at
min-1 of that domain: it is NOT a "missing collection" (whose documented
answer is 200 result.exists=false) but an out-of-domain identifier that must
be rejected with a clean 4xx.

Adjudication note (channel ambiguity resolved): a 404 here is acceptable -
for an out-of-domain identifier the route/validation layer rejecting with 404
or 400 is clean rejection; the "never 404" clause of the assertion protects
MISSING collections (002 covers that), not ILLEGAL identifiers.

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url;
R12 lesson: register collections+exists verbatim - established pattern):
  collections+exists -> GET /collections/{collection_name}/exists
"""

import json
import os
import sys
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    _root = Path(__file__).resolve()
    for _p in (_root, *_root.parents):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or TARGET != "qdrant":
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)

# URL registry - verbatim from raw_knowledge.json api_endpoints[].url
PATH_EXISTS = "/collections/{collection_name}/exists"   # collections+exists


def safe_request(method, endpoint, json=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md).
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, headers=headers, timeout=timeout
        )
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except Exception:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def main():
    # Act: empty collection_name (length 0 - below the minimum legal name length of 1).
    # The empty path segment is outside the legal identifier domain: expect clean 4xx.
    st, _, raw = safe_request("GET", "/collections//exists", timeout=30)
    print(f"GET /collections//exists (empty collection_name) -> status={st}")
    print(f"raw: {raw[:600]}")

    # Assert (declare expectation first, then compare)
    if st <= 0:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on probe (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - empty collection_name "
              f"triggered server error {st} (should be a clean 4xx)")
        return
    if 200 <= st <= 399:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - empty collection_name "
              f"accepted with {st}; the documented identifier domain requires length>=1, "
              f"an out-of-domain identifier must be rejected with 4xx")
        return
    # 4xx (400/404/...): clean rejection of the empty identifier
    # Type-2 observation (non-gating: error field structure is an implementation detail
    # per threat_model by-design list) - record diagnostics quality for the judge.
    lowered = raw.lower()
    if ("collection" in lowered or "name" in lowered or "uri" in lowered
            or "segment" in lowered or "not found" in lowered):
        print("diagnostics observation: rejection message references the offending "
              "identifier/route (acceptable quality)")
    else:
        print(f"diagnostics observation: rejection message does not name the offending "
              f"parameter (informational, non-gating): {raw[:200]}")
    print("OK: empty collection_name rejected with 4xx as expected")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
