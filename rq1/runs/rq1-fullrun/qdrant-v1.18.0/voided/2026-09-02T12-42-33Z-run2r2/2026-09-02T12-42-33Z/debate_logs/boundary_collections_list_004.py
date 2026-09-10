#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_list_004
# strategy: strategy7_malformed_input_robustness
# endpoint: collections+list
# constraint_ids: qdrant_behavioral_collections_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collections
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (parser/serde robustness: malformed input streams must yield clean 4xx
# or be ignored, never 5xx/panic)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-input / unexpected-input robustness x
qdrant_behavioral_collections_list_001 — the parameterless GET /collections is probed with
(a) a raw truncated-JSON body, (b) a raw NUL-byte body, (c) foreign query params that belong
to other endpoints (limit=0, offset=-1), (d) a NUL byte inside a query-param value, (e) a
10k-char overlong query-param value; none of these may crash the endpoint or corrupt the
documented envelope.
[coverage: strategy7 x collections_list_001; unit assertions::qdrant_behavioral_collections_list_001]
Oracle: control GET /collections -> HTTP 200 with a parseable result.collections array; each
malformed/abnormal probe returns EITHER HTTP 200 with an intact parseable result.collections
array (input ignored) OR a clean 4xx (400/404/414/422/431 — explicit rejection); HTTP
500/502/503/504 or a panic/OOM/serde/internal marker in the body = Type3_RuntimeFailure;
HTTP 200 with a missing/non-array result.collections = Type4_StateLogicViolation; control
GET 5xx = Type3_RuntimeFailure, control GET 4xx = Type1_IllegalRejection (legal request).
Constraint: qdrant_behavioral_collections_list_001 (bare id) — "returns 200 with an array of
{name} CollectionDescription entries" (evidence_tier: explicit; level: endpoint). The promise
is conditional on a well-formed request; malformed input streams must be answered with a
clean client error or ignored — never a server failure.

Method note (strategy 7 safety wrapper): raw malformed bodies are sent via safe_request's
data= parameter (bytes) so client-side JSON serialization cannot pre-reject them; the
wrapper still owns timeout/error handling per agents/_target_api_reference.md (R14 lesson:
wrapper forwards data/query params exactly).

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
COLL = "b1cl4m" + TAG


def safe_request(method, endpoint, json=None, timeout=10, data=None, params=None):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md),
    extended per strategy-7 discipline to forward raw bodies (data=) and query params
    (params=) exactly (R14 lesson). Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, data=data, params=params,
            headers=headers, timeout=timeout
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


def envelope_intact(body):
    """True iff body carries the documented result.collections[] array envelope."""
    if not isinstance(body, dict):
        return False
    result = body.get("result")
    if not isinstance(result, dict):
        return False
    return isinstance(result.get("collections"), list)


PANIC_MARKERS = ("panic", "out of memory", "oom", "serde", "capacity overflow", "killed")


def adjudicate(label, st, body, raw):
    """Declare expectation, then compare: returns defect verdict string or None.

    Expected per probe: 200 + intact envelope, or clean 4xx. Defect: 5xx/panic (Type3),
    or 200 with broken envelope (Type4).
    """
    print(f"probe [{label}] -> status={st}")
    print(f"probe [{label}] raw (first 300 chars): {raw[:300]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on probe {label} (healthz status={hs}: {hraw[:200]})")
        return "SCRIPT_ERROR"
    if 500 <= st <= 599:
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) - probe {label} on GET /collections "
                f"triggered server error {st}")
    low = raw.lower()
    for k in PANIC_MARKERS:
        if k in low:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) - probe {label} leaked a crash/"
                    f"parser marker ({k!r}) in the response body")
    if 200 <= st <= 299:
        if not envelope_intact(body):
            return (f"DEFECT_FOUND (Type4_StateLogicViolation) - probe {label} was accepted "
                    f"with {st} but the documented result.collections[] envelope is missing/"
                    f"malformed in the response")
        print(f"OK: probe {label} ignored the malformed input; envelope intact")
        return None
    if 400 <= st <= 499:
        print(f"OK: probe {label} cleanly rejected with client error {st}")
        return None
    return (f"DEFECT_FOUND (Type4_StateLogicViolation) - probe {label} returned unexpected "
            f"status {st}")


def main():
    # ---- Arrange: one prefixed collection so the envelope has content to stay intact ----
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

    # ---- Act/Assert 0: control GET (legal request must be served) ----
    st, body, raw = safe_request("GET", PATH_LIST, timeout=30)
    print(f"control GET {PATH_LIST} -> status={st}")
    print(f"control raw (first 300 chars): {raw[:300]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on control GET (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - control GET /collections "
              f"returned server error {st}")
        return
    if st in (404, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) - control GET /collections "
              f"wrongly rejected with {st} (promise: 200 with array of {{name}})")
        return
    if not (200 <= st <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - expected HTTP 200 for "
              f"control GET /collections, got {st}")
        return
    if not envelope_intact(body):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - control GET returned "
              f"{st} but the documented result.collections[] envelope is missing/malformed: "
              f"{raw[:300]}")
        return
    print("OK: control GET served with intact envelope")

    # ---- Act/Assert 1..5: malformed / unexpected input probes ----
    probes = [
        ("raw truncated-JSON body", dict(data=b'{"a":1')),
        ("raw NUL-byte body", dict(data=b"\x00\x01\x02\xff")),
        ("foreign query params limit=0 offset=-1", dict(params={"limit": "0", "offset": "-1"})),
        ("NUL byte in query-param value", dict(params={"x": "\x00"})),
        ("overlong 10k query-param value", dict(params={"x": "a" * 10000})),
    ]
    for label, kw in probes:
        st, body, raw = safe_request("GET", PATH_LIST, timeout=30, **kw)
        verdict = adjudicate(label, st, body, raw)
        if verdict == "SCRIPT_ERROR":
            print("VERDICT: SCRIPT_ERROR - transport failure on probe, no defect conclusion")
            return
        if verdict:
            print(f"VERDICT: {verdict}")
            return

    print("OK: all five malformed/unexpected-input probes answered without server failure "
          "and without envelope corruption")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
