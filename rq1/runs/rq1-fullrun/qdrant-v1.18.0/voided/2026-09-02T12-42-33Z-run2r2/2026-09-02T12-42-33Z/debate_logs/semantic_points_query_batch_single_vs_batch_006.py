#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_batch_single_vs_batch_006
# strategy: strategy6 metamorphic attack (query-form equivalence: single face
#           vs batch-of-1 vs the VectorInput shorthand branch — the same
#           query under all documented spellings must yield the identical
#           ranking)
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift — QueryRequestQuery is oneOf
#            [VectorInput, Query] in the published schema: the bare-vector
#            shorthand is a documented spelling of nearest; drift between
#            spellings is the metamorphic relation under test)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy6 single vs batch-of-1 vs VectorInput shorthand x
  qdrant_behavioral_points_query_batch_001 — "executes multiple queries in
  one call" means a batch-of-1 must execute exactly the QueryRequest it
  wraps, and the published QueryRequestQuery schema is oneOf [VectorInput,
  Query] (vendored OpenAPI), so {"query": {"nearest": v}} and {"query": v}
  are two documented spellings of the SAME nearest query. The state lane
  already verified batch-vs-single id-SET equality for by-id entries; this
  script pins the equivalence for NEAREST entries at full LIST equality
  (order too) and extends it to the shorthand spelling — both unmeasured.
  9 points at strictly increasing Euclid distances 1..9 from anchor ORIG
  (unique ranking, params.exact=true; ids only, never scores — R39):
    M1 single face   POST points/query        {"query": {"nearest": ORIG},
                                               "limit": 5, exact}
    M2 batch-of-1    POST points/query/batch  {"searches": [<same entry>]}
    M3 shorthand     POST points/query/batch  {"searches": [{"query": ORIG,
                                               "limit": 5, exact}]} (VectorInput
                                               branch — the bare vector)
  Hard oracle: M1 == M2 id LIST equality (both unambiguously documented
  forms). M3: if 200, must equal M1 too (same branch semantics); a 4xx on
  M3 is recorded as a spec-vs-impl divergence NOTE (the published schema
  licenses the form — R39 doc-drift recording convention — judge call, not
  an auto-defect).
  [chunk_points+query+batch semantic coverage (7 scripts): search_correctness
  per-entry limit + k-nearest prefix + mixed invalid-entry atomicity +
  empty-searches N-in/N-out x behavioral_points_query_batch_001
  (perelem_limit_001); metamorphic per-entry offset window x
  behavioral_points_query_batch_001 (perelem_offset_002); filter_semantics
  per-entry exact-set closure + bleed isolation x
  behavioral_points_query_batch_001 (perelem_filter_003); behavioral_contract
  mixed-variant per-entry dispatch x behavioral_points_query_batch_001
  (mixed_variant_004); type_coercion R33-family dual-key query oneOf
  cross-face x behavioral_points_query_batch_001 (dualkey_005); metamorphic
  single vs batch-of-1 + VectorInput shorthand x
  behavioral_points_query_batch_001 (this); diagnosis_quality 404 +
  validation message rubric x behavioral_points_query_batch_001
  (404_diag_007)]
Oracle: M1 -> 200 with 5 point ids == [901..905] (unique-distance ranking,
  live-measured); M2 -> 200 with ids LIST-identical to M1 (any divergence =
  Type4_StateLogicViolation: the batch wrapper changed query semantics;
  4xx = Type1_IllegalRejection — the documented wrapper rejected); M3 -> if
  200, ids LIST-identical to M1 (divergence = Type4: the VectorInput branch
  executes different semantics than the same query spelled via nearest);
  if 4xx, NOTE spec-vs-impl divergence recorded (published schema licenses
  the branch); 5xx with /healthz alive = Type3_RuntimeFailure; transport
  failure -> /healthz liveness re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_query_batch_001).
Constraint: qdrant_behavioral_points_query_batch_001 (bare id) — "executes
  multiple queries in one call; returns 200 with a list of per-query results;
  404 for a missing collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query        -> POST /collections/{collection_name}/points/query
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
IDS = list(range(901, 910))          # 901..909, distance to anchor == i-900
ORIG = [0.0, 0.0, 0.0, 0.0]
SEED = [{"id": i, "vector": [float(i - 900), 0.0, 0.0, 0.0]} for i in IDS]


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


def single_points(body):
    """Single-face result extraction (response_shape result.points array)."""
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, dict) and isinstance(r.get("points"), list):
            return r["points"]
        if isinstance(r, list):
            print("NOTE single face returned a list-form result (published "
                  "schema declares result.points object form) — recorded")
            return r
    return None


def batch_first_entry(body):
    """Batch-face extraction of entry[0]'s point list (result[].points)."""
    if not isinstance(body, dict):
        return None
    outer = body.get("result")
    if not isinstance(outer, list) or len(outer) != 1:
        return None
    e = outer[0]
    if isinstance(e, dict) and isinstance(e.get("points"), list):
        return e["points"]
    if isinstance(e, list):
        print("NOTE batch entry[0]: bare-array envelope form observed "
              "(published schema declares result[].points object form) — recorded")
        return e
    return None


def ids_of(points):
    return [p.get("id") for p in points if isinstance(p, dict)]


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqbS6" + tag

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
        bpath = f"/collections/{coll}/points/query/batch"
        base_entry = {"query": {"nearest": ORIG}, "params": {"exact": True}, "limit": 5}

        # ---- M1: single face ----
        s, body, raw = safe_request("POST", qpath, json=base_entry, timeout=60)
        print(f"M1 single face nearest-dict -> status={s}")
        print(f"raw: {raw[:350]}")
        if s == -1:
            bail_transport("M1")
            return
        if handle_5xx(s, raw, "M1"):
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: SCRIPT_ERROR — M1 unexpected status {s}; no defect conclusion")
            return
        m1 = ids_of(single_points(body) or [])
        if m1 != IDS[:5]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M1: "
                  f"unique-distance ranking must start {IDS[:5]}, got {m1}: "
                  f"{raw[:250]}")
            return
        print(f"M1 OK: ranking head {m1}")

        # ---- M2: batch-of-1, same entry ----
        s, body, raw = safe_request("POST", bpath, json={"searches": [base_entry]}, timeout=60)
        print(f"M2 batch-of-1 same entry -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            bail_transport("M2")
            return
        if handle_5xx(s, raw, "M2"):
            return
        if 400 <= s <= 499:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — M2: the "
                  f"documented batch wrapper executing the identical valid "
                  f"entry was rejected with {s}: {raw[:250]}")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: SCRIPT_ERROR — M2 unexpected status {s}; no defect conclusion")
            return
        m2 = ids_of(batch_first_entry(body) or [])
        if m2 != m1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M2: "
                  f"batch-of-1 must execute exactly the wrapped query: "
                  f"expected {m1}, got {m2} (wrapper changed query semantics): "
                  f"{raw[:250]}")
            return
        print("M2 OK: batch-of-1 ranking LIST-identical to the single face")

        # ---- M3: shorthand VectorInput branch inside batch-of-1 ----
        shorthand_entry = {"query": list(ORIG), "params": {"exact": True}, "limit": 5}
        s, body, raw = safe_request("POST", bpath, json={"searches": [shorthand_entry]}, timeout=60)
        print(f"M3 batch-of-1 VectorInput shorthand -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            bail_transport("M3")
            return
        if handle_5xx(s, raw, "M3"):
            return
        if 200 <= s <= 299:
            m3 = ids_of(batch_first_entry(body) or [])
            if m3 != m1:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M3: "
                      f"the VectorInput branch must execute the same nearest "
                      f"query as the 'nearest' spelling: expected {m1}, "
                      f"got {m3}: {raw[:250]}")
                return
            print("M3 OK: shorthand spelling ranking LIST-identical")
        elif 400 <= s <= 499:
            print("NOTE M3: bare-vector query rejected with 4xx although the "
                  "published QueryRequestQuery schema is oneOf [VectorInput, "
                  "Query] and licenses the form — spec-vs-impl divergence "
                  "recorded for the judge (R39 doc-drift convention), not "
                  "auto-adjudicated")
        else:
            print(f"VERDICT: SCRIPT_ERROR — M3 unexpected status {s}; no defect conclusion")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
