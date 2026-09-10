#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_optimizations_004
# strategy: strategy2_type_boundary
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — an integer-typed optional query param
#            must be type-checked, not coerced, and must never crash the readout face)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_behavioral_collections_optimizations_001 —
type-confusion probes against the OPTIONAL integer query parameter completed_limit of the
optimizations readout face (parameter placement: query string, per contract api_endpoints
parameter list — never stuffed into a body): non-integer literals "abc", float "1.5",
negative "-1", empty "", and a duplicated completed_limit=0&completed_limit=1 must each be
answered by the server with either a clean 4xx reject or a 200 whose documented envelope
(result object with summary aggregation) stays intact — 5xx/panic/parse-internal-error
leakage = Type3_RuntimeFailure (the readout face must survive malformed optional input).
Oracle: control GET (no params) on the live b1opt4t_* collection -> HTTP 200 with result
object; every completed_limit probe -> EITHER HTTP 4xx (clean reject) OR HTTP 200 with the
result-object envelope intact; 5xx/connection-reset/panic keywords = Type3_RuntimeFailure,
200-without-result-object = Type4_StateLogicViolation, transport failure re-checked with a
/healthz probe -> SCRIPT_ERROR
Constraint: qdrant_behavioral_collections_optimizations_001 (bare id) — "returns 200 with
optimizer status per shard; 404 for a missing collection" (evidence_tier: explicit; level:
endpoint). The face must keep answering its documented 200 status readout while optional
typed params are type-probed; a crash/5xx on any probe breaks the endpoint promise.

[coverage: strategy2 x qdrant_behavioral_collections_optimizations_001; unit assertions::qdrant_behavioral_collections_optimizations_001]
Shape anchor (D3b + R14 standing lesson): success-path assertions only reference
response_shape-declared paths (result: object; result.summary: object) — 200 responses are
gated on the result object envelope, present-group typing only; message fields are never
gated. Raw bodies printed per probe for the judge.

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  collections+optimizations -> GET    /collections/{collection_name}/optimizations
  collections+create        -> PUT    /collections/{collection_name}
  collections+delete        -> DELETE /collections/{collection_name}
  healthz                   -> GET    /healthz
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

# URL registry - verbatim from raw_knowledge.json api_endpoints[].url
PATH_OPTIMIZATIONS = "/collections/{collection_name}/optimizations"   # collections+optimizations
PATH_CREATE = "/collections/{collection_name}"                        # collections+create
PATH_DELETE = "/collections/{collection_name}"                        # collections+delete


def safe_request(method, endpoint, json=None, timeout=10, data=None, params=None):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md),
    extended per R14/R15 standing lessons to forward raw bodies (data=) and query params
    (params=) exactly. Returns: (status_code, body, raw_text)
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


COLL = "b1opt4t_" + uuid.uuid4().hex[:10]   # unique-prefix discipline: only this script's resource

# Type-confusion probes on the integer-typed optional query param (query string placement).
PROBES = [
    ("completed_limit=abc (non-integer literal)", dict(params={"completed_limit": "abc"})),
    ("completed_limit=1.5 (float literal)", dict(params={"completed_limit": "1.5"})),
    ("completed_limit=-1 (negative literal)", dict(params={"completed_limit": "-1"})),
    ("completed_limit= (empty value)", dict(params={"completed_limit": ""})),
    ("completed_limit=0&completed_limit=1 (duplicate key)", dict(params={"completed_limit": ["0", "1"]})),
]


def cleanup():
    """Teardown: best-effort delete of ONLY the collection this script created."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")), timeout=30)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    # ---- Arrange: live collection (setup gate, then control probe) ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
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

    path = PATH_OPTIMIZATIONS.format(collection_name=quote(COLL, safe=""))
    st, body, raw = safe_request("GET", path, timeout=30)
    print(f"control GET optimizations (no params) -> status={st}")
    print(f"control raw: {raw[:400]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on control (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if not (200 <= st <= 299):
        print(f"VERDICT: SCRIPT_ERROR - control probe failed with {st}: {raw[:300]}")
        return
    if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
        print(f"VERDICT: SCRIPT_ERROR - control 200 lacks the result envelope: {raw[:300]}")
        return

    # ---- Act: type-confusion probes on completed_limit ----
    for label, kwargs in PROBES:
        st, body, raw = safe_request("GET", path, timeout=30, **kwargs)
        print(f"probe {label!r} -> status={st}")
        print(f"raw (first 400 chars): {raw[:400]}")

        if st == -1:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"transport failure on probe (healthz status={hs}: {hraw[:200]})")
            print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
            return
        if 500 <= st <= 599:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - probe {label} triggered "
                  f"server error {st} (readout face must survive malformed optional query "
                  f"input with a clean 4xx or a 200)")
            return
        low = raw.lower()
        if any(k in low for k in ("panic", "internal", "capacity overflow", "oom")):
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - probe {label} leaked a "
                  f"parser/internal error: {raw[:300]}")
            return
        if 200 <= st <= 299:
            if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - probe {label} "
                      f"returned 200 but the result-object envelope is gone: {raw[:300]}")
                return
            print(f"probe {label}: 200 accepted with envelope intact (recorded)")
        else:
            print(f"probe {label}: clean {st} reject (recorded)")

    print("OK: all completed_limit type probes answered without 5xx/crash; "
          "200s kept the result envelope")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
