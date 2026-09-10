#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_recommend_dualkey_008
# strategy: strategy2 R33/R40 dual-key silent-drop family — the proven
#           serde-untagged family (3 confirmed instances: silently drop
#           the second variant, 200, first wins) measured on the recommend
#           face's own input variants: positive arrays mixing an id
#           example and a mirrored vector example. Contract ground: the
#           vendored RecommendStrategy doc promises average_vector
#           "average positive and negative vectors" — ALL examples, so a
#           silently discarded example is a state-logic violation, not a
#           tolerance
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — each positive[]
#            element resolves through the UNTAGGED RecommendExample oneOf;
#            R33/R40 PROVED this resolution family silently discards
#            content on three sibling faces; the recommend face's mixed
#            example arrays are the unmeasured member)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: R33/R40 dual-key family x qdrant_behavioral_points_recommend_001 —
  the positive[] field holds RecommendExample elements resolved through an
  untagged oneOf {id, vector, sparse}. The proven family defect is silent
  discard of the second variant with a 200. Construction with LIVE
  baselines and deterministic fingerprints (never assumed — R39):
    seed  cluster A ids 1-3 at +V*f, cluster B ids 4-6 at the EXACT
          negations (-V*f), cluster C ids 7-9 at V*0.01*f (near origin),
          cluster D ids 10-12 far-rotated; f = 1.01/1.02/1.03;
          Euclid + binary-exact floats (R27) + params.exact=true so
          avg(A_1, B_4) = (V*1.01 + (-V*1.01)) / 2 = 0.0 EXACTLY in IEEE
          doubles (x + (-x) is exact), and a zero query vector's top-3 is
          exactly the C cluster.
    G    read-back guard: fetch stored vectors of ids 1 and 4 and verify
         stored(4) == -stored(1) exactly — otherwise the mirror premise
         is ungrounded and the script declines (SCRIPT_ERROR)
    E1   baseline positive=[1] (single id example)   -> 200, {2,3} in
         top-3 (fpA)
    E2   baseline positive=[4] (single id example)   -> 200, {5,6} in
         top-3 (fpB)
    E3   positive=[1, 4] (BOTH id examples;         -> 200 with top-3 ==
         schema-legal: each element is an               {7,8,9} (both
         independent oneOf resolution)                  examples honored:
                                                       avg = 0 -> C wins);
                                                       top-3 matching fpA
                                                       = example 4 SILENTLY
                                                       DISCARDED (R33
                                                       family); fpB =
                                                       example 1 discarded
    E4   positive=[1, readback(4)] (id + raw        -> same trio of
         vector, mixed variant resolution)             dispositions
  G6 mutation justification: the mutation point is the SECOND example of
  a mixed untagged-oneOf array — the exact spot where the proven family
  loses data (variant resolution consumes the element set once); the
  fingerprint trio makes any loss observable in the returned ids.
  [chunk_points+recommend coverage (11 scripts): strategy1 limit boundary
  matrix x qdrant_range_points_recommend_001 (limit_001); strategy1 offset
  boundary matrix + huge-offset x qdrant_range_points_recommend_001
  (offset_002); behavioral positive core by-id/by-vector/strategy-enum
  closure x qdrant_behavioral_points_recommend_001 (positive_003); BS-10
  missing referenced point ids 400-legs x qdrant_behavioral_points_
  recommend_001 (missing_ref_004); using-vector characteristics mismatch
  (lookup dim + named partial) x qdrant_behavioral_points_recommend_001
  (using_mismatch_005); 404 status-mapping legs x qdrant_behavioral_
  points_recommend_001 (404_006); strategy2 RecommendExample oneOf element
  type-confusion + raw-vector dimension x qdrant_behavioral_points_
  recommend_001 (example_type_007); R33/R40 dual-key silent-drop family on
  mixed recommend examples x qdrant_behavioral_points_recommend_001 (this
  script); strategy2 filter type-confusion family mirror x
  qdrant_behavioral_points_recommend_001 (filter_type_009); strategy6
  conservative single-extreme + modest-product resource x
  qdrant_range_points_recommend_001 (resource_010); strategy7 malformed
  raw-byte stream x qdrant_behavioral_points_recommend_001
  (malformed_011)]
Oracle: G -> stored(4) == -stored(1) exactly (else SCRIPT_ERROR: mirror
  premise ungrounded); E1 -> 200 with {2,3} within the top-3 ids and E2 ->
  200 with {5,6} within the top-3 ids (baseline failure = SCRIPT_ERROR,
  no defect conclusion — live baselines are preconditions, R39); E3/E4 ->
  200 with top-3 ids EXACTLY {7,8,9} = NO_DEFECT (both examples honored);
  200 with top-3 containing {2,3} = DEFECT_FOUND (Type4_StateLogicViolation:
  the second example silently discarded though average_vector promises ALL
  positives averaged — R33 proven family on the recommend face); 200 with
  {5,6} = same DEFECT with the first example discarded; 200 matching
  neither fingerprint = SCRIPT_ERROR (unmeasured semantics); 4xx on E3/E4
  = Type1_IllegalSuccess (schema-legal documented request rejected); 5xx
  with /healthz alive = Type3_RuntimeFailure; transport failure ->
  /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_recommend_001).
Constraint: qdrant_behavioral_points_recommend_001 (bare id) — "returns
  200 [ScoredPoint]; 400 when a positive/negative references a point
  without the used vector or a missing point (fetched vectors must match
  the using-vector characteristics); 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+recommend      -> POST /collections/{collection_name}/points/recommend
  points+upsert         -> PUT  /collections/{collection_name}/points
  points+get (bulk)     -> POST /collections/{collection_name}/points
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
  healthz               -> GET  /healthz
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
W = [0.0625, 0.125, 0.25, 0.5]


def build_seed():
    """A ids 1-3 at +V*f; B ids 4-6 at exact negations; C ids 7-9 near origin; D ids 10-12 far."""
    pts = []
    for i, f in ((1, 1.01), (2, 1.02), (3, 1.03)):
        pts.append({"id": i, "vector": [v * f for v in V]})
    for i, f in ((4, 1.01), (5, 1.02), (6, 1.03)):
        pts.append({"id": i, "vector": [-v * f for v in V]})
    for i, f in ((7, 1.07), (8, 1.08), (9, 1.09)):
        pts.append({"id": i, "vector": [v * 0.01 * f for v in V]})
    for i, f in ((10, 1.10), (11, 1.11), (12, 1.12)):
        pts.append({"id": i, "vector": [w * 1.5 * f for w in W]})
    return pts


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """Safe HTTP wrapper -> (status_code, body, raw_text); transport failure -> (-1, err, err)."""
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


def extract_scored(body):
    """Contract response_shape: result is a top-level array of ScoredPoints."""
    if not isinstance(body, dict):
        return None, "body-not-dict"
    result = body.get("result")
    if isinstance(result, list):
        return result, "result-array"
    return None, "result-missing-or-not-array"


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bprD8" + tag

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = build_seed()
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        # ---- Leg G: read-back mirror guard (R27 + mirror premise) ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points",
                                 json={"ids": [1, 4], "with_vector": True,
                                       "with_payload": False}, timeout=60)
        print(f"leg G read-back mirror guard -> status={s}")
        if s != 200 or not isinstance(b, dict) or not isinstance(b.get("result"), list) \
                or len(b["result"]) != 2:
            print(f"raw: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — read-back guard failed")
            return
        vec = {p.get("id"): p.get("vector") for p in b["result"]}
        v1, v4 = vec.get(1), vec.get(4)
        if v1 is None or v4 is None or v4 != [-x for x in v1]:
            print(f"mirror premise broken: v1={v1} v4={v4}")
            print("VERDICT: SCRIPT_ERROR — stored(4) != -stored(1), fingerprint trio ungrounded")
            return
        print("leg G OK: stored(4) == -stored(1) exactly — avg query will be exactly 0")

        def top3_ids(positive):
            payload = {"positive": positive, "limit": 3, "params": {"exact": True},
                       "strategy": "average_vector"}
            return safe_request("POST", f"/collections/{coll}/points/recommend",
                                json=payload, timeout=60)

        # ---- Leg E1: baseline single id example 1 -> fpA ----
        s, b, raw = top3_ids([1])
        print(f"\nleg E1 positive=[1] baseline -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1 or 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if s == -1:
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive
                      else "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            elif alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [E1]: {s} with "
                      f"service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        scored, shape = extract_scored(b)
        if s != 200 or scored is None or len(scored) != 3:
            print(f"VERDICT: SCRIPT_ERROR — baseline E1 failed ({s}, {shape}); no defect conclusion")
            return
        ids_e1 = {sp.get("id") for sp in scored}
        if not {2, 3} <= ids_e1:
            print(f"VERDICT: SCRIPT_ERROR — fpA baseline not established, top3={sorted(ids_e1)}")
            return
        print(f"leg E1 OK: fpA established, top3={sorted(ids_e1)}")

        # ---- Leg E2: baseline single id example 4 -> fpB ----
        s, b, raw = top3_ids([4])
        print(f"\nleg E2 positive=[4] baseline -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1 or 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if s == -1:
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive
                      else "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            elif alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [E2]: {s} with "
                      f"service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        scored, shape = extract_scored(b)
        if s != 200 or scored is None or len(scored) != 3:
            print(f"VERDICT: SCRIPT_ERROR — baseline E2 failed ({s}, {shape}); no defect conclusion")
            return
        ids_e2 = {sp.get("id") for sp in scored}
        if not {5, 6} <= ids_e2:
            print(f"VERDICT: SCRIPT_ERROR — fpB baseline not established, top3={sorted(ids_e2)}")
            return
        print(f"leg E2 OK: fpB established, top3={sorted(ids_e2)}")

        # ---- Legs E3 / E4: mixed example arrays — drop-or-honor ----
        for label, positive in (("E3 positive=[1, 4] (both id)", [1, 4]),
                                ("E4 positive=[1, readback(4)] (id + vector)", [1, v4])):
            s, b, raw = top3_ids(positive)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, _, _ = healthz_alive()
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                      "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: {s} "
                          f"with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s in (400, 404, 422):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: the "
                      f"positive array {[type(x).__name__ for x in positive]} is schema-legal "
                      f"(array[RecommendExample], each element an independent oneOf resolution) "
                      f"and must be accepted, got {s}: {raw[:300]}")
                return
            scored, shape = extract_scored(b)
            if s != 200 or scored is None:
                print(f"VERDICT: SCRIPT_ERROR — unexpected status/envelope {s} ({shape}); no defect conclusion")
                return
            ids = {sp.get("id") for sp in scored}
            if ids == {7, 8, 9}:
                print(f"leg {label} OK: top3 == {{7,8,9}} — BOTH examples honored (avg=0 -> C "
                      f"cluster wins); R33-family silent-drop ABSENT on this face")
            elif {2, 3} <= ids:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: top3="
                      f"{sorted(ids)} matches the single-example fpA fingerprint — the SECOND "
                      f"positive example was SILENTLY DISCARDED although average_vector promises "
                      f"to average ALL positive examples (R33/R40 proven family on the recommend "
                      f"face): {raw[:300]}")
                return
            elif {5, 6} <= ids:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: top3="
                      f"{sorted(ids)} matches the single-example fpB fingerprint — the FIRST "
                      f"positive example was SILENTLY DISCARDED although average_vector promises "
                      f"to average ALL positive examples (R33/R40 proven family on the recommend "
                      f"face): {raw[:300]}")
                return
            else:
                print(f"VERDICT: SCRIPT_ERROR — leg [{label}]: top3={sorted(ids)} matches neither "
                      f"baseline nor the both-honored fingerprint; unmeasured semantics, no "
                      f"defect conclusion")
                return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
