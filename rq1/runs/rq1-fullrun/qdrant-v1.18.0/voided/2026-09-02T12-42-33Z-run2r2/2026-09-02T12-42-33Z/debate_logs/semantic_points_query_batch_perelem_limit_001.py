#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_batch_perelem_limit_001
# strategy: strategy5 search-correctness attack (per-entry limit semantics +
#           k-nearest prefix nesting inside the batch wrapper) with a
#           mixed invalid-entry atomicity leg and the empty-searches
#           N-in/N-out closure
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the batch wrapper adds a
#            nesting level where per-entry fields can be silently dropped,
#            the R33 serde family analog on a read face)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy5 per-entry limit semantics x
  qdrant_behavioral_points_query_batch_001 — the assertion promises "HTTP 200
  with one result per search in the same order"; each searches[] element is a
  full QueryRequest whose limit is documented as "Max number of points to
  return" with minimum 1 (QueryRequest schema, verbatim from the vendored
  OpenAPI). 9 points seeded at strictly increasing Euclid distances 1..9 from
  anchor ORIG so the k-nearest set for every k is unique by construction (no
  tie-breaking, no invented score oracle — R39: only ids are asserted and the
  full ranking is measured live as the baseline, never assumed):
    G  guard single-entry batch limit=9 -> establishes the true ranking
       [801..809] (distance order == id order by construction).
    L  limits [1,2,4] in ONE batch (same anchor, params.exact=true) ->
       outer len 3; per-entry counts EXACTLY [1,2,4]; entry ids == the
       live-measured G ranking truncated to that k (k-nearest prefix
       nesting); top-1 == 801 everywhere. A wrapper that drops per-entry
       limit (R33-family field discard) collapses all counts to one value.
    M  mixed atomicity: searches=[{nearest,limit:2},{nearest,limit:0}] ->
       limit=0 violates the schema minimum 1, so the whole batch must be
       rejected (whole-batch rejection is the proven family disposition on
       the sibling discover+batch face, R37 — verify, don't assume);
       200 with outer len 2 = the schema-illegal entry executed (Type1);
       200 with outer len 1 = silent skip breaking one-result-per-search
       (Type4).
    K0 empty searches [] (no minItems in the QueryRequestBatch schema, so
       the body is spec-legal) -> N-in/N-out: 200 with outer len 0 is the
       only count-consistent outcome; 200 with a non-empty result array
       violates one-result-per-search (Type4); 4xx recorded as judge-call
       NOTE.
  [chunk_points+query+batch semantic coverage (7 scripts): search_correctness
  per-entry limit + k-nearest prefix + mixed invalid-entry atomicity +
  empty-searches N-in/N-out x behavioral_points_query_batch_001 (this);
  metamorphic per-entry offset window x behavioral_points_query_batch_001
  (perelem_offset_002); filter_semantics per-entry exact-set closure + bleed
  isolation x behavioral_points_query_batch_001 (perelem_filter_003);
  behavioral_contract mixed-variant per-entry dispatch x
  behavioral_points_query_batch_001 (mixed_variant_004); type_coercion
  R33-family dual-key query oneOf cross-face x behavioral_points_query_batch_001
  (dualkey_005); metamorphic single vs batch-of-1 + VectorInput shorthand x
  behavioral_points_query_batch_001 (single_vs_batch_006); diagnosis_quality
  404 + validation message rubric x behavioral_points_query_batch_001
  (404_diag_007)]
Oracle: G -> 200 with entry of exactly 9 points ids [801..809] in that order
  (the live baseline); L -> 200 outer len EXACTLY 3, per-entry point counts
  EXACTLY [1,2,4], each entry's ids == G-ids[:k] (any count collapse, prefix
  break, or top-1 != 801 = Type4_StateLogicViolation; 4xx on L = Type1_IllegalRejection);
  M -> 400/422
  whole-batch rejection (200 outer 2 = Type1_IllegalSuccess; 200 outer 1 =
  Type4 silent skip; other outer len = Type4); K0 -> 200 with outer len 0
  (non-zero = Type4; 4xx = NOTE judge-call); 5xx with /healthz alive =
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
IDS = list(range(801, 810))          # 801..809
ORIG = [0.0, 0.0, 0.0, 0.0]          # anchor: distance to id 801+i == i+1 (strictly increasing)
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
    Contract response_shape: result[] is an object with result[].points array.
    A bare-array entry is tolerated as an alias form (recorded, never a
    defect criterion by itself — R39 envelope-form latitude).
    Returns (outer_list, [points_list_per_entry]) or (None, None).
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
    coll = "spqbL1" + tag

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

        def nearest_entry(limit, offset=None):
            e = {"query": {"nearest": ORIG}, "params": {"exact": True}, "limit": limit}
            if offset is not None:
                e["offset"] = offset
            return e

        # ---- G: guard single-entry batch, limit 9 -> live ranking baseline ----
        s, body, raw = safe_request("POST", bpath, json={"searches": [nearest_entry(9)]}, timeout=60)
        print(f"G limit=9 -> status={s}")
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

        # ---- L: per-entry limits [1,2,4] in one batch ----
        s, body, raw = safe_request("POST", bpath,
                                    json={"searches": [nearest_entry(1), nearest_entry(2),
                                                       nearest_entry(4)]}, timeout=60)
        print(f"L limits=[1,2,4] -> status={s}")
        print(f"raw: {raw[:500]}")
        if s == -1:
            bail_transport("L")
            return
        if handle_5xx(s, raw, "L"):
            return
        if 400 <= s <= 499:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — L: documented "
                  f"per-entry limit values rejected with {s}: {raw[:250]}")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: SCRIPT_ERROR — L unexpected status {s}; no defect conclusion")
            return
        outer, entries = batch_entries(body)
        if outer is None or len(entries) != 3:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L: 3 "
                  f"searches must yield exactly 3 results, got "
                  f"{len(entries) if entries is not None else 'malformed'}: {raw[:250]}")
            return
        for idx, k in enumerate((1, 2, 4)):
            got = ids_of(entries[idx])
            if len(got) != k:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L: "
                      f"entry[{idx}] limit={k} must return exactly {k} points, "
                      f"got {len(got)} (per-entry limit not honored): {raw[:250]}")
                return
            if got != g_ids[:k]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L: "
                      f"entry[{idx}] limit={k} must be the k-nearest prefix "
                      f"{g_ids[:k]}, got {got}: {raw[:250]}")
                return
        print("L OK: per-entry counts [1,2,4], each a k-nearest prefix of the baseline")

        # ---- M: mixed atomicity [valid limit=2, schema-illegal limit=0] ----
        s, body, raw = safe_request("POST", bpath,
                                    json={"searches": [nearest_entry(2),
                                                       {"query": {"nearest": ORIG},
                                                        "params": {"exact": True}, "limit": 0}]},
                                    timeout=60)
        print(f"M mixed [limit=2, limit=0] -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            bail_transport("M")
            return
        if handle_5xx(s, raw, "M"):
            return
        if 400 <= s <= 499:
            print("M OK: whole-batch rejection of the schema-illegal entry "
                  "(limit minimum is 1) — matches the sibling-face disposition")
        elif 200 <= s <= 299:
            outer, entries = batch_entries(body)
            n = len(entries) if entries is not None else None
            if n == 2:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — M: entry "
                      f"limit=0 (schema minimum 1) executed, batch returned 2 "
                      f"results: {raw[:250]}")
                return
            if n == 1:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M: "
                      f"silent skip — one result per search broken (outer len 1 "
                      f"for 2 searches): {raw[:250]}")
                return
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M: 200 "
                  f"with outer len {n} for 2 searches: {raw[:250]}")
            return
        else:
            print(f"VERDICT: SCRIPT_ERROR — M unexpected status {s}; no defect conclusion")
            return

        # ---- K0: empty searches (spec-legal, no minItems) ----
        s, body, raw = safe_request("POST", bpath, json={"searches": []}, timeout=60)
        print(f"K0 empty searches -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1:
            bail_transport("K0")
            return
        if handle_5xx(s, raw, "K0"):
            return
        if 200 <= s <= 299:
            outer, entries = batch_entries(body)
            n = len(entries) if entries is not None else None
            if n == 0:
                print("K0 OK: 0 searches -> 0 results (N-in/N-out closure)")
            elif n is None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — K0: "
                      f"malformed result envelope: {raw[:250]}")
                return
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — K0: "
                      f"0 searches yielded {n} results — one-result-per-search "
                      f"violated: {raw[:250]}")
                return
        elif 400 <= s <= 499:
            print("NOTE K0: empty searches rejected with 4xx although the "
                  "QueryRequestBatch schema declares no minItems — judge call, "
                  "disposition recorded")
        else:
            print(f"VERDICT: SCRIPT_ERROR — K0 unexpected status {s}; no defect conclusion")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
