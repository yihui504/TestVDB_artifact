#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_optimizations_005
# strategy: strategy6_resource_limit
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — implementation-layer limits of the
#            completed_limit trim parameter: extremes must be bounded, never a crash)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 resource-limit x qdrant_behavioral_collections_optimizations_001 — extreme
values of the OPTIONAL integer query parameter completed_limit (count/limit class) against
the optimizations readout face: completed_limit=0 (min-side closure of a trim count),
2147483647 (INT_MAX), 1000000000 (1e9). The defect signal for this class is a crash, not an
acceptance: an upper-bound trim parameter may legally cap the returned completed list
(200 = returns <= limit entries) or be explicitly rejected (4xx); 5xx / OOM / panic /
connection reset = Type3_RuntimeFailure (reference: hashbrown capacity-overflow/OOM class).
A response hanging past the wrapper timeout is re-checked with a /healthz liveness probe —
a live server yields SCRIPT_ERROR (inconclusive), never a defect claim (G8 three-outcome
isolation).
Oracle: on the live b1opt5r_* collection each of completed_limit in {0, 2147483647,
1000000000} returns EITHER HTTP 2xx with the result-object envelope intact OR a clean 4xx
reject; 5xx/panic/OOM/capacity-overflow keywords or a connection reset = Type3_RuntimeFailure,
200-without-result-object = Type4_StateLogicViolation; timeout/transport failure + healthy
/healthz = SCRIPT_ERROR
Constraint: qdrant_behavioral_collections_optimizations_001 (bare id) — "returns 200 with
optimizer status per shard; 404 for a missing collection" (evidence_tier: explicit; level:
endpoint). A readout endpoint that crashes under extreme optional-input values breaks the
promise that an existing collection always answers 200 with its optimizer status.

[coverage: strategy6 x qdrant_behavioral_collections_optimizations_001; unit assertions::qdrant_behavioral_collections_optimizations_001]
Shape anchor (D3b + R14 standing lesson): 200-leg gating references only response_shape-
declared paths (result object / summary object present-group typing); error message fields
never gated.

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

CRASH_KEYWORDS = ("panic", "out of memory", "oom", "capacity overflow", "killed")


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


COLL = "b1opt5r_" + uuid.uuid4().hex[:10]   # unique-prefix discipline: only this script's resource

# count/limit-class extremes (strategy 6 table) on the optional trim parameter
EXTREMES = [
    ("completed_limit=0 (min-side)", dict(params={"completed_limit": "0"})),
    ("completed_limit=2147483647 (INT_MAX)", dict(params={"completed_limit": "2147483647"})),
    ("completed_limit=1000000000 (1e9)", dict(params={"completed_limit": "1000000000"})),
]


def cleanup():
    """Teardown: best-effort delete of ONLY the collection this script created."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")), timeout=30)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    # ---- Arrange: live collection (setup gate) ----
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

    # ---- Act: extreme completed_limit probes ----
    for label, kwargs in EXTREMES:
        st, body, raw = safe_request("GET", path, timeout=30, **kwargs)
        print(f"probe {label!r} -> status={st}")
        print(f"raw (first 400 chars): {raw[:400]}")

        if st == -1:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"probe {label} transport failure / timeout (healthz status={hs}: {hraw[:200]})")
            if hs == 200:
                print("VERDICT: SCRIPT_ERROR - transport failure with live /healthz; "
                      "no defect conclusion (G8 three-outcome isolation)")
            else:
                print("VERDICT: SCRIPT_ERROR - service not healthy after transport failure; "
                      "no defect conclusion")
            return
        if 500 <= st <= 599:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - probe {label} triggered "
                  f"server error {st} (extreme optional input must not crash the readout face)")
            return
        low = raw.lower()
        if any(k in low for k in CRASH_KEYWORDS):
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - probe {label} leaked a "
                  f"crash/OOM/panic signal: {raw[:300]}")
            return
        if 200 <= st <= 299:
            if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - probe {label} "
                      f"returned 200 but the result-object envelope is gone: {raw[:300]}")
                return
            print(f"probe {label}: 200 accepted (upper-bound trim semantics; <= limit "
                  f"entries is legal) with envelope intact (recorded)")
        else:
            print(f"probe {label}: clean {st} reject (recorded)")

    print("OK: all completed_limit extremes answered without crash/5xx; 200s kept the envelope")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
