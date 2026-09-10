#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_batch_perelem_offset_002
# strategy: strategy6 metamorphic attack (per-entry offset window semantics
#           inside the batch wrapper — window algebra against a live-measured
#           full ranking)
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the batch wrapper is one
#            extra nesting level where per-entry offset can be silently
#            dropped or mis-applied, the R33 field-discard family analog)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy6 per-entry offset window x
  qdrant_behavioral_points_query_batch_001 — each searches[] element is a
  full QueryRequest whose offset is documented as "Offset of the first
  result to return" (minimum 0, vendored OpenAPI QueryRequest.offset), so
  an element with (limit=k, offset=j) must return the live full ranking
  sliced [j:j+k]. Mutation justification (G6): offset is the batch
  wrapper's most breakable per-entry field — silently discarding it
  collapses every window onto the head of the ranking (undetectable on a
  single-entry batch whose offset is 0, glaring in a multi-entry batch
  with heterogeneous windows). 9 points seeded at strictly increasing
  Euclid distances 1..9 from anchor ORIG so the ranking is unique by
  construction (params.exact=true; only ids asserted, never scores — R39):
    G  single-entry batch limit=9 offset=0 -> live ranking baseline
       (expected [801..809] by construction, measured not assumed).
    W  one batch, three windows on the same anchor:
       w0 (limit=3, offset=0) -> G[0:3]; w1 (limit=2, offset=1) -> G[1:3];
       w2 (limit=3, offset=6) -> G[6:9]. Window algebra is exact: offset
       skips j results, limit takes the next k.
    E  edge window beyond the collection: (limit=3, offset=50) -> the only
       count-consistent outcome is 200 with 0 points; returned points with
       offset beyond the total would fabricate ranking positions (Type4);
       4xx recorded as judge-call NOTE (schema pins no maximum offset).
  [chunk_points+query+batch semantic coverage (7 scripts): search_correctness
  per-entry limit + k-nearest prefix + mixed invalid-entry atomicity +
  empty-searches N-in/N-out x behavioral_points_query_batch_001
  (perelem_limit_001); metamorphic per-entry offset window x
  behavioral_points_query_batch_001 (this); filter_semantics per-entry
  exact-set closure + bleed isolation x behavioral_points_query_batch_001
  (perelem_filter_003); behavioral_contract mixed-variant per-entry dispatch
  x behavioral_points_query_batch_001 (mixed_variant_004); type_coercion
  R33-family dual-key query oneOf cross-face x behavioral_points_query_batch_001
  (dualkey_005); metamorphic single vs batch-of-1 + VectorInput shorthand x
  behavioral_points_query_batch_001 (single_vs_batch_006); diagnosis_quality
  404 + validation message rubric x behavioral_points_query_batch_001
  (404_diag_007)]
Oracle: G -> 200 with 9 point ids [801..809] in order (live baseline);
  W -> 200 outer len EXACTLY 3, w0 ids == G[0:3], w1 ids == G[1:3], w2 ids
  == G[6:9] exactly (offset dropped => w1==G[0:2] head collapse or w2 short
  = Type4_StateLogicViolation window semantics broken; wrong count/order on
  any window = Type4); 4xx on W = Type1_IllegalRejection (documented
  limit/offset values wrongly rejected); E -> 200 with 0 points (any point returned
  = Type4; 4xx = NOTE judge-call); 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz liveness re-check then
  SCRIPT_ERROR (constraint qdrant_behavioral_points_query_batch_001).
Constraint: qdrant_behavioral_points_query_batch_001 (bare id) — "executes
  multiple queries in one call; returns 200 with a list of per-query results;
  404 for a missing collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+batch  -> POST /collections/{collection_name}/points/query/batch
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
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
IDS = list(range(801, 810))          # 801..809, distance to anchor == i-800
ORIG = [0.0, 0.0, 0.0, 0.0]
SEED = [{"id": i, "vector": [float(i - 800), 0.0, 0.0, 0.0]} for i in IDS]


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
    coll = "spqbO2" + tag

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

        bpath = f"/collections/{coll}/points/query/batch"

        def window(limit, offset):
            return {"query": {"nearest": ORIG}, "params": {"exact": True},
                    "limit": limit, "offset": offset}

        # ---- G: full ranking baseline (limit 9, offset 0) ----
        s, body, raw = safe_request("POST", bpath, json={"searches": [window(9, 0)]}, timeout=60)
        print(f"G limit=9 offset=0 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            bail_transport("G")
            return
        if handle_5xx(s, raw, "G"):
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: SCRIPT_ERROR — G unexpected status {s}; no defect conclusion")
            return
        outer, entries = batch_entries(body)
        if outer is None or len(entries) != 1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — G: outer "
                  f"envelope not a 1-entry result list: {raw[:250]}")
            return
        g_ids = ids_of(entries[0])
        if g_ids != IDS:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — G: unique-"
                  f"distance ranking must be {IDS}, got {g_ids}: {raw[:250]}")
            return
        print(f"G OK: live baseline ranking {g_ids}")

        # ---- W: three windows in one batch ----
        s, body, raw = safe_request("POST", bpath,
                                    json={"searches": [window(3, 0), window(2, 1),
                                                       window(3, 6)]}, timeout=60)
        print(f"W windows [(3,0),(2,1),(3,6)] -> status={s}")
        print(f"raw: {raw[:500]}")
        if s == -1:
            bail_transport("W")
            return
        if handle_5xx(s, raw, "W"):
            return
        if 400 <= s <= 499:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — W: documented "
                  f"per-entry limit/offset values rejected with {s}: {raw[:250]}")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: SCRIPT_ERROR — W unexpected status {s}; no defect conclusion")
            return
        outer, entries = batch_entries(body)
        if outer is None or len(entries) != 3:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — W: 3 "
                  f"searches must yield exactly 3 results, got "
                  f"{len(entries) if entries is not None else 'malformed'}: {raw[:250]}")
            return
        expected_windows = [g_ids[0:3], g_ids[1:3], g_ids[6:9]]
        for idx, (lim, off, exp) in enumerate(zip((3, 2, 3), (0, 1, 6), expected_windows)):
            got = ids_of(entries[idx])
            if got != exp:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — W: "
                      f"entry[{idx}] (limit={lim}, offset={off}) must return "
                      f"ranking window {exp}, got {got} (offset dropped/mis-"
                      f"applied by the batch wrapper): {raw[:250]}")
                return
        print("W OK: all three windows are exact slices of the live ranking")

        # ---- E: window beyond the collection total ----
        s, body, raw = safe_request("POST", bpath, json={"searches": [window(3, 50)]}, timeout=60)
        print(f"E (limit=3, offset=50) -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1:
            bail_transport("E")
            return
        if handle_5xx(s, raw, "E"):
            return
        if 200 <= s <= 299:
            outer, entries = batch_entries(body)
            got = ids_of(entries[0]) if (entries is not None and len(entries) == 1) else None
            if got:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — E: "
                      f"offset=50 is beyond all 9 points, no point can occupy a "
                      f"window position, yet returned {got}: {raw[:250]}")
                return
            print("E OK: window beyond total -> 0 points (count-consistent)")
        elif 400 <= s <= 499:
            print("NOTE E: offset=50 rejected with 4xx although the schema pins "
                  "no maximum offset — judge call, disposition recorded")
        else:
            print(f"VERDICT: SCRIPT_ERROR — E unexpected status {s}; no defect conclusion")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
