#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_batch_mixed_variant_004
# strategy: strategy1 behavioral-contract attack (mixed-variant per-entry
#           dispatch — heterogeneous query variants inside ONE batch must
#           each execute their own variant)
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift / semantic dispatch — the endpoint is
#            documented as "Execute multiple universal queries in one call";
#            a wrapper that dispatches every entry to one variant's executor
#            would still return 200 with plausible-looking per-entry results)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy1 mixed-variant dispatch x
  qdrant_behavioral_points_query_batch_001 — the endpoint is documented as
  "Execute multiple universal queries in one call" where each searches[]
  element is a full QueryRequest whose query is oneOf {nearest, recommend,
  discover, context, order_by, fusion, sample, ...} (Query oneOf, vendored
  OpenAPI). This is the planned-but-unwritten mixed_008 leg of the boundary
  lane, taken with a SEMANTIC oracle: the batch mixes three DIFFERENT
  variants whose expected id lists are pairwise disjoint fingerprints, so
  any cross-entry dispatch corruption (all entries executed as entry 0's
  variant, entries swapped, one variant's executor reused) is caught by id
  comparison alone — no invented score oracles, ids only (R39):
    seeds: id 871 = [1,0,0,0], id 872 = [0,1,0,0], ids 873..878 far along
    the all-ones direction ([5..10,5,5,5]); payload ts = id-871 unique
    0..7; integer payload index on ts (order_by robustness).
    e0 nearest anchor A=[1,0,0,0] limit 3 exact -> EXACTLY [871,872,873]
       (d=0 < sqrt(2) < sqrt(91) < sqrt(100) — unique ranking)
    e1 order_by ts direction=desc limit 3     -> EXACTLY [878,877,876]
       (ts desc; OrderByDirection enum asc|desc, documented)
    e2 nearest anchor B=[0,1,0,0] limit 3 exact -> EXACTLY [872,871,873]
    fingerprints are pairwise distinct, and e0/e2 differ in their FIRST TWO
    positions, so even a two-entry swap between the nearest legs is caught.
  [chunk_points+query+batch semantic coverage (7 scripts): search_correctness
  per-entry limit + k-nearest prefix + mixed invalid-entry atomicity +
  empty-searches N-in/N-out x behavioral_points_query_batch_001
  (perelem_limit_001); metamorphic per-entry offset window x
  behavioral_points_query_batch_001 (perelem_offset_002); filter_semantics
  per-entry exact-set closure + bleed isolation x
  behavioral_points_query_batch_001 (perelem_filter_003); behavioral_contract
  mixed-variant per-entry dispatch x behavioral_points_query_batch_001
  (this); type_coercion R33-family dual-key query oneOf cross-face x
  behavioral_points_query_batch_001 (dualkey_005); metamorphic single vs
  batch-of-1 + VectorInput shorthand x behavioral_points_query_batch_001
  (single_vs_batch_006); diagnosis_quality 404 + validation message rubric x
  behavioral_points_query_batch_001 (404_diag_007)]
Oracle: the 3-entry mixed-variant batch -> HTTP 200 with outer len EXACTLY 3
  and result[0].points ids EXACTLY [871,872,873], result[1].points ids
  EXACTLY [878,877,876] (desc ts order), result[2].points ids EXACTLY
  [872,871,873]; ANY deviation (variant dispatched to the wrong entry's
  executor, entry swap, wrong order_by direction, wrong ranking) =
  Type4_StateLogicViolation; 4xx = Type1_IllegalRejection (nearest and
  order_by are documented oneOf members on a documented wrapper); 5xx with
  /healthz alive = Type3_RuntimeFailure; transport failure -> /healthz
  liveness re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_query_batch_001).
Constraint: qdrant_behavioral_points_query_batch_001 (bare id) — "executes
  multiple queries in one call; returns 200 with a list of per-query results;
  404 for a missing collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+batch  -> POST /collections/{collection_name}/points/query/batch
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  field index create  -> PUT  /collections/{collection_name}/index
  healthz             -> GET  /healthz
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
ANCHOR_A = [1.0, 0.0, 0.0, 0.0]   # self-match id 871 (d=0); next 872 (sqrt 2); far pts >= sqrt(91)
ANCHOR_B = [0.0, 1.0, 0.0, 0.0]   # self-match id 872; next 871 (sqrt 2); far pts >= sqrt(91)

SEED = [{"id": 871, "vector": [1.0, 0.0, 0.0, 0.0], "payload": {"ts": 0}},
        {"id": 872, "vector": [0.0, 1.0, 0.0, 0.0], "payload": {"ts": 1}}]
for i in range(873, 879):         # far cluster: distances from both anchors >= sqrt(91)
    SEED.append({"id": i, "vector": [float(5 + (i - 873)), 5.0, 5.0, 5.0],
                 "payload": {"ts": i - 871}})

EXPECTED = {
    0: [871, 872, 873],           # nearest A, limit 3, exact
    1: [878, 877, 876],           # order_by ts desc, limit 3
    2: [872, 871, 873],           # nearest B, limit 3, exact
}


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
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def bail_transport(where):
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")


def handle_5xx(rs, rraw, leg):
    if not (500 <= rs <= 599):
        return False
    alive, _, _ = healthz_alive()
    if alive:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{leg}]: {rs} "
              f"with service alive: {rraw[:300]}")
    else:
        print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
    return True


def batch_entries(body):
    """
    Extract outer result list and per-entry point lists.
    Contract response_shape: result[] is an object with result[].points array;
    a bare-array entry is tolerated as an alias form (recorded, not adjudicated).
    """
    if not isinstance(body, dict):
        return None, None
    outer = body.get("result")
    if not isinstance(outer, list):
        return None, None
    entries = []
    for i, e in enumerate(outer):
        if isinstance(e, dict) and isinstance(e.get("points"), list):
            entries.append(e["points"])
        elif isinstance(e, list):
            print(f"NOTE entry[{i}]: bare-array envelope form observed "
                  f"(published schema declares result[].points object form) — "
                  f"recorded, not adjudicated")
            entries.append(e)
        else:
            return None, None
    return outer, entries


def ids_of(points):
    return [p.get("id") for p in points if isinstance(p, dict)]


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqbV4" + tag

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": SEED}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        # integer payload index on ts — documented order_by robustness measure
        s, _, raw = safe_request("PUT", f"/collections/{coll}/index",
                                 json={"field_name": "ts", "field_schema": "integer"},
                                 params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"NOTE setup: ts index create returned {s} (order_by proceeds "
                  f"without index): {raw[:200]}")

        bpath = f"/collections/{coll}/points/query/batch"
        searches = [
            {"query": {"nearest": ANCHOR_A}, "params": {"exact": True}, "limit": 3},
            {"query": {"order_by": {"key": "ts", "direction": "desc"}}, "limit": 3},
            {"query": {"nearest": ANCHOR_B}, "params": {"exact": True}, "limit": 3},
        ]
        s, body, raw = safe_request("POST", bpath, json={"searches": searches}, timeout=60)
        print(f"mixed-variant batch [nearest A, order_by desc, nearest B] -> status={s}")
        print(f"raw: {raw[:600]}")
        if s == -1:
            bail_transport("mixed-variant batch")
            return
        if handle_5xx(s, raw, "mixed-variant batch"):
            return
        if 400 <= s <= 499:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — nearest and "
                  f"order_by are documented oneOf members executed via the "
                  f"documented batch wrapper, rejected with {s}: {raw[:250]}")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: SCRIPT_ERROR — batch unexpected status {s}; no defect conclusion")
            return
        outer, entries = batch_entries(body)
        if outer is None or len(entries) != 3:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 3 "
                  f"searches must yield exactly 3 results, got "
                  f"{len(entries) if entries is not None else 'malformed'}: {raw[:250]}")
            return
        names = ["e0 nearest A", "e1 order_by ts desc", "e2 nearest B"]
        for idx, name in enumerate(names):
            got = ids_of(entries[idx])
            if got != EXPECTED[idx]:
                others = {j: EXPECTED[j] for j in EXPECTED if j != idx}
                cross = ""
                for j, exp_j in others.items():
                    if got == exp_j:
                        cross = f" — matches entry {j}'s fingerprint {exp_j} (variant mis-dispatched or entries swapped)"
                        break
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"{name}: expected exactly {EXPECTED[idx]}, got {got}"
                      f"{cross}: {raw[:250]}")
                return
        print("e0/e1/e2 OK: each variant dispatched and executed per entry "
              "(fingerprints exact, no cross-entry corruption)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
