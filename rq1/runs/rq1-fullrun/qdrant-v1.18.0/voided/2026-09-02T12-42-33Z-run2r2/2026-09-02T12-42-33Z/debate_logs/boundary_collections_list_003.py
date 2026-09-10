#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_list_003
# strategy: strategy4_special_value
# endpoint: collections+list
# constraint_ids: qdrant_behavioral_collections_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collections
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (serde/encoding trust: the list face must round-trip non-ASCII names
# byte-exactly, not a mangled/escaped replacement)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy4 special-value x qdrant_behavioral_collections_list_001 — unicode round-trip
fidelity of the list face: a collection name containing CJK + emoji + zero-width space
("中文测试\U0001F3AF​") accepted by the create face must be echoed
byte-exactly (Python ==) by GET /collections.
[coverage: strategy4 x collections_list_001; unit assertions::qdrant_behavioral_collections_list_001]
Oracle: if PUT-create of the exotic name b1cl3u{tag}_<CJK><emoji><ZWSP> succeeds (2xx), then
GET /collections returns HTTP 200 and result.collections contains exactly one entry whose
name == the created name (exact string equality, same length — no truncation, no escaping, no
replacement); missing or altered name = Type4_StateLogicViolation; 5xx on the list face =
Type3_RuntimeFailure; 404/422 on the legal GET = Type1_IllegalRejection; a 4xx from the
create face = SCRIPT_ERROR (create-side acceptance of exotic names is the collections+create
chunk's unit, not adjudicated here — G3 avoidance).
Constraint: qdrant_behavioral_collections_list_001 (bare id) — "returns 200 with an array of
{name} CollectionDescription entries" (evidence_tier: explicit; level: endpoint). The {name}
promised by the list face is the name the create face accepted; cross-face disagreement
(G9) breaks the identifier contract.

Shape anchor (D3b + R14 standing lesson — cross-checked against the published OpenAPI):
contract api_endpoints['collections+list'].response_shape mirrors the describe face
(extraction artifact); the doc_quote and published v-1-18-x OpenAPI ListCollectionsResponse
govern: result.collections[] with string name per item.

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

TAG = uuid.uuid4().hex[:8]
# Exotic-but-legal name: ASCII prefix (traceability) + CJK + emoji + zero-width space.
EXOTIC = "中文测试\U0001F3AF​"
COLL = "b1cl3u" + TAG + "_" + EXOTIC


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


def cleanup():
    """Teardown: best-effort delete of ONLY the collection this script created."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")), timeout=30)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    print(f"collection under test (repr): {COLL!r}")

    # ---- Arrange: create the exotic-named collection (create face used only as setup) ----
    st, _, raw = safe_request(
        "PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
        json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    print(f"setup create: status={st}")
    print(f"setup raw: {raw[:300]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on setup (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure in setup, no defect conclusion")
        return
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - create face returned server "
              f"error {st} for a unicode name (list-face round-trip unreachable)")
        return
    if st not in (200, 201):
        print(f"note: create face rejected the exotic name with {st} — create-side acceptance "
              f"is the collections+create chunk's unit; list-face round-trip not testable")
        print(f"VERDICT: SCRIPT_ERROR - setup rejected by create face: {st} {raw[:300]}")
        return

    # ---- Act: list all collections ----
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
              f"server error {st} while an exotic-named collection exists")
        return
    if st in (404, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) - legal GET /collections wrongly "
              f"rejected with {st} (promise: 200 with array of {{name}})")
        return
    if not (200 <= st <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - expected HTTP 200 for "
              f"GET /collections, got {st}")
        return

    # ---- Assert: envelope + byte-exact round-trip ----
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

    matches = []
    prefix_base = "b1cl3u" + TAG
    for e in colls:
        if isinstance(e, dict) and isinstance(e.get("name"), str):
            if e["name"] == COLL:
                matches.append(e["name"])
            elif e["name"].startswith(prefix_base):
                matches.append(e["name"])  # near-miss: same prefix but different bytes
    if len(matches) != 1 or matches[0] != COLL:
        near = [n for n in matches if n != COLL]
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - the list face must echo "
              f"the created name byte-exactly; exact matches={len([m for m in matches if m == COLL])}, "
              f"near-miss prefixed entries (mangled/truncated echoes)={near!r}; expected {COLL!r}")
        return

    print(f"OK: exotic name round-tripped byte-exactly through the list face: {matches[0]!r}")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
