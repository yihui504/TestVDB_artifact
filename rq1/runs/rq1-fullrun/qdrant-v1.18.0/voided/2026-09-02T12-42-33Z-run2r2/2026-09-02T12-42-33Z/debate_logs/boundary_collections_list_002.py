#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_list_002
# strategy: strategy2_type_boundary
# endpoint: collections+list
# constraint_ids: qdrant_behavioral_collections_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collections
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — here: trust that the list face always
# emits well-typed CollectionDescription entries)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_behavioral_collections_list_001 — global typing
closure of the listed array: EVERY entry of result.collections must be a JSON object whose
"name" key holds a non-empty string (v1.18.0 CollectionDescription); no type-confused items
(bare strings / numbers / nulls / arrays as items) and no duplicate names in the listing.
[coverage: strategy2 x collections_list_001; unit assertions::qdrant_behavioral_collections_list_001]
Oracle: with >= 1 setup collection b1cl2t{tag} present (non-empty-array branch), GET
/collections returns HTTP 200 where result.collections is an array in which every element is
a dict containing key "name" whose value is a non-empty str, and the name multiset contains
no duplicates; any non-dict element, missing-name element, non-string/empty name, or
duplicate name = Type4_StateLogicViolation; 404/422 on the legal GET = Type1_IllegalRejection,
other non-200 4xx = Type4_StateLogicViolation, 5xx = Type3_RuntimeFailure.
Constraint: qdrant_behavioral_collections_list_001 (bare id) — "returns 200 with an array of
{name} CollectionDescription entries" (evidence_tier: explicit; level: endpoint). The typing
of each {name} item IS the promise; a type-confused or duplicated entry violates it.

Global-face discipline (dispatch): assertions on membership are prefix-filtered for setup,
but the per-entry typing closure is this endpoint's own contract face and therefore applies
to every listed entry (sibling collections created by other scripts are still Collection-
Descriptions and must type-check; additive extra keys inside entries are tolerated).

Shape anchor (D3b + R14 standing lesson — cross-checked against the published OpenAPI):
contract api_endpoints['collections+list'].response_shape mirrors the describe face
(extraction artifact); the doc_quote ("array of {name} CollectionDescription entries") and
the published v-1-18-x OpenAPI ListCollectionsResponse govern: result.collections[] with
string-typed name per item.

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  collections+list    -> GET    /collections
  collections+create  -> PUT    /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET    /healthz
"""

import json
import os
import sys
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


TAG = uuid.uuid4().hex[:8]
COLL = "b1cl2t" + TAG


def cleanup():
    """Teardown: best-effort delete of ONLY the collection this script created."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")), timeout=30)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    # ---- Arrange: one prefixed collection so the non-empty-array branch is exercised ----
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

    # ---- Act: list all collections (global face) ----
    st, body, raw = safe_request("GET", PATH_LIST, timeout=30)
    print(f"GET {PATH_LIST} -> status={st}")
    print(f"raw (first 400 chars): {raw[:400]}")

    # ---- Assert: status first ----
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on list (healthz status={hs}: {hraw[:200]})")
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

    # ---- Assert: envelope + global per-entry typing closure ----
    if not isinstance(body, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - response body is not a "
              f"JSON object: {raw[:300]}")
        return
    result = body.get("result")
    if not isinstance(result, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result is not an object: "
              f"got {type(result).__name__}: {raw[:300]}")
        return
    colls = result.get("collections")
    if not isinstance(colls, list):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.collections is not "
              f"an array: got {type(colls).__name__}: {raw[:300]}")
        return
    if len(colls) == 0:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - listing is empty although "
              f"{COLL} was just created (membership/visibility violation)")
        return

    names = []
    for i, e in enumerate(colls):
        if not isinstance(e, dict):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.collections[{i}] "
                  f"is not an object (CollectionDescription), got {type(e).__name__}={e!r}: "
                  f"{raw[:300]}")
            return
        if "name" not in e:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.collections[{i}] "
                  f"has no 'name' key: {json.dumps(e, ensure_ascii=False)[:200]}")
            return
        n = e["name"]
        if not isinstance(n, str):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - name of entry {i} is "
                  f"not a string, got {type(n).__name__}={n!r}: {raw[:300]}")
            return
        if n == "":
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - entry {i} carries an "
                  f"empty-string collection name: {json.dumps(e, ensure_ascii=False)[:200]}")
            return
        names.append(n)

    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - the list face reports "
              f"duplicate collection names (same collection listed more than once): {dupes}")
        return

    own = [n for n in names if n.startswith("b1cl2t")]
    if own != [COLL]:
        print(f"VERDICT: SCRIPT_ERROR - unique-prefix discipline broken: expected exactly "
              f" {[COLL]}, listed {own}")
        return

    print(f"OK: all {len(colls)} listed entries are {{name: non-empty string}} "
          f"CollectionDescriptions; no duplicates; own entry {COLL} present")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
