#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_get_missing_001
# strategy: strategy1 boundary-value attack (found/missing arithmetic
#           closure — R33-style arithmetic-derived count expectations with
#           id-collision analysis: every expectation is derived from the
#           seeded id set, never eyeballed)
# endpoint: points+get
# constraint_ids: qdrant_behavioral_points_get_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/get-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the all-missing request is
#            the zero-found boundary of "one Record per found id; missing
#            ids are simply absent, not an error")
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 missing-id arithmetic closure x
  qdrant_behavioral_points_get_002 — the contract promises HTTP 200 with one
  Record per FOUND id and ids that do not exist are OMITTED from the result
  without erroring. Seed ids {201..205} (5 points, disjoint from the
  999xxx missing-space — no id collisions). Legs across the whole found/
  missing spectrum: mixed 2-found+2-missing; all-found (5); all-missing
  (3); single-missing (1). Every leg judged by exact arithmetic:
  len(result) == number of requested ids that exist, id-set equality, and
  every result entry is a Record object carrying id (response_shape
  result[]: object, result[].id).
  [chunk_points+get coverage: strategy1 defaults-matrix x _001
  (defaults_001); strategy1 selector-projection x _001 (defaults_002);
  strategy2 flag-type x _001 (type_001); strategy1 missing-arithmetic x
  _002 (this script); strategy1 multiplicity+duality x _002 (dupes_001);
  strategy1+2 PointId domain x _002 (idtype_001); strategy2 ids-container
  x _002 (idtype_002); strategy6 resource x _002 (ids_size_001)]
Oracle: every leg -> HTTP 200; mixed leg -> len(result)==2 and id set
  EXACTLY {201,203}; all-found leg -> len(result)==5 and id set {201..205};
  all-missing legs -> result == [] (a 404/4xx on all-missing would VIOLATE
  "missing ids are simply absent from the result, not an error" =
  Type1_IllegalSuccess); len mismatch or extra/missing ids = Type4_
  StateLogicViolation (Record-per-found-id arithmetic broken); 5xx with
  /healthz alive = Type3_RuntimeFailure; transport failure -> /healthz
  re-check then SCRIPT_ERROR (constraint qdrant_behavioral_points_get_002).
Constraint: qdrant_behavioral_points_get_002 (bare id) — "batch get returns
  HTTP 200 with one Record per found id; ids that do not exist are omitted
  from the result without erroring" (evidence_tier: explicit; level:
  endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+get          -> POST /collections/{collection_name}/points   (body field ids is REQUIRED — R31/R37 lesson)
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
SEEDED = [201, 202, 203, 204, 205]  # existing ids (999xxx space unused -> no collisions)


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
    coll = "bpgM4" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{"id": pid, "vector": V, "payload": {"n": pid - 200}} for pid in SEEDED]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        def defect(kind, leg, detail):
            print(f"VERDICT: DEFECT_FOUND ({kind}) — leg [{leg}]: {detail}")

        # (leg_name, requested_ids, expected_found_ids) — expectations arithmetic-derived
        legs = [
            ("mixed 2found+2missing", [201, 999001, 203, 999002], [201, 203]),
            ("all-found 5",          [201, 202, 203, 204, 205],   SEEDED),
            ("all-missing 3",        [999101, 999102, 999003],    []),
            ("single-missing 1",     [999999],                     []),
        ]
        for leg_name, req_ids, expected in legs:
            s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                             json={"ids": req_ids}, timeout=60)
            print(f"leg {leg_name} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1 and not transport_dead(f"leg {leg_name}"):
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    defect("Type3_RuntimeFailure", leg_name,
                           f"valid get returned {s} with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s in (400, 404, 422):
                defect("Type1_IllegalSuccess", leg_name,
                       f"get of {len(req_ids)} ids ({len(expected)} existing) errored with {s} — "
                       f"missing ids must be ABSENT from a 200 result, not an error "
                       f"('simply absent, not an error' broken): {raw[:300]}")
                return
            if s != 200:
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on {leg_name}; no defect conclusion")
                return
            result = body_resp.get("result") if isinstance(body_resp, dict) else None
            if not isinstance(result, list):
                defect("Type1_IllegalSuccess", leg_name,
                       f"200 but envelope result is not an array (response_shape result: "
                       f"array): {raw[:300]}")
                return
            for i, rec in enumerate(result):
                if not isinstance(rec, dict) or "id" not in rec:
                    defect("Type1_IllegalSuccess", leg_name,
                           f"result[{i}] is not a Record object with id (response_shape "
                           f"result[]: object, result[].id): {json.dumps(rec)[:200]}")
                    return
            got_ids = [rec.get("id") for rec in result]
            # arithmetic: one Record per found id — exactly the requested-existing set
            if len(got_ids) != len(expected) or set(got_ids) != set(expected):
                defect("Type4_StateLogicViolation", leg_name,
                       f"requested {req_ids} with {len(expected)} existing -> must return "
                       f"EXACTLY {len(expected)} records with ids {expected}, got "
                       f"{len(got_ids)} records with ids {got_ids}: {raw[:300]}")
                return
            if len(got_ids) != len(set(got_ids)):
                defect("Type4_StateLogicViolation", leg_name,
                       f"duplicate records for one found id (one-Record-per-found-id "
                       f"broken): {got_ids}: {raw[:200]}")
                return
            print(f"leg {leg_name} OK: {len(got_ids)} records, ids exactly as derived")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
