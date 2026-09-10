#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_nested_filter_001
# strategy: strategy7 filter-semantics attack (nested condition) +
#           strategy2 diagnosis-quality on the no-index / required-path faces
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 — the TMA names "nested filter validation" as the second
#            semantic attack on this critical endpoint
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy7 nested-filter semantics x points+query —
  the TMA semantic attack order for this endpoint lists nested filter
  validation. The contract data type fixes the nested condition as
  {key, filter} (BOTH required per the published Nested schema), key
  pointing at an array of objects, filter applied PER ARRAY ELEMENT, a
  parent point matching when at least one element matches; has_id/slice
  are NOT supported inside nested — they belong in an adjacent must
  clause. 4 points with array-of-objects payload (id-collision analysis
  per R33 — every expectation is set arithmetic):
    701 data=[{diet:[meat]},{diet=[plant]}] -> matches diet=plant
    702 data=[{diet:[meat]}]                -> no
    703 data=[{diet:[plant]}]               -> yes
    704 data=[]                             -> no (empty array)
  Legs (same exact nearest query every time):
    G1a nested filter BEFORE any payload index
         -> EITHER 4xx with an actionable message (index-required policy —
            rubric-scored) OR 200 with exactly {701, 703} (index-free
            evaluation): both clean; 200 with any other set = Type4
    G1b after creating the nested payload index (PUT index, field_schema
         {"type":"nested"} — spec-side note: PayloadSchemaParams in the
         published v1.18.x OpenAPI does not list a nested variant, so the
         index-create disposition itself is recorded; if creation is
         rejected, G1b degrades to SKIPPED-note and G1a carries the round)
         -> MUST return exactly {701, 703} (hard oracle)
    G2 adjacent-clause composition (documented placement for has_id):
         must=[has_id [701,702,703,704], nested(diet=plant)] -> {701,703}
         intersect {701,702} -> exactly {701}
    G3 nested with MISSING key (required-path violation) -> 4xx;
         2xx = Type1_IllegalSuccess
    G4 (NOTE) has_id INSIDE nested — documented NOT supported -> expect
         4xx; 200 recorded as NOTE only (doc-consistency signal, G3-avoid)
  [chunk_points+query semantic coverage — see variant_domain_001 for the
  full 10-script coverage list; this script = filter_semantics nested x
  TMA-order#2, anchored on qdrant_behavioral_points_query_001 whose
  result-set semantics the filter decides]
Oracle: G1a -> 4xx with usable message OR 200 with ids exactly {701,703};
  G1b (if index created) -> 200 with ids exactly {701,703}; G2 -> exactly
  {701}; G3 -> 400-family 4xx; wrong sets on G1/G2 =
  Type4_StateLogicViolation; 2xx on G3 = Type1_IllegalSuccess; 5xx with
  /healthz alive = Type3_RuntimeFailure; unusable rejection body on G1a =
  Type2_PoorDiagnostics (R29-calibrated); transport failure -> /healthz
  re-check then SCRIPT_ERROR (constraint qdrant_behavioral_points_query_001).
Constraint: qdrant_behavioral_points_query_001 (bare id) + nested condition
  data type — "key points to an array of objects; filter applies per array
  element; the parent point matches if at least one element matches;
  has_id and slice are NOT supported inside nested" (evidence_tier:
  explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query        -> POST /collections/{collection_name}/points/query
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  index+create        -> PUT  /collections/{collection_name}/index
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
SEED = [
    {"id": 701, "vector": [1.0, 0.0, 0.0, 0.0],
     "payload": {"data": [{"diet": ["meat"]}, {"diet": ["plant"]}]}},
    {"id": 702, "vector": [0.0, 1.0, 0.0, 0.0],
     "payload": {"data": [{"diet": ["meat"]}]}},
    {"id": 703, "vector": [0.0, 0.0, 1.0, 0.0],
     "payload": {"data": [{"diet": ["plant"]}]}},
    {"id": 704, "vector": [0.0, 0.0, 0.0, 1.0],
     "payload": {"data": []}},
]
EXPECTED_PLANT = {701, 703}

FORMAT_HINTS = ["must be", "expected", "should be", "valid", "range", "type",
                "minimum", "maximum", "unknown", "invalid", "parse",
                "deserialize", "validation", "not found", "exist", "index"]
ACTION_HINTS = ["correct", "try", "use ", "change", "specify", "provide",
                "instead", "create", "index"]


def score_error_quality(raw, keywords):
    """Type-2 rubric, R29-calibrated (naming informational, not an anchor)."""
    msg = json.dumps(raw).lower() if isinstance(raw, dict) else str(raw or "").lower()
    if not msg.strip():
        return -1, ""
    score = 0
    if any(k.lower() in msg for k in keywords):
        score += 1
    if any(h in msg for h in FORMAT_HINTS):
        score += 1
    if any(h in msg for h in ACTION_HINTS):
        score += 1
    return score, msg


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


def transport_dead(where):
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


def get_points(body):
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, dict) and isinstance(r.get("points"), list):
            return r["points"]
    return None


def nested_filter(conditions_key="data"):
    diet_plant = {"key": "diet", "match": {"any": ["plant"]}}
    inner = {"must": [diet_plant]}
    nested = {"key": conditions_key, "filter": inner}
    return {"must": [{"nested": nested}]}


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqN1" + tag

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

        qpath = f"/collections/{coll}/points/query"

        def query_with_filter(leg, flt):
            s, body, raw = safe_request("POST", qpath,
                                        json={"query": {"nearest": [0.0, 0.0, 0.0, 1.0]},
                                              "params": {"exact": True},
                                              "filter": flt, "limit": 4}, timeout=60)
            print(f"{leg} -> status={s}")
            print(f"raw: {raw[:350]}")
            if s == -1:
                transport_dead(leg)
                return None
            if handle_5xx(s, raw, leg):
                return None
            return s, get_points(body), raw

        # ---- G1a: nested filter WITHOUT payload index ----
        res = query_with_filter("G1a nested (no index yet)", nested_filter())
        if res is None:
            return
        s, pts, raw = res
        index_needed = False
        if 200 <= s <= 299:
            ids = set(p.get("id") for p in pts) if pts is not None else set()
            if ids != EXPECTED_PLANT:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — G1a: "
                      f"nested diet=plant must match exactly {sorted(EXPECTED_PLANT)} "
                      f"(701 via its plant element, 703, NOT 702 meat-only, NOT 704 "
                      f"empty array), got {sorted(ids)}: {raw[:250]}")
                return
            print("G1a OK: nested filter evaluated correctly without an index")
        elif 400 <= s <= 499:
            index_needed = True
            score, _ = score_error_quality(raw, ["nested", "index", "payload"])
            print(f"G1a: rejected with {s} (index-required policy); rubric "
                  f"score={score}/3")
            if score < 0:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — G1a: "
                      f"rejection carries no usable diagnostic content: "
                      f"{raw[:200]}")
                return
        else:
            print(f"VERDICT: SCRIPT_ERROR — G1a unexpected status {s}; no defect "
                  f"conclusion")
            return

        # ---- create the nested payload index (disposition recorded) ----
        idx_ok = False
        s_idx, _, raw_idx = safe_request("PUT", f"/collections/{coll}/index",
                                         json={"field_name": "data",
                                               "field_schema": {"type": "nested"}},
                                         params={"wait": "true"}, timeout=60)
        print(f"index create (nested) -> status={s_idx}")
        print(f"raw: {raw_idx[:300]}")
        if s_idx in (200, 201):
            idx_ok = True
            print("index create OK — note: the published v1.18.x OpenAPI "
                  "PayloadSchemaParams oneOf does not list 'nested'; acceptance "
                  "recorded as a spec-coverage observation")
        elif 400 <= s_idx <= 499:
            print(f"NOTE index create rejected with {s_idx} — matches the "
                  f"boundary-lane finding that 'nested' is a plausible "
                  f"non-member of the documented field_schema enum; recorded")
        else:
            if handle_5xx(s_idx, raw_idx, "index create"):
                return

        # ---- G1b: nested filter WITH index (hard oracle) ----
        if idx_ok:
            res = query_with_filter("G1b nested (index created)", nested_filter())
            if res is None:
                return
            s, pts, raw = res
            if 200 <= s <= 299:
                ids = set(p.get("id") for p in pts) if pts is not None else set()
                if ids != EXPECTED_PLANT:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"G1b: with the nested index in place the filter must "
                          f"return exactly {sorted(EXPECTED_PLANT)}, got "
                          f"{sorted(ids)}: {raw[:250]}")
                    return
                print("G1b OK: exact nested semantics with index")
            elif 400 <= s <= 499 and index_needed:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — G1b: "
                      f"the nested index was created successfully yet the same "
                      f"filter is still rejected with {s}: {raw[:250]}")
                return
            else:
                print(f"VERDICT: SCRIPT_ERROR — G1b unexpected status {s}; no "
                      f"defect conclusion")
                return
        else:
            print("SKIPPED-note G1b: nested index creation was rejected, so the "
                  "with-index face cannot run; G1a's disposition carries this "
                  "constraint (no false conclusion drawn)")

        # ---- G2: adjacent-clause composition with has_id (documented) ----
        flt = {"must": [{"has_id": [701, 702]}, nested_filter()["must"][0]]}
        res = query_with_filter("G2 adjacent has_id + nested", flt)
        if res is None:
            return
        s, pts, raw = res
        if 200 <= s <= 299:
            ids = set(p.get("id") for p in pts) if pts is not None else set()
            if ids != {701}:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — G2: "
                      f"has_id[701,702] AND nested(diet=plant) must intersect to "
                      f"{{701}}, got {sorted(ids)}: {raw[:250]}")
                return
            print("G2 OK: adjacent-clause composition intersects correctly")
        elif 400 <= s <= 499:
            if index_needed and not idx_ok:
                print("NOTE G2: rejected 4xx — same index-required policy as G1a; "
                      "recorded")
            else:
                print(f"NOTE G2: rejected with {s} despite documented placement "
                      f"guidance for has_id (adjacent must clause) — recorded for "
                      f"the judge")
        else:
            print(f"VERDICT: SCRIPT_ERROR — G2 unexpected status {s}; no defect "
                  f"conclusion")
            return

        # ---- G3: nested missing required key -> 4xx ----
        # built programmatically to avoid deep-literal brace miscounts
        inner_filter = {"must": [{"key": "diet", "match": {"any": ["plant"]}}]}
        keyless_nested_flt = {"must": [{"nested": {"filter": inner_filter}}]}
        res = query_with_filter("G3 nested missing key", keyless_nested_flt)
        if res is None:
            return
        s, pts, raw = res
        if 200 <= s <= 299:
            ids = set(p.get("id") for p in pts) if pts is not None else set()
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — G3: the "
                  f"published Nested schema marks BOTH key and filter required; "
                  f"a keyless nested condition was accepted with {s} returning "
                  f"{sorted(ids)}: {raw[:250]}")
            return
        if not (400 <= s <= 499):
            print(f"VERDICT: SCRIPT_ERROR — G3 unexpected status {s}; no defect "
                  f"conclusion")
            return
        print("G3 OK: keyless nested condition rejected by 4xx")

        # ---- G4 (NOTE): has_id INSIDE nested — documented NOT supported ----
        hasid_inside_flt = {"must": [{"nested": {"key": "data",
                                                 "filter": {"must": [{"has_id": [701]}]}}}]}
        res = query_with_filter("G4 has_id inside nested", hasid_inside_flt)
        if res is None:
            return
        s, pts, raw = res
        if 200 <= s <= 299:
            ids = sorted(set(p.get("id") for p in pts)) if pts is not None else []
            print(f"NOTE G4: has_id inside nested was ACCEPTED with {s} "
                  f"(returned {ids}) although the data type documents it as NOT "
                  f"supported inside nested — doc-consistency signal recorded, "
                  f"not judged (G3-avoidance)")
        else:
            print(f"G4 OK: has_id inside nested rejected with {s} as documented")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
