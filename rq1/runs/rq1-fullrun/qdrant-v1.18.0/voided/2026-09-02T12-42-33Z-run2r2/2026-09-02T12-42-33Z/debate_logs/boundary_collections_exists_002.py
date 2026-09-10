#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_exists_002
# strategy: strategy1_behavioral_negative
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 behavioral-negative x qdrant_behavioral_collections_exists_001 (G4 negative branch - the assertion's core promise: a MISSING collection yields HTTP 200 with result.exists=false, existence is NEVER expressed as HTTP 404)
Oracle: for 3 never-created syntactically-legal b2cex_* names, GET exists returns HTTP 200 with result as a dict and result.exists exactly bool False on every probe; a 404 = Type1_IllegalRejection (the explicitly forbidden channel), another 4xx = Type4_StateLogicViolation, 5xx = Type3_RuntimeFailure, shape violation = Type4_StateLogicViolation

Constraint (bare id): qdrant_behavioral_collections_exists_001
  expected_behavior: "HTTP 200 with result being an object of shape {exists: bool};
  a missing collection yields result.exists=false with HTTP 200 (never 404)"

Shape anchor (D3b rule 2): contract response_shape declares result: object,
result.exists: boolean (R5 exists-shape lesson: {result:{exists:bool}}, not a
bare result boolean).

This is the exact surface where a REST framework's default not-found handler
(404 for absent resources) would violate the body-expressed-existence contract:
the missing-collection case is the only input state that can flip the channel.

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url;
R12 lesson: register collections+exists verbatim - established pattern):
  collections+exists -> GET /collections/{collection_name}/exists
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


def judge_missing_probe(name, st, body, raw):
    """Declare expectation, then compare: missing collection -> 200 + result.exists==False."""
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on {name} (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return False
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - exists on missing "
              f"collection {name} returned server error {st}")
        return False
    if st == 404:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) - missing collection {name} "
              f"answered with HTTP 404; assertion: existence is NEVER expressed as 404, "
              f"must be HTTP 200 with result.exists=false")
        return False
    if not (200 <= st <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - expected HTTP 200 for "
              f"missing collection {name}, got {st}")
        return False
    if not isinstance(body, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - response body is not a "
              f"JSON object: {raw[:300]}")
        return False
    result = body.get("result")
    if not isinstance(result, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result is not an object "
              f"(CollectionExistence) for missing collection; got {type(result).__name__}: "
              f"{raw[:300]} (R5 shape lesson: envelope is result.exists)")
        return False
    if "exists" not in result:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result object carries no "
              f"'exists' key: {raw[:300]}")
        return False
    exists_val = result["exists"]
    if type(exists_val) is not bool:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.exists is not a "
              f"boolean (got {type(exists_val).__name__}={exists_val!r}): {raw[:300]}")
        return False
    if exists_val is not False:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - never-created collection "
              f"{name} reported result.exists=true: {raw[:300]}")
        return False
    print(f"OK: missing collection {name} -> 200 with result.exists == False (bool)")
    return True


def main():
    ts = int(time.time())
    # never-created, syntactically-legal names (alnum / dash / underscore families)
    missing_names = [
        f"b2cex_missing_{ts}",
        f"b2cex-missing-{ts}",
        f"b2cexMissing{ts}",
    ]

    all_ok = True
    for name in missing_names:
        st, body, raw = safe_request("GET", PATH_EXISTS.format(collection_name=name), timeout=30)
        print(f"GET exists on missing '{name}' -> status={st}")
        print(f"raw: {raw[:400]}")
        if not judge_missing_probe(name, st, body, raw):
            all_ok = False
            break

    if all_ok:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
