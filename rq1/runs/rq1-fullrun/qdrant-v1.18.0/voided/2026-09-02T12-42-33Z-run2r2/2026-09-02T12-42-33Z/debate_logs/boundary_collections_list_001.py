#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_list_001
# strategy: strategy1_boundary_behavioral_positive
# endpoint: collections+list
# constraint_ids: qdrant_behavioral_collections_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collections
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value / behavioral-positive x qdrant_behavioral_collections_list_001
(prefix-scoped list-size closure {0,1}: fresh unique prefix -> 0 listed entries; after
PUT-create -> exactly 1 listed entry with byte-exact name) + envelope closure
result.collections[] as a JSON array.
[coverage: strategy1 x collections_list_001; unit assertions::qdrant_behavioral_collections_list_001]
Oracle: baseline GET /collections with a fresh unique prefix b1cl1p* -> HTTP 200 where
result.collections is a JSON array containing 0 entries whose name starts with the prefix;
after PUT-create of b1cl1p{tag} (vectors size=4 distance=Cosine) -> GET /collections returns
HTTP 200 with exactly 1 prefix-matching entry whose name == the created name exactly
(string equality); 404/422 on the legal GET = Type1_IllegalRejection, other non-200 4xx =
Type4_StateLogicViolation, 5xx = Type3_RuntimeFailure, missing/non-array result.collections
or prefix count != 1 or name mismatch = Type4_StateLogicViolation.
Constraint: qdrant_behavioral_collections_list_001 (bare id) — "returns 200 with an array of
{name} CollectionDescription entries" (evidence_tier: explicit; level: endpoint).

Shape anchor (D3b + R14 standing lesson — shape oracles cross-checked against the published
OpenAPI): the contract api_endpoints['collections+list'].response_shape block mirrors the
describe face (result.config/...) — an extraction artifact. The endpoint_registry doc_quote
("Returns 200 with an array of {name} CollectionDescription entries") and the published
v-1-18-x OpenAPI ListCollectionsResponse govern: envelope = result.collections[] with each
item carrying a string "name" (v1.18.0 CollectionDescription). Adjudication keys off
result.collections[], never a bare top-level array.

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  collections+list    -> GET    /collections
  collections+create  -> PUT    /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET    /healthz
"""

import json
import os
import sys
import time
import uuid
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

PATH_LIST = "/collections"                                # collections+list
PATH_CREATE = "/collections/{collection_name}"            # collections+create
PATH_DELETE = "/collections/{collection_name}"            # collections+delete


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


def parse_collections(body):
    """Extract the listed collections array from a qdrant 200 envelope.

    Returns (collections_list, err): err is None on success, else a human reason.
    """
    if not isinstance(body, dict):
        return None, "response body is not a JSON object"
    result = body.get("result")
    if not isinstance(result, dict):
        return None, "result is not an object"
    colls = result.get("collections")
    if not isinstance(colls, list):
        return None, "result.collections is not an array"
    return colls, None


TAG = uuid.uuid4().hex[:8]
PREFIX = "b1cl1p" + TAG
COLL = PREFIX  # single collection whose visibility is under test


def prefix_matches(colls, prefix):
    """Names of listed entries (dict-guarded) that start with prefix."""
    names = []
    for e in colls:
        if isinstance(e, dict) and isinstance(e.get("name"), str):
            if e["name"].startswith(prefix):
                names.append(e["name"])
    return names


def cleanup():
    """Teardown: best-effort delete of ONLY the collection this script created."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")), timeout=30)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    # ---- Act 1: baseline list with a fresh unique prefix (0-branch of the closure) ----
    st, body, raw = safe_request("GET", PATH_LIST, timeout=30)
    print(f"baseline GET {PATH_LIST} -> status={st}")
    print(f"raw (first 400 chars): {raw[:400]}")

    # ---- Assert 1: legal parameterless GET must be answered, never crash ----
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on baseline list (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - legal GET /collections returned "
              f"server error {st}")
        return
    if st in (404, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) - legal GET /collections wrongly "
              f"rejected with {st} (promise: 200 with array of {{name}})")
        return
    if not (200 <= st <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - expected HTTP 200 for "
              f"GET /collections, got {st}")
        return

    colls, err = parse_collections(body)
    if err:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - documented envelope "
              f"result.collections[] missing/malformed: {err}: {raw[:300]}")
        return
    base_hits = prefix_matches(colls, PREFIX)
    if base_hits:
        print(f"VERDICT: SCRIPT_ERROR - unique-prefix discipline broken: stale entries "
              f"{base_hits} already listed before this script ran")
        return
    print(f"OK: baseline 0-branch — 0 entries with prefix {PREFIX}* among {len(colls)} listed")

    # ---- Arrange: create exactly one collection under the fresh prefix ----
    st, _, raw = safe_request(
        "PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
        json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
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

    # ---- Act 2: list again (1-branch of the closure) ----
    st, body, raw = safe_request("GET", PATH_LIST, timeout=30)
    print(f"post-create GET {PATH_LIST} -> status={st}")
    print(f"raw (first 400 chars): {raw[:400]}")

    # ---- Assert 2: status + envelope + exact-once visibility + byte-exact name ----
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on post-create list (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - legal GET /collections returned "
              f"server error {st} after a successful create")
        return
    if st in (404, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) - legal GET /collections wrongly "
              f"rejected with {st} after a successful create")
        return
    if not (200 <= st <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - expected HTTP 200 for "
              f"GET /collections after create, got {st}")
        return

    colls, err = parse_collections(body)
    if err:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - documented envelope "
              f"result.collections[] missing/malformed: {err}: {raw[:300]}")
        return
    hits = prefix_matches(colls, PREFIX)
    if len(hits) != 1:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - created collection {COLL} "
              f"must be listed exactly once, prefix matched {len(hits)} time(s): {hits}")
        return
    if hits[0] != COLL:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - listed name {hits[0]!r} != "
              f"created name {COLL!r} (list face must echo the name byte-exactly)")
        return

    print(f"OK: 1-branch — {COLL} listed exactly once with byte-exact name among "
          f"{len(colls)} entries")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
