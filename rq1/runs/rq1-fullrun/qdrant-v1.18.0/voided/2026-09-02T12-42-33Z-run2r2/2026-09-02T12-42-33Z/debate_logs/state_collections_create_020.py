#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_020
# strategy: no_residue_after_reject
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_005
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: rejected-query-param no-residue + boundary closure on
  PUT /collections/{name} (collections+create; URL from raw_knowledge
  api_endpoints[].url). The behavioral assertion promises: timeout values
  below 1 are rejected with an error (the create-collection query schema
  pins timeout minimum 1), never silently accepted. timeout is a QUERY
  parameter (never body — qdrant silent-drops body-placed wait/timeout
  params; v34 R1 S1 lesson). Legs: (N) create with ?timeout=0 on a fresh
  name -> expect 422/4xx (v1.18.0 runtime observed: 'Validation error in
  query parameters: [timeout: value 0 invalid, must be 1 or larger]');
  a 4xx must leave no ghost state (describe 404, name absent from list);
  (P) boundary closure on the SAME name with ?timeout=1 (the schema
  minimum itself) -> must now be 200 and describe 200 — reusing the name
  doubles as a second ghost detector (a residue from N would surface as
  a 409 here).
  [chunk_collections+create-2of2 coverage: no_residue_after_reject x
   qdrant_behavioral_collections_create_005 (sub-minimum rejection +
   min-closure + ghost-state absence)]
Oracle: ?timeout=0 -> 4xx (422 observed), never 200 (200 =
  Type1_IllegalSuccess); after the 4xx describe must be 404 and the name
  absent from list_collections (lingering state = Type4
  ghost); ?timeout=1 on the same name -> 200 with describe 200 (409 here
  = ghost from N = Type4; 4xx on the legal minimum = closure violation);
  5xx judged Type3 only after /healthz confirms liveness.
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


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)

def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scc2f_" + TS + "_"
    C = PFX + "tmo"
    DEFECTS = []

    try:
        # ---- (N) sub-minimum query timeout on a fresh name ----
        sn, rawn = safe_request("PUT", "create_collection",
                                path_params={"name": C},
                                body={"vectors": {"size": 4, "distance": "Euclid"}},
                                query_params={"timeout": 0})
        print(f"[N create ?timeout=0] status={sn} raw={rawn[:300]}")
        if sn == 0:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness N-transport] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                print("DEFECT: (N) timeout=0 create transport-failed and /healthz "
                      "is not 200 — service down on invalid input — "
                      "Type3_RuntimeFailure")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if 500 <= sn <= 599:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness N-5xx] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                return "SCRIPT_ERROR"
            print(f"DEFECT: (N) timeout=0 returned {sn} with service alive — "
                  f"assertion promises a rejection error — "
                  f"Type3_RuntimeFailure — raw={rawn[:200]}")
            return "DEFECT_FOUND"
        if sn in (200, 201):
            DEFECTS.append(f"(N) timeout=0 (below schema minimum 1) silently "
                           f"accepted with {sn} — Type1_IllegalSuccess "
                           f"(qdrant_behavioral_collections_create_005)")
        elif not (400 <= sn <= 499):
            print(f"OBSERVATION (N): unexpected status {sn} for timeout=0")

        if sn == 408:
            print("OBSERVATION (N): 408 operation timeout — not a definitive "
                  "rejection; no ghost claim")
        elif 400 <= sn <= 499:
            # rejected: no ghost state may remain
            gs, graw = safe_request("GET", "describe_collection",
                                    path_params={"name": C})
            print(f"[N describe-after-reject] status={gs} raw={graw[:200]}")
            if gs != 404:
                DEFECTS.append(f"(N) timeout=0 create rejected with {sn} but "
                               f"describe returned {gs} (expected 404) — ghost "
                               f"collection state — Type4_StateLogicViolation")
            ls, lraw = safe_request("GET", "list_collections")
            present = (ls == 200 and C in (lraw or ""))
            print(f"[N list-membership] status={ls} present={present}")
            if ls == 200 and present:
                DEFECTS.append(f"(N) rejected collection '{C}' still present in "
                               f"list_collections — stale list state — "
                               f"Type4_StateLogicViolation")

        # ---- (P) boundary closure: timeout=1 (schema minimum) on SAME name ----
        sp, rawp = safe_request("PUT", "create_collection",
                                path_params={"name": C},
                                body={"vectors": {"size": 4, "distance": "Euclid"}},
                                query_params={"timeout": 1})
        print(f"[P create ?timeout=1] status={sp} raw={rawp[:300]}")
        if sp == 0:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness P-transport] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                print("DEFECT: (P) timeout=1 create transport-failed and /healthz "
                      "is not 200 — Type3_RuntimeFailure")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if 500 <= sp <= 599:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness P-5xx] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                return "SCRIPT_ERROR"
            print(f"DEFECT: (P) timeout=1 create returned {sp} with service alive — "
                  f"Type3_RuntimeFailure — raw={rawp[:200]}")
            return "DEFECT_FOUND"
        if sp == 409:
            DEFECTS.append(f"(P) timeout=1 create got 409 although the timeout=0 "
                           f"request on this name returned {sn} — residue of that "
                           f"prior request (rejected-request ghost or in-progress "
                           f"state of an illegally accepted one) — "
                           f"Type4_StateLogicViolation")
        elif sp not in (200, 201):
            DEFECTS.append(f"(P) timeout=1 (the schema minimum itself) rejected "
                           f"with {sp} — boundary closure violated: min 1 must be "
                           f"accepted — Type4_StateLogicViolation — raw={rawp[:200]}")
        else:
            gs, graw = safe_request("GET", "describe_collection",
                                    path_params={"name": C})
            print(f"[P describe] status={gs} raw={graw[:200]}")
            if gs != 200:
                DEFECTS.append(f"(P) timeout=1 create returned 200 but describe "
                               f"returned {gs} — created state absent — "
                               f"Type4_StateLogicViolation")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
