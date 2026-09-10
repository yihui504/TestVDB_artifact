#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_get_ids_size_001
# strategy: strategy6 resource-limit attack (large ids arrays on the
#           batch-get face — no crash, exact arithmetic at scale) +
#           strategy1 arithmetic closure at 2k/5k scale
# endpoint: points+get
# constraint_ids: qdrant_behavioral_points_get_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/get-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-07 (Resource Exhaustion — the ids array has no documented
#            upper bound; a request-sized preallocation (dedup set, record
#            buffer) is the classic OOM/hang vector on this face)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 resource x qdrant_behavioral_points_get_002 — the
  contract states no upper bound for the ids array of the batch-get face.
  Two legs on a collection seeded with 2000 points (ids 100000..101999;
  the 900xxx/950xxx request space is disjoint — no id collisions):
  (a) 20000 ALL-MISSING ids — the worst case for "missing ids are simply
  absent": the server must build a 20k-request answer of zero records
  without crashing; (b) 5000 MIXED ids (2000 found + 3000 missing) — the
  found-set arithmetic must stay EXACT at scale (one Record per found id,
  no duplicates, no omissions). Resource-class adjudication: 200 or a
  clean 422/400 with a limit message = no defect; 5xx / OOM / hang with
  /healthz alive = Type3.
  [chunk_points+get coverage: strategy1 defaults-matrix x _001
  (defaults_001); strategy1 selector-projection x _001 (defaults_002);
  strategy2 flag-type x _001 (type_001); strategy1 missing-arithmetic x
  _002 (missing_001); strategy1 multiplicity+duality x _002 (dupes_001);
  strategy1+2 PointId domain x _002 (idtype_001); strategy2 ids-container
  x _002 (idtype_002); strategy6 resource x _002 (this script)]
Oracle: leg (a) 20000 all-missing ids -> HTTP 200 with result == [] (0
  found -> 0 records) or a clean 400/422 limit rejection (both reported;
  neither is a defect); leg (b) 5000 mixed ids -> if 200: len(result)==2000
  EXACTLY with id set == the 2000 seeded ids and no duplicate records
  (arithmetic mismatch = Type4_StateLogicViolation); a request TIMEOUT or
  connection error re-checked against /healthz: service alive = Type3_
  RuntimeFailure (hang), service dead = SCRIPT_ERROR; 5xx with /healthz
  alive = Type3_RuntimeFailure (OOM/DoS); 4xx on leg (b) = reported
  note, not a defect (resource-class norm) (constraint
  qdrant_behavioral_points_get_002).
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
N_SEED = 2000
SEED_BASE = 100000                    # seeded ids: 100000..101999
MISS_BASE_ALL = 900000                # all-missing space: 900000..919999 (disjoint)
MISS_BASE_MIX = 950000                # mixed-leg missing space: 950000..952999 (disjoint)


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


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpgR8" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{"id": SEED_BASE + i, "vector": V, "payload": {"i": i % 10}}
               for i in range(N_SEED)]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=180)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        def defect(kind, leg, detail):
            print(f"VERDICT: DEFECT_FOUND ({kind}) — leg [{leg}]: {detail}")

        # ---- Leg (a): 20000 all-missing ids (resource face of the missing promise) ----
        big_missing = [MISS_BASE_ALL + i for i in range(20000)]
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": big_missing}, timeout=90)
        print(f"leg (a) 20000 all-missing -> status={s}")
        print(f"raw head: {raw[:300]}")
        if s == -1:
            # resource-class adjudication: timeout/connection error -> liveness re-check
            alive, hs, hraw = healthz_alive()
            if alive:
                defect("Type3_RuntimeFailure", "(a) 20000 all-missing",
                       f"request did not complete (transport error) while /healthz is "
                       f"alive ({hs}: {hraw}) — hang/DoS signal on the ids-size face")
            else:
                print("VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                defect("Type3_RuntimeFailure", "(a) 20000 all-missing",
                       f"5xx ({s}) on a 20k all-missing ids request with service alive: "
                       f"{raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        if 200 <= s <= 299:
            result = body_resp.get("result") if isinstance(body_resp, dict) else None
            if not isinstance(result, list):
                defect("Type1_IllegalSuccess", "(a) 20000 all-missing",
                       f"200 but envelope result is not an array: {raw[:300]}")
                return
            if len(result) != 0:
                defect("Type4_StateLogicViolation", "(a) 20000 all-missing",
                       f"all 20000 requested ids are absent -> result must be [], got "
                       f"{len(result)} records: {raw[:200]}")
                return
            print("leg (a) OK: 200, 20000 missing ids -> result == [] (no crash, no echo)")
        elif s in (400, 422):
            print(f"leg (a) observed branch: clean {s} limit rejection (resource-class "
                  f"norm — not a defect): {raw[:200]}")
        else:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg (a); no defect conclusion")
            return

        # ---- Leg (b): 5000 mixed ids (2000 found + 3000 missing), exact arithmetic ----
        found_ids = [SEED_BASE + i for i in range(N_SEED)]
        miss_ids = [MISS_BASE_MIX + i for i in range(3000)]
        mixed = found_ids + miss_ids  # concatenation; both spaces disjoint by construction
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": mixed}, timeout=90)
        print(f"leg (b) 5000 mixed (2000 found + 3000 missing) -> status={s}")
        print(f"raw head: {raw[:200]}")
        if s == -1:
            alive, hs, hraw = healthz_alive()
            if alive:
                defect("Type3_RuntimeFailure", "(b) 5000 mixed",
                       f"request did not complete (transport error) while /healthz is "
                       f"alive ({hs}: {hraw}) — hang/DoS signal on the ids-size face")
            else:
                print("VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                defect("Type3_RuntimeFailure", "(b) 5000 mixed",
                       f"5xx ({s}) on a 5k mixed ids request with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        if s in (400, 422):
            print(f"leg (b) observed branch: clean {s} rejection (resource-class norm — "
                  f"not a defect): {raw[:200]}")
            print("VERDICT: NO_DEFECT")
            return
        if s != 200:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg (b); no defect conclusion")
            return
        result = body_resp.get("result") if isinstance(body_resp, dict) else None
        if not isinstance(result, list):
            defect("Type1_IllegalSuccess", "(b) 5000 mixed",
                   f"200 but envelope result is not an array: {raw[:300]}")
            return
        got_ids = [rec.get("id") if isinstance(rec, dict) else None for rec in result]
        if len(got_ids) != N_SEED or set(got_ids) != set(found_ids):
            defect("Type4_StateLogicViolation", "(b) 5000 mixed",
                   f"arithmetic broken at scale: {N_SEED} found of 5000 requested must "
                   f"yield EXACTLY {N_SEED} records with the seeded id set, got "
                   f"{len(got_ids)} records "
                   f"(missing={N_SEED - len(set(found_ids) & set(got_ids))}, "
                   f"extra={len(set(got_ids) - set(found_ids))}): {raw[:200]}")
            return
        if len(got_ids) != len(set(got_ids)):
            defect("Type4_StateLogicViolation", "(b) 5000 mixed",
                   f"duplicate records at scale (one-Record-per-found-id broken): "
                   f"{len(got_ids) - len(set(got_ids))} duplicates: {raw[:200]}")
            return
        print(f"leg (b) OK: 5000 mixed -> exactly {N_SEED} records, id set exact, "
              f"no duplicates")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=120)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
