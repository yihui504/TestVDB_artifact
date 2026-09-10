#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_get_002
# strategy: strategy1_behavioral_negative
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 behavioral-negative x qdrant_behavioral_collections_get_001 (G4 negative branch - the assertion's core promise and its declared defect_type_if_violated: a MISSING collection must yield HTTP 404 with an error message, NEVER HTTP 200 with config)
Oracle: for 3 never-created syntactically-legal b2cget_* names (unique via timestamp; no PUT is ever issued against them), GET describe returns HTTP 404 on every probe with a non-empty body carrying an error indication (name or 'not found' text, case-insensitive); HTTP 200 = Type1_IllegalSuccess (config served for a nonexistent collection - the assertion's primary defect class), any other 4xx = Type4_StateLogicViolation (the contract pins the 404 channel for plain legal names), 5xx = Type3_RuntimeFailure, a 404 whose body carries no error indication at all = Type2_PoorDiagnostics

Constraint (bare id): qdrant_behavioral_collections_get_001
  expected_behavior: "existing collection: HTTP 200 with resolved config
  including defaults; missing collection: HTTP 404 with an error message
  (runtime verified: 'Not found: Collection ... doesn't exist!'), never 200
  with config"
  evidence_tier: explicit; level: endpoint; defect_type_if_violated:
  Type1_IllegalSuccess.

This is the exact surface where a misconfigured default handler (200 with an
empty/stale config skeleton for absent resources) would violate the contract:
the missing-collection case is the only input state that can flip the channel
to the forbidden 200.

Face-dispatch note (dispatch prompt, proven in sibling chains this session):
this describe face demonstrably 404s unknown names - the probes below use
never-created names only; no cleanup is required (we delete nothing).

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url;
R12 lesson - established pattern):
  collections+get -> GET /collections/{collection_name}
  healthz         -> GET /healthz
"""

import json
import os
import sys
import time
import uuid
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
PATH_GET = "/collections/{collection_name}"   # collections+get


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
# Three never-created, syntactically-legal names in different shapes:
# uuid-ish, long-64, and short-mixed-case. None is ever PUT-created here.
NEVER_CREATED = [
    f"b2cget_neg_{uuid.uuid4().hex[:12]}",
    "b2cget_neg_" + "x" * 64 + f"_{TS}",
    f"B2CGET-NEG-Upper-{TS}",
]


def main():
    for name in NEVER_CREATED:
        print(f"--- probe: GET describe on never-created '{name}' (len={len(name)}) ---")
        st, body, raw = safe_request("GET", PATH_GET.format(collection_name=name), timeout=30)
        print(f"status={st}")
        print(f"raw: {raw[:400]}")

        if st == -1:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"transport failure on probe (healthz status={hs}: {hraw[:200]})")
            print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
            return
        if 500 <= st <= 599:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - describe on a "
                  f"never-created name returned server error {st}")
            return
        if 200 <= st <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - describe on the "
                  f"never-created collection '{name}' returned HTTP {st} "
                  f"(raw: {raw[:300]}); assertion explicitly forbids 200 for a "
                  f"missing collection: 'never 200 with config'")
            return
        if st != 404:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - expected the "
                  f"pinned 404 channel for a missing collection with a plain legal "
                  f"name, got {st}: {raw[:300]}")
            return

        # 404 branch: expected_behavior demands an error message; threat_model
        # by-design list only exempts the error STRUCTURE (field names), not the
        # presence of a message. Gate: body must carry some error indication.
        low = raw.lower()
        if not raw.strip() or ("not found" not in low and name.lower() not in low
                               and "error" not in low):
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) - 404 as pinned, but "
                  f"the body carries no error indication at all (expected message per "
                  f"assertion, e.g. 'Not found: Collection ... doesn't exist!'): "
                  f"{raw[:200]!r}")
            return
        print(f"OK: never-created name -> 404 with error message")

    print("OK: all 3 never-created names -> HTTP 404 with an error message (never 200)")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
