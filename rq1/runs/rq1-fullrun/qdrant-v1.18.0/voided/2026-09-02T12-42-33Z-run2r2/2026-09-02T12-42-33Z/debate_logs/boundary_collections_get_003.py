#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_get_003
# strategy: strategy1_lifecycle_flip
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness) + BS-04 (Boundary Default Optimism)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 lifecycle-flip x qdrant_behavioral_collections_get_001 (G6 mutation: the mutation point is the delete of a collection we just described - deletion is the strongest lifecycle boundary for the describe face, because a cached/stale config path would keep serving 200 for a name whose state was just destroyed; timing: probe immediately after the DELETE returns, then again after a settle delay to catch slow invalidation)
Oracle: PUT-create b3cget_lf_* -> GET describe = 200 with result dict (control leg); DELETE the same collection (acknowledged 200) -> immediate GET describe must return HTTP 404 with an error message, and a second GET after a 2s settle must still be 404; a post-delete 200 = Type4_StateLogicViolation (stale config served for a destroyed collection) with Type1_IllegalSuccess character (config without a backing collection), 5xx = Type3_RuntimeFailure, non-404 4xx = Type4_StateLogicViolation
Constraint (bare id): qdrant_behavioral_collections_get_001
  expected_behavior: "existing collection: HTTP 200 with resolved config;
  missing collection: HTTP 404 with an error message, never 200 with config"
  evidence_tier: explicit; level: endpoint.
G9 consistent-disposition angle: the SAME name must flip channels purely as a
function of lifecycle state (200-before / 404-after); any asymmetry (e.g. 200
after delete, or a 404 that later becomes 200 again = resurrection) is a
state-logic defect with no contract endorsement needed.
Cleanup discipline (dispatch prompt): the only collection deleted here is the
one this script created (b3cget_lf_*); the delete is the ACT under test, and
the final cleanup delete is additionally wrapped best-effort.

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url;
R12 lesson - established pattern):
  collections+get    -> GET    /collections/{collection_name}
  collections+create -> PUT    /collections/{collection_name}
  collections+delete -> DELETE /collections/{collection_name}
  healthz            -> GET    /healthz
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

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
PATH_GET = "/collections/{collection_name}"            # collections+get
PATH_CREATE = "/collections/{collection_name}"         # collections+create
PATH_DELETE = "/collections/{collection_name}"         # collections+delete


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
COLL = f"b3cget_lf_{TS}"


def cleanup():
    """Teardown: best-effort idempotent delete of the collection WE created."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")), timeout=15)
    except Exception:
        pass


def judge_missing_probe(st, raw, phase):
    """Adjudicate one post-delete describe probe. Returns True iff a verdict was printed."""
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on {phase} probe (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return True
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - {phase} describe after "
              f"delete returned server error {st}")
        return True
    if 200 <= st <= 299:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation, Type1 character) - "
              f"{phase} describe after acknowledged delete of {COLL} still returns "
              f"HTTP {st} with config (stale/resurrected state: {raw[:300]}); the "
              f"collection is missing and the contract pins 404, never 200")
        return True
    if st != 404:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - {phase} describe "
              f"after delete should be 404, got {st}: {raw[:300]}")
        return True
    return False


def main():
    # ---- Arrange: create, then control-describe (200 leg) ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
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

    st, body, raw = safe_request("GET", PATH_GET.format(collection_name=quote(COLL, safe="")), timeout=30)
    print(f"control describe (pre-delete) -> status={st}")
    print(f"raw: {raw[:400]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on control probe (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if not (200 <= st <= 299) or not isinstance(body, dict) or not isinstance(body.get("result"), dict):
        print(f"VERDICT: SCRIPT_ERROR - control leg failed (pre-delete describe did not "
              f"return 200 with a result object): status={st} raw={raw[:300]}")
        return
    print("OK: pre-delete describe = 200 with result object (control leg)")

    # ---- Act: delete (the mutation under test), then immediate + settled probes ----
    st, _, raw = safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")), timeout=30)
    print(f"delete {COLL}: status={st}")
    print(f"delete raw: {raw[:300]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on delete (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure on delete, no defect conclusion")
        return
    if not (200 <= st <= 299):
        print(f"VERDICT: SCRIPT_ERROR - delete of the collection we created failed "
              f"unexpectedly: {st} {raw[:300]} (cannot run the flip leg)")
        return

    st, _, raw = safe_request("GET", PATH_GET.format(collection_name=quote(COLL, safe="")), timeout=30)
    print(f"immediate post-delete describe -> status={st}")
    print(f"raw: {raw[:400]}")
    if judge_missing_probe(st, raw, "immediate"):
        return
    print("OK: immediate post-delete describe = 404")

    time.sleep(2)
    st, _, raw = safe_request("GET", PATH_GET.format(collection_name=quote(COLL, safe="")), timeout=30)
    print(f"settled post-delete describe (after 2s) -> status={st}")
    print(f"raw: {raw[:400]}")
    if judge_missing_probe(st, raw, "settled"):
        return

    print("OK: lifecycle flip 200->404 holds immediately and after settle; no stale "
          "config, no resurrection")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
