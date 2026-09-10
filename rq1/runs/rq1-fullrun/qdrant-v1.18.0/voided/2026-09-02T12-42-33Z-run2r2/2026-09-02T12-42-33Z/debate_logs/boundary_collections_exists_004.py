#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_exists_004
# strategy: strategy4_special_value + strategy7_malformed_input
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust) + BS-04 (Boundary Default Optimism)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy4 special-value + strategy7 malformed-input on the collection_name path param x qdrant_behavioral_collections_exists_001 (unicode / SQL-injection / JSON-injection / RTL bidi / percent-encoded NUL truncation probe)
Oracle: for every never-created special name, GET exists answers with a clean 4xx (validation reject) OR HTTP 200 + result.exists exactly bool False; 200 with exists=true = Type1_IllegalSuccess (hallucinated existence, or NUL-truncation matching the prefix-named base collection), 5xx = Type3_RuntimeFailure, result.exists non-bool / result not an object = Type4_StateLogicViolation

Constraint (bare id): qdrant_behavioral_collections_exists_001 - existence must be
answered in the body ({result:{exists:bool}}, shape per contract response_shape;
R5 lesson) and the lookup must stay robust for hostile identifiers. The NUL probe
is the sharpest variant: if the server truncates the decoded name at the NUL
byte, exists("<base>%00suffix") would wrongly return true for the created base
collection - a read-side identifier-confusion defect (Type1).

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url;
R12 lesson: register collections+exists verbatim - established pattern):
  collections+exists -> GET  /collections/{collection_name}/exists
  collections+create -> PUT  /collections/{collection_name}
  collections+delete -> DELETE /collections/{collection_name}
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


TS = int(time.time())
BASE_COLL = f"b4cex_base_{TS}"


def cleanup():
    """Teardown: best-effort delete; cleanup failure must never fail the script."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=BASE_COLL), timeout=15)
    except Exception:
        pass


def judge_probe(label, name, st, body, raw):
    """Declare expectation, then compare: special never-created name -> 4xx or
    200 with result.exists exactly False; never exists=true, never 5xx."""
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on {label} (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return False
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - {label} name triggered "
              f"server error {st} (hostile identifier must be answered with 4xx, not a crash)")
        return False
    if 400 <= st <= 499:
        print(f"OK: {label} rejected with 4xx ({st}) - clean validation behavior")
        return True
    if not (200 <= st <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - unexpected status {st} "
              f"for {label}")
        return False
    # 200 branch: shape closure (result: object, result.exists: boolean)
    if not isinstance(body, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - response body is not a "
              f"JSON object for {label}: {raw[:300]}")
        return False
    result = body.get("result")
    if not isinstance(result, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result is not an object "
              f"for {label}; got {type(result).__name__}: {raw[:300]}")
        return False
    exists_val = result.get("exists")
    if type(exists_val) is not bool:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.exists is not a "
              f"boolean for {label} (got {type(exists_val).__name__}={exists_val!r}): {raw[:300]}")
        return False
    if exists_val is True:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - {label} reported "
              f"result.exists=true; name was never created"
              + (" (NUL-truncation: decoded name truncated at %00 and matched the base "
                 f"collection {BASE_COLL})" if "NUL" in label else
                 " (hallucinated existence for a hostile identifier)"))
        return False
    print(f"OK: {label} -> 200 with result.exists == False (bool)")
    return True


def main():
    # ---- Arrange: create the base collection used by the NUL-truncation probe ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=BASE_COLL),
                              json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=30)
    print(f"setup create {BASE_COLL}: status={st}")
    print(f"setup raw: {raw[:300]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on setup (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure in setup, no defect conclusion")
        return
    if st not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR - setup failed creating {BASE_COLL}: {st} {raw[:300]}")
        return

    # ---- Act + Assert: special / malformed identifiers (none of these exist) ----
    probes = [
        ("unicode name", f"b4cex_中文\U0001F3AF_{TS}"),
        ("SQL-injection name", "'; DROP TABLE collections;--"),
        ("JSON-injection name", '{"$gt": ""}'),
        ("RTL-bidi name", f"coll‮evil_{TS}"),
        # decoded name = b4cex_base_<TS> + NUL + suffix; a true answer means the
        # server truncated at NUL and matched BASE_COLL (identifier confusion)
        ("percent-encoded NUL probe", f"b4cex_base_{TS}%00suffix"),
    ]

    all_ok = True
    for label, name in probes:
        st, body, raw = safe_request("GET", PATH_EXISTS.format(collection_name=name), timeout=30)
        print(f"GET exists [{label}] name={name!r} -> status={st}")
        print(f"raw: {raw[:400]}")
        if not judge_probe(label, name, st, body, raw):
            all_ok = False
            break

    if all_ok:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
