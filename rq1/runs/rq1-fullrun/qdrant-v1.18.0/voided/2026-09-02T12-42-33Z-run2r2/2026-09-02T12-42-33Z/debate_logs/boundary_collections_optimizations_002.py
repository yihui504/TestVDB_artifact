#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_optimizations_002
# strategy: strategy1_boundary_behavioral_negative
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the absence face of the boundary: a name
#            that never existed must be refused, not answered with a phantom readout)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value / behavioral-negative x qdrant_behavioral_collections_optimizations_001
(G4 negative branch): the assertion's second face is "missing collection: HTTP 404" — a
GET /collections/{name}/optimizations on a never-created unique name (b1opt2n_*, no setup
call in this script) must return HTTP 404 exactly. A 2xx here reports optimizer status for a
collection that never existed (phantom readout = the face cannot express absence); a 5xx
means the absence face crashes instead of refusing.
Oracle: GET /collections/{never-created b1opt2n_* name}/optimizations -> HTTP 404 exactly
(assertion qdrant_behavioral_collections_optimizations_001 "missing collection: HTTP 404");
2xx = Type1_IllegalSuccess (phantom optimizer status for a nonexistent collection), 5xx =
Type3_RuntimeFailure, any other non-404 status (400/422/3xx) = Type4_StateLogicViolation
(documented refusal face not honored); transport failure is re-checked with a /healthz probe
and yields SCRIPT_ERROR, never a defect conclusion.
Constraint: qdrant_behavioral_collections_optimizations_001 (bare id) — "returns 200 with
optimizer status per shard; 404 for a missing collection" (evidence_tier: explicit; level:
endpoint; expected_behavior: "existing collection: HTTP 200 with per-shard optimizer status;
missing collection: HTTP 404").

[coverage: strategy1 x qdrant_behavioral_collections_optimizations_001; unit assertions::qdrant_behavioral_collections_optimizations_001]
Shape anchor (D3b + R14 standing lesson): the 404 leg is judged on HTTP status only — error
message structure is an implementation detail (threat-model by-design list), so the raw
body is printed for the judge but never gated. raw_knowledge expected_responses for this
endpoint: 200 ok / 404 not found.

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  collections+optimizations -> GET    /collections/{collection_name}/optimizations
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


# Unique-prefix discipline: this name is NEVER created (neither here nor by any other
# script in the session), so any 2xx answer is a phantom readout on a nonexistent collection.
NEVER_NAME = "b1opt2n_" + uuid.uuid4().hex[:10]


def main():
    # ---- Act: optimizations readout on a name that never existed ----
    st, body, raw = safe_request("GET",
                                 PATH_OPTIMIZATIONS.format(collection_name=quote(NEVER_NAME, safe="")),
                                 timeout=30)
    print(f"GET optimizations on never-created {NEVER_NAME} -> status={st}")
    print(f"raw: {raw[:500]}")

    # ---- Assert (declare expectation first, then compare) ----
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on never-created probe (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - optimizations on a never-created "
              f"collection returned server error {st} instead of the documented 404")
        return
    if st == 404:
        print(f"OK: never-created name -> 404 (documented absence face honored)")
        print("VERDICT: NO_DEFECT")
        return
    if 200 <= st <= 299:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - optimizations on never-created "
              f"collection {NEVER_NAME} returned {st} with a body; assertion requires HTTP 404 "
              f"for a missing collection (phantom optimizer-status readout)")
        return
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - expected HTTP 404 exactly for "
          f"a never-created collection, got {st}: {raw[:300]}")


if __name__ == "__main__":
    main()
