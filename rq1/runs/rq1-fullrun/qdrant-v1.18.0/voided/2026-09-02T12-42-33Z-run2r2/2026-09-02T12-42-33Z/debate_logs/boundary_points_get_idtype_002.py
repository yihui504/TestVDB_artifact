#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_get_idtype_002
# strategy: strategy2 type-boundary attack (ids CONTAINER-level forms:
#           required-field absence, null, object, comma-string, and the
#           empty-array zero-closure) + strategy5 error-diagnostics
#           assessment on the required-field leg
# endpoint: points+get
# constraint_ids: qdrant_behavioral_points_get_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/get-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — request_required_paths
#            declares ids REQUIRED on this face; a missing/null/mistyped
#            ids must fail cleanly, and the empty array must not degrade
#            into an error or a crash)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 ids-container forms x qdrant_behavioral_points_get_002 —
  R31/R37 lesson leg: on this face (POST /collections/{name}/points) the
  body field "ids" is REQUIRED (request_required_paths: ids). Hard legs,
  each its own request: empty body {} (ids absent); {"with_payload": true}
  (ids absent, other field present); {"ids": null}; {"ids": {}} (object);
  {"ids": "401"} (scalar string — not an array of PointIds). Each must be
  a clean 400/422 naming the problem (strategy5 diagnostics check on the
  ids-absent leg: the 4xx must mention "ids"). Soft zero-closure leg:
  {"ids": []} — zero requested ids means zero found ids, so the
  shape-consistent answer is 200 with result == [] ("one Record per found
  id": 0 found -> 0 records); a clean 4xx is also defensible; only 5xx or
  a non-array/errored 200 is a defect.
  [chunk_points+get coverage: strategy1 defaults-matrix x _001
  (defaults_001); strategy1 selector-projection x _001 (defaults_002);
  strategy2 flag-type x _001 (type_001); strategy1 missing-arithmetic x
  _002 (missing_001); strategy1 multiplicity+duality x _002 (dupes_001);
  strategy1+2 PointId domain x _002 (idtype_001); strategy2 ids-container
  x _002 (this script); strategy6 resource x _002 (ids_size_001)]
Oracle: hard legs -> HTTP 400/422 (required field ids must be enforced);
  HTTP 200 on a hard leg = Type1_IllegalSuccess (BS-01 — request accepted
  without its required field / with a mistyped ids); 5xx with /healthz
  alive = Type3_RuntimeFailure; soft leg ids=[] -> 200 with result == []
  OR clean 4xx (observed branch reported for the judge; defect only on
  5xx, or a 200 whose result is not an empty array); the 4xx for the
  ids-absent leg that does not mention "ids" = Type2_PoorDiagnostics;
  transport failure -> /healthz re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_get_002).
Constraint: qdrant_behavioral_points_get_002 (bare id) — "batch get returns
  HTTP 200 with one Record per found id; ids that do not exist are omitted
  from the result without erroring" (evidence_tier: explicit; level:
  endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+get          -> POST /collections/{collection_name}/points   (body field ids is REQUIRED — R31/R37 lesson; NO /points/get suffix exists)
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
  (wait is a query parameter on the upsert face — passed via params=)
"""

import json
import os
import sys
import uuid
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap: three-layer fallback (env -> upward walk -> contract target) ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    _root = Path(__file__).resolve()
    for _p in (_root, *list(_root.parents)):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or TARGET != "qdrant":
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)

DIM = 4
V = [0.5, 0.25, 0.125, 0.0625]


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, headers=headers,
            timeout=timeout, params=params,
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


def healthz_alive():
    """Inline liveness probe on the lightweight healthz face."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def transport_dead(where):
    """Transport-branch liveness re-check (lightweight healthz face only)."""
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return False


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpgC7" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": [{"id": 401, "vector": V, "payload": {"k": 1}}]},
                                 params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        def defect(kind, leg, detail):
            print(f"VERDICT: DEFECT_FOUND ({kind}) — leg [{leg}]: {detail}")

        # sanity leg: the face works with a well-formed body before attacking it
        s, _, raw = safe_request("POST", f"/collections/{coll}/points",
                                 json={"ids": [401]}, timeout=60)
        print(f"sanity well-formed ids=[401] -> status={s}")
        if s == -1 and not transport_dead("sanity leg"):
            return
        if s != 200:
            print(f"VERDICT: SCRIPT_ERROR — sanity get returned {s}; no defect conclusion")
            return

        # ---- Hard legs: ids required/mistyped — each its own request ----
        hard_legs = [
            ("body {} (ids absent)",        {}),
            ("ids absent, wp present",      {"with_payload": True}),
            ("ids = null",                  {"ids": None}),
            ("ids = {} (object)",           {"ids": {}}),
            ("ids = '401' (scalar string)", {"ids": "401"}),
        ]
        for leg_name, body in hard_legs:
            s, _, raw = safe_request("POST", f"/collections/{coll}/points",
                                     json=body, timeout=60)
            print(f"leg {leg_name} -> status={s}")
            print(f"raw: {raw[:300]}")
            if s == -1 and not transport_dead(f"leg {leg_name}"):
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    defect("Type3_RuntimeFailure", leg_name,
                           f"malformed ids container got 5xx ({s}) instead of clean 4xx: "
                           f"{raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if 200 <= s <= 299:
                defect("Type1_IllegalSuccess", leg_name,
                       f"request accepted with ids={json.dumps(body)[:120]} — ids is the "
                       f"REQUIRED array field on this face (BS-01 coercion / required-field "
                       f"gap): {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on {leg_name}; no defect conclusion")
                return
            # strategy5 diagnostics check on the required-field leg
            if leg_name == "ids absent, wp present":
                if "ids" not in raw.lower():
                    defect("Type2_PoorDiagnostics", leg_name,
                           f"4xx for the missing required field does not name 'ids': "
                           f"{raw[:300]}")
                    return
                print("diagnostics OK: 4xx names the required field ids")
            print(f"leg {leg_name} OK: clean 4xx rejection")

        # ---- Soft zero-closure leg: ids == [] ----
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": []}, timeout=60)
        print(f"leg ids=[] (zero-closure, soft) -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1 and not transport_dead("leg ids=[]"):
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                defect("Type3_RuntimeFailure", "ids=[]",
                       f"empty ids array got 5xx ({s}) — zero-found must degrade cleanly: "
                       f"{raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        if 200 <= s <= 299:
            result = body_resp.get("result") if isinstance(body_resp, dict) else None
            if not isinstance(result, list):
                defect("Type1_IllegalSuccess", "ids=[]",
                       f"200 but envelope result is not an array: {raw[:300]}")
                return
            if len(result) != 0:
                defect("Type4_StateLogicViolation", "ids=[]",
                       f"0 ids requested -> 0 found -> result must be [], got {len(result)} "
                       f"records: {raw[:300]}")
                return
            print("leg ids=[] OK: 200 with result == [] (0 found -> 0 records)")
        elif s in (400, 422):
            print("leg ids=[] observed branch: clean 4xx rejection (reported for judge; "
                  "shape-consistent alternative)")
        else:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on ids=[]; no defect conclusion")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
