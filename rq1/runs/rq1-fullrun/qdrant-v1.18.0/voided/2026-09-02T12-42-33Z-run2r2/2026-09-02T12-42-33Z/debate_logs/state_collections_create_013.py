#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_013
# strategy: delete_consistency
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: query-parameter face of PUT /collections/{name} (collections+create)
  — the timeout query param. The range constraint pins schema minimum 1
  (seconds to wait before the operation times out). The timeout param is a
  URL query parameter (never request body — body placement is silently
  dropped, v34 R1 S1 lesson; forwarded via query_params exactly). Legs:
  (A) positive: create with ?timeout=1 (the minimum itself, G4 closure) ->
      200 AND the collection state actually materialized (describe -> 200):
      a create that times out client-side or half-commits would leave state
      inconsistent with the response.
  (B) negative: create with ?timeout=0 (below schema minimum) -> 400/422
      AND no residue (describe 404, name absent from list_collections).
      2xx acceptance = below-minimum value admitted (Type1_IllegalSuccess
      against the versioned OpenAPI minimum).
  [chunk_collections+create-1of2 coverage: delete_consistency (no-residue
  after rejected create; state-materialization check on accepted create) x
  qdrant_range_collections_create_001]
Oracle: (A) ?timeout=1 create -> 200 and describe -> 200 (missing state
  after a 2xx = Type4_StateLogicViolation); (B) ?timeout=0 -> 400/422 and
  describe -> 404 with name absent from list_collections (2xx = Type1;
  residue = Type4; 5xx = Type3 only after /healthz liveness)
"""

import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p / "scripts")
            break
if not _sd or not Path(_sd, "runtime", "__init__.py").exists():
    print("VERDICT: SCRIPT_ERROR - runtime scripts dir not found (TESTVDB_SCRIPTS_DIR unset)")
    sys.exit(2)
sys.path.insert(0, _sd)

if not os.environ.get("TESTVDB_TARGET"):
    for _p in Path(__file__).resolve().parents:
        _c = _p / "structured_contract.json"
        if _c.exists():
            try:
                _t = json.loads(_c.read_text(encoding="utf-8")).get("target", "")
                if _t:
                    os.environ["TESTVDB_TARGET"] = str(_t).lower()
            except Exception:
                pass
            break

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

BODY = {"vectors": {"size": 4, "distance": "Cosine"}}


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; inline liveness probes (GET healthz)
    stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr13_" + TS + "_"
    CA = PFX + "tq1"
    CB = PFX + "tq0"
    DEFECTS = []

    try:
        # ---- (A) positive: ?timeout=1 (schema minimum) ----
        s, raw = safe_request("PUT", "create_collection", path_params={"name": CA},
                              body=BODY, query_params={"timeout": 1})
        print(f"[A timeout=1] status={s} raw={raw[:240]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[A transport] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on (A); liveness ok — skipped")
        elif 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[A liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(A) create with ?timeout=1 returned {s} (5xx; service alive "
                f"per /healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
            )
        elif s not in (200, 201):
            DEFECTS.append(
                f"(A) create with ?timeout=1 (schema minimum) rejected with "
                f"{s} — boundary closure violated — raw={raw[:200]}"
            )
        else:
            # state must actually be materialized after the 2xx
            gs, graw = safe_request("GET", "describe_collection",
                                    path_params={"name": CA})
            print(f"[A state] describe status={gs} raw={graw[:160]}")
            if gs != 200:
                DEFECTS.append(
                    f"(A) create returned 200 but describe -> {gs} — state not "
                    f"materialized / not queryable — Type4_StateLogicViolation "
                    f"(qdrant_inv_create_queryable_001)"
                )

        # ---- (B) negative: ?timeout=0 (below schema minimum) ----
        s2, raw2 = safe_request("PUT", "create_collection", path_params={"name": CB},
                                body=BODY, query_params={"timeout": 0})
        print(f"[B timeout=0] status={s2} raw={raw2[:240]}")
        if s2 == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[B transport] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on (B); liveness ok — skipped")
        elif 500 <= s2 <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[B liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(B) create with ?timeout=0 returned {s2} (5xx; service alive "
                f"per /healthz) — Type3_RuntimeFailure — raw={raw2[:200]}"
            )
        elif 200 <= s2 < 300:
            DEFECTS.append(
                f"(B) ?timeout=0 (below OpenAPI minimum 1) accepted with {s2} — "
                f"Type1_IllegalSuccess — raw={raw2[:200]}"
            )
        elif s2 not in (400, 422):
            print(f"OBSERVATION (B): rejection status {s2} outside 400/422 — recorded")
        # no-residue probe regardless of disposition
        gs2, graw2 = safe_request("GET", "describe_collection", path_params={"name": CB})
        if gs2 == 200:
            DEFECTS.append(
                f"(B) below-minimum-timeout create left residue: describe -> 200 "
                f"— ghost state — Type4_StateLogicViolation — raw={graw2[:200]}"
            )
        ls, lraw = safe_request("GET", "list_collections")
        if ls == 200 and CB in (lraw or ""):
            DEFECTS.append(
                f"(B) '{CB}' present in list_collections after below-minimum "
                f"create attempt — stale list state — Type4_StateLogicViolation"
            )

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for n in (CA, CB):
            try:
                rt.drop_collection(n)
            except Exception:
                pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
