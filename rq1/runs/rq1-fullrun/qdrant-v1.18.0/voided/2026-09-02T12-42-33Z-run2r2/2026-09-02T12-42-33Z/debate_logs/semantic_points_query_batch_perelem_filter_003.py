#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_batch_perelem_filter_003
# strategy: strategy7 filter-semantics attack (per-entry exact-set closure +
#           cross-entry bleed isolation inside the batch wrapper)
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (filter semantics on the critical query surface — the TMA
#            names filter semantics as this face's semantic blindspot; the
#            batch wrapper adds the risk that a per-entry filter is dropped
#            or bleeds across entries)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy7 per-entry filter exact-set closure x
  qdrant_behavioral_points_query_batch_001 — each searches[] element is a
  full QueryRequest carrying its own Filter ({must?, should?, must_not?,
  min_should?} per the contract Filter data type); "executes multiple
  queries in one call" means element i's filter governs element i's result
  ONLY. 12 points: 8 berlin (ids 851..858), 4 paris (ids 859..862), scalar
  payload city so no point can match both values (pure set arithmetic, the
  R33 id-collision discipline); vectors share the anchor direction so the
  full ranking is id order by construction (params.exact=true; only ids and
  readback payloads asserted, never scores — R39):
    F0 entry with NO filter      -> exactly all 12 ids, id order
    F1 entry filter must berlin  -> EXACTLY {851..858}, every readback
                                    payload city==berlin
    F2 entry filter must paris   -> EXACTLY {859..862}, every readback
                                    payload city==paris
  All three entries travel in ONE batch on the SAME anchor, so:
    - filter dropped   => F1 or F2 returns the unfiltered 12 (Type4)
    - filter bleed     => a paris id inside F1 or berlin id inside F2 (Type4)
    - entry corruption => wrong outer length / reordered envelope (Type4)
  Differentiation from boundary_points_query_batch_positive_001 B1 (which
  asserted only membership subsets len<=3 for attribution): this script
  asserts EXACT-set closure at limit 12 plus payload-readback consistency
  plus cross-entry bleed isolation — set-level semantics, not attribution.
  [chunk_points+query+batch semantic coverage (7 scripts): search_correctness
  per-entry limit + k-nearest prefix + mixed invalid-entry atomicity +
  empty-searches N-in/N-out x behavioral_points_query_batch_001
  (perelem_limit_001); metamorphic per-entry offset window x
  behavioral_points_query_batch_001 (perelem_offset_002); filter_semantics
  per-entry exact-set closure + bleed isolation x
  behavioral_points_query_batch_001 (this); behavioral_contract mixed-variant
  per-entry dispatch x behavioral_points_query_batch_001 (mixed_variant_004);
  type_coercion R33-family dual-key query oneOf cross-face x
  behavioral_points_query_batch_001 (dualkey_005); metamorphic single vs
  batch-of-1 + VectorInput shorthand x behavioral_points_query_batch_001
  (single_vs_batch_006); diagnosis_quality 404 + validation message rubric x
  behavioral_points_query_batch_001 (404_diag_007)]
Oracle: one batch of 3 entries -> HTTP 200 with outer len EXACTLY 3 and
  per-entry point lists where F0 ids == [851..862] (12, id order), F1 ids ==
  [851..858] EXACTLY with every readback payload city==berlin, F2 ids ==
  [859..862] EXACTLY with every readback payload city==paris; any filter
  drop (F1/F2 == the unfiltered 12), bleed (wrong-city id in F1/F2), count
  or set mismatch = Type4_StateLogicViolation; 4xx on the batch =
  Type1_IllegalRejection (documented Filter on a documented wrapper
  wrongly rejected); 5xx with /healthz alive = Type3_RuntimeFailure;
  transport failure -> /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_query_batch_001).
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
BERLIN_IDS = list(range(851, 859))   # 8
PARIS_IDS = list(range(859, 863))    # 4
ALL_IDS = BERLIN_IDS + PARIS_IDS
ANCHOR = [0.0, 1.0, 0.25, 0.5]       # distance to id 851+i == i (id order == ranking)
SEED = [{"id": i,
         "vector": [float(i - 851), 1.0, 0.25, 0.5],
         "payload": {"city": "berlin" if i in BERLIN_IDS else "paris"}}
        for i in ALL_IDS]

COND_BERLIN = {"key": "city", "match": {"value": "berlin"}}
COND_PARIS = {"key": "city", "match": {"value": "paris"}}


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
    coll = "spqbF3" + tag

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

        def entry(flt):
            e = {"query": {"nearest": ANCHOR}, "params": {"exact": True},
                 "limit": 12, "with_payload": True}
            if flt is not None:
                e["filter"] = flt
            return e

        searches = [entry(None),
                    entry({"must": [COND_BERLIN]}),
                    entry({"must": [COND_PARIS]})]
        s, body, raw = safe_request("POST", bpath, json={"searches": searches}, timeout=60)
        print(f"batch [nofilter, must berlin, must paris] -> status={s}")
        print(f"raw: {raw[:600]}")
        if s == -1:
            bail_transport("batch")
            return
        if handle_5xx(s, raw, "batch"):
            return
        if 400 <= s <= 499:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — documented "
                  f"per-entry Filter values rejected with {s}: {raw[:250]}")
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

        # ---- F0: no filter -> all 12 in id order ----
        f0 = ids_of(entries[0])
        if f0 != ALL_IDS:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F0: "
                  f"unfiltered entry must return all 12 ids in ranking order "
                  f"{ALL_IDS}, got {f0}: {raw[:250]}")
            return

        # ---- F1: must berlin -> exactly the 8 berlin ids, payload-consistent ----
        f1 = ids_of(entries[1])
        if sorted(f1) != BERLIN_IDS:
            if sorted(f1) == sorted(ALL_IDS):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F1: "
                      f"per-entry filter DROPPED — returned the unfiltered full "
                      f"set {sorted(f1)} instead of exactly {BERLIN_IDS}: "
                      f"{raw[:250]}")
            else:
                paris_leak = sorted(set(f1) & set(PARIS_IDS))
                extra = (f"paris bleed ids {paris_leak}" if paris_leak
                         else "wrong set")
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F1: "
                      f"must city=berlin must return exactly {BERLIN_IDS}, got "
                      f"{sorted(f1)} ({extra}): {raw[:250]}")
            return
        for p in entries[1]:
            if p.get("payload", {}).get("city") != "berlin":
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F1: "
                      f"readback payload contradicts the filter: "
                      f"{json.dumps(p)[:150]}")
                return

        # ---- F2: must paris -> exactly the 4 paris ids, payload-consistent ----
        f2 = ids_of(entries[2])
        if sorted(f2) != PARIS_IDS:
            if sorted(f2) == sorted(ALL_IDS):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F2: "
                      f"per-entry filter DROPPED — returned the unfiltered full "
                      f"set {sorted(f2)} instead of exactly {PARIS_IDS}: "
                      f"{raw[:250]}")
            else:
                berlin_leak = sorted(set(f2) & set(BERLIN_IDS))
                extra = (f"berlin bleed ids {berlin_leak}" if berlin_leak
                         else "wrong set")
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F2: "
                      f"must city=paris must return exactly {PARIS_IDS}, got "
                      f"{sorted(f2)} ({extra}): {raw[:250]}")
            return
        for p in entries[2]:
            if p.get("payload", {}).get("city") != "paris":
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F2: "
                      f"readback payload contradicts the filter: "
                      f"{json.dumps(p)[:150]}")
                return

        print("F0/F1/F2 OK: exact-set closure per entry, zero cross-entry "
              "bleed, payloads consistent")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
