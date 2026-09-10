#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_exists_001
# strategy: strategy1_behavioral_positive
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 behavioral-positive x qdrant_behavioral_collections_exists_001 (G4 positive branch + response-shape closure: existing collection -> HTTP 200 with result as an OBJECT {exists: bool==True})
Oracle: after a successful PUT create of a b1cex_* collection, GET exists returns HTTP 200 where result is a dict (not a bare boolean), result["exists"] has type exactly bool and value True; a 404 = Type1_IllegalRejection, another non-200 4xx = Type4_StateLogicViolation, 5xx = Type3_RuntimeFailure, wrong shape (bare-bool result / non-bool exists) = Type4_StateLogicViolation

Constraint (bare id): qdrant_behavioral_collections_exists_001
  description: "returns 200 {result: {exists: bool}} - the result is the
  CollectionExistence object, existence is never expressed as HTTP 404"
  evidence_tier: explicit; level: endpoint.

Shape anchor (D3b rule 2 - spec-derived response_shape wins over paraphrase):
  contract api_endpoints['collections+exists'].response_shape declares
  result: object, result.exists: boolean (R5 exists-shape lesson from run2r #1:
  the envelope is {result: {exists: bool}}, NOT a bare result boolean, even
  though the raw_knowledge behavioral paraphrase loosely says "{result: bool}";
  the published OpenAPI CollectionExistence object is the ground truth).

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url;
R12 lesson: collections+exists is NOT in the runtime PATHS table - register it
verbatim from raw_knowledge - established pattern):
  collections+exists -> GET  /collections/{collection_name}/exists
  collections+create -> PUT  /collections/{collection_name}
  collections+delete -> DELETE /collections/{collection_name}
  healthz            -> GET  /healthz
"""

import json
import os
import sys
import time
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
PATH_CREATE = "/collections/{collection_name}"          # collections+create
PATH_DELETE = "/collections/{collection_name}"          # collections+delete


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


COLL = f"b1cex_pos_{int(time.time())}"


def cleanup():
    """Teardown: best-effort delete; cleanup failure must never fail the script."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=COLL), timeout=15)
    except Exception:
        pass


def main():
    # ---- Arrange: create the collection whose existence we will verify ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=COLL),
                              json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=30)
    print(f"setup create {COLL}: status={st}")
    print(f"setup raw: {raw[:300]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on setup (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure in setup, no defect conclusion")
        return
    if st not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR - setup failed creating {COLL}: {st} {raw[:300]}")
        return

    # ---- Act: exists on the just-created collection ----
    st, body, raw = safe_request("GET", PATH_EXISTS.format(collection_name=COLL), timeout=30)
    print(f"GET exists on {COLL} -> status={st}")
    print(f"raw: {raw[:600]}")

    # ---- Assert (declare expectation first, then compare) ----
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on exists probe (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - exists on an existing "
              f"collection returned server error {st}")
        return
    if st == 404:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) - exists on the existing "
              f"collection {COLL} returned 404; assertion requires HTTP 200 with "
              f"result.exists=true (existence is never expressed as HTTP 404)")
        return
    if not (200 <= st <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - expected HTTP 200 for "
              f"an existing collection, got {st}")
        return

    # 200 branch: shape closure per contract response_shape (result: object, result.exists: boolean)
    if not isinstance(body, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - response body is not a "
              f"JSON object: {raw[:300]}")
        return
    result = body.get("result")
    if not isinstance(result, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result is not an object "
              f"(CollectionExistence); got {type(result).__name__}: {raw[:300]} "
              f"(R5 shape lesson: envelope is result.exists, not a bare result boolean)")
        return
    if "exists" not in result:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result object carries no "
              f"'exists' key: {raw[:300]}")
        return
    exists_val = result["exists"]
    if type(exists_val) is not bool:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.exists is not a "
              f"boolean (got {type(exists_val).__name__}={exists_val!r}): {raw[:300]}")
        return
    if exists_val is not True:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - collection {COLL} exists "
              f"(created with status 200 just before) but result.exists=false: {raw[:300]}")
        return

    # envelope observation only (status/time are listed in response_shape; not gated - error
    # field structure is an implementation detail per threat_model by-design list)
    print(f"envelope observation: status field={body.get('status')!r}, "
          f"time field={body.get('time')!r}")
    print("OK: existing collection -> 200 with result.exists == True (bool, object envelope)")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
