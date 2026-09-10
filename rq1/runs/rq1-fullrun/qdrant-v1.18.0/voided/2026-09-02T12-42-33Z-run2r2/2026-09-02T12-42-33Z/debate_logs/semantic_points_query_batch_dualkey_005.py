#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_batch_dualkey_005
# strategy: strategy4 type-coercion attack (R33 serde-untagged dual-key
#           family extended to the query oneOf, cross-face G9 comparison:
#           single query face vs batch query face)
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde untagged enums were
#            PROVEN to silently discard the second key on batch endpoints,
#            R33; this script checks whether the same laxity or its rejection
#            is applied CONSISTENTLY across the two query faces)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy4 dual-key query oneOf cross-face x
  qdrant_behavioral_points_query_batch_001 — QueryRequestQuery resolves to
  Query = oneOf {NearestQuery, RecommendQuery, ..., OrderByQuery, ...}
  (vendored OpenAPI), so a query object carrying TWO variant keys
  ({"nearest": [...], "order_by": {...}}) is oneOf-ambiguous: not licensed
  by the schema. R33 proved serde untagged dual-key elements silently
  discard the second key on the points+batch face (REST-only); the R39
  single-face variant-domain probe never reached its dual-key leg (it
  stopped on an earlier defect), so the disposition on BOTH query faces is
  unmeasured. This script measures both faces with LIVE baselines (no
  assumed interpretation — which variant wins is read off by comparing
  against pure-nearest and pure-order_by results measured in the same run):
    BN baseline single face, pure nearest  -> fingerprint FN (expect [871,872,873])
    BO baseline single face, pure order_by desc -> fingerprint FO (expect [878,877,876])
    S  single face POST points/query with the dual-key query object
    B  batch face POST points/query/batch {"searches":[{same dual-key entry}]}
  Adjudication (G9 — the SAME payload on the two faces of the same query
  engine must get a consistent disposition):
    - both faces 4xx                     -> NO_DEFECT (oneOf enforced consistently)
    - both faces 2xx, same variant wins  -> NOTE: consistent untagged-enum
      tolerance on a READ face (R33 family shape, benign per the R35 read-
      face calibration); which key won is recorded; NO_DEFECT
    - both faces 2xx, DIFFERENT variants win, or one face 2xx while the
      other 4xx -> DEFECT_FOUND (Type4): cross-face inconsistent disposition
      of one payload — a client porting a working single query into a batch
      silently gets different results (or vice versa)
  [chunk_points+query+batch semantic coverage (7 scripts): search_correctness
  per-entry limit + k-nearest prefix + mixed invalid-entry atomicity +
  empty-searches N-in/N-out x behavioral_points_query_batch_001
  (perelem_limit_001); metamorphic per-entry offset window x
  behavioral_points_query_batch_001 (perelem_offset_002); filter_semantics
  per-entry exact-set closure + bleed isolation x
  behavioral_points_query_batch_001 (perelem_filter_003); behavioral_contract
  mixed-variant per-entry dispatch x behavioral_points_query_batch_001
  (this lane's mixed_variant_004); type_coercion R33-family dual-key query
  oneOf cross-face x behavioral_points_query_batch_001 (this); metamorphic
  single vs batch-of-1 + VectorInput shorthand x
  behavioral_points_query_batch_001 (single_vs_batch_006); diagnosis_quality
  404 + validation message rubric x behavioral_points_query_batch_001
  (404_diag_007)]
Oracle: BN -> 200 ids == live pure-nearest fingerprint; BO -> 200 ids == live
  pure-order_by-desc fingerprint; S and B each independently 4xx (consistent
  enforcement -> NO_DEFECT) or 2xx with ids equal to exactly one of the two
  baselines (interpretation read off live, never assumed); DEFECT_FOUND
  (Type4_StateLogicViolation) iff the two faces' dispositions or winning
  variants DIVERGE (same payload, same engine, different behavior — G9
  cross-face asymmetry); 5xx with /healthz alive = Type3_RuntimeFailure;
  transport failure -> /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_query_batch_001).
Constraint: qdrant_behavioral_points_query_batch_001 (bare id) — "executes
  multiple queries in one call; returns 200 with a list of per-query results;
  404 for a missing collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query        -> POST /collections/{collection_name}/points/query
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
ANCHOR_A = [1.0, 0.0, 0.0, 0.0]   # nearest self-match id 871 (unique ranking)

SEED = [{"id": 871, "vector": [1.0, 0.0, 0.0, 0.0], "payload": {"ts": 0}},
        {"id": 872, "vector": [0.0, 1.0, 0.0, 0.0], "payload": {"ts": 1}}]
for i in range(873, 879):
    SEED.append({"id": i, "vector": [float(5 + (i - 873)), 5.0, 5.0, 5.0],
                 "payload": {"ts": i - 871}})


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
    coll = "spqbD5" + tag

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
        s, _, raw = safe_request("PUT", f"/collections/{coll}/index",
                                 json={"field_name": "ts", "field_schema": "integer"},
                                 params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"NOTE setup: ts index create returned {s}: {raw[:200]}")

        qpath = f"/collections/{coll}/points/query"
        bpath = f"/collections/{coll}/points/query/batch"

        # ---- BN: live baseline, pure nearest on the single face ----
        s, body, raw = safe_request("POST", qpath,
                                    json={"query": {"nearest": ANCHOR_A},
                                          "params": {"exact": True}, "limit": 3}, timeout=60)
        print(f"BN pure nearest (single face) -> status={s}")
        print(f"raw: {raw[:350]}")
        if s == -1:
            bail_transport("BN")
            return
        if handle_5xx(s, raw, "BN"):
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: SCRIPT_ERROR — BN unexpected status {s}; no defect conclusion")
            return
        fn = ids_of(single_points(body) or [])
        print(f"BN fingerprint FN = {fn}")

        # ---- BO: live baseline, pure order_by desc on the single face ----
        s, body, raw = safe_request("POST", qpath,
                                    json={"query": {"order_by": {"key": "ts",
                                                                 "direction": "desc"}},
                                          "limit": 3}, timeout=60)
        print(f"BO pure order_by desc (single face) -> status={s}")
        print(f"raw: {raw[:350]}")
        if s == -1:
            bail_transport("BO")
            return
        if handle_5xx(s, raw, "BO"):
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: SCRIPT_ERROR — BO unexpected status {s}; no defect conclusion")
            return
        fo = ids_of(single_points(body) or [])
        print(f"BO fingerprint FO = {fo}")
        if fn == fo:
            print("VERDICT: SCRIPT_ERROR — baselines collide, interpretation "
                  "undecidable; no defect conclusion")
            return

        dual_query = {"nearest": list(ANCHOR_A),
                      "order_by": {"key": "ts", "direction": "desc"}}

        # ---- S: single face with the dual-key query object ----
        s, body, raw = safe_request("POST", qpath,
                                    json={"query": dual_query,
                                          "params": {"exact": True}, "limit": 3}, timeout=60)
        print(f"S single-face dual-key query -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            bail_transport("S")
            return
        if handle_5xx(s, raw, "S"):
            return
        s_disposition = ("reject", None) if 400 <= s <= 499 else None
        s_ids = None
        if 200 <= s <= 299:
            s_ids = ids_of(single_points(body) or [])
            if s_ids == fn:
                s_disposition = ("accept", "nearest")
            elif s_ids == fo:
                s_disposition = ("accept", "order_by")
            else:
                s_disposition = ("accept", "other")
        elif s_disposition is None:
            print(f"VERDICT: SCRIPT_ERROR — S unexpected status {s}; no defect conclusion")
            return
        print(f"S disposition = {s_disposition}")

        # ---- B: batch face with the same dual-key entry ----
        s, body, raw = safe_request("POST", bpath,
                                    json={"searches": [{"query": dual_query,
                                                        "params": {"exact": True},
                                                        "limit": 3}]}, timeout=60)
        print(f"B batch-face dual-key entry -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            bail_transport("B")
            return
        if handle_5xx(s, raw, "B"):
            return
        b_disposition = ("reject", None) if 400 <= s <= 499 else None
        if 200 <= s <= 299:
            b_ids = ids_of(batch_first_entry(body) or [])
            if b_ids == fn:
                b_disposition = ("accept", "nearest")
            elif b_ids == fo:
                b_disposition = ("accept", "order_by")
            else:
                b_disposition = ("accept", "other")
        elif b_disposition is None:
            print(f"VERDICT: SCRIPT_ERROR — B unexpected status {s}; no defect conclusion")
            return
        print(f"B disposition = {b_disposition}")

        # ---- G9 cross-face adjudication ----
        if s_disposition[0] == "reject" and b_disposition[0] == "reject":
            print("both faces reject the oneOf-ambiguous dual-key payload — "
                  "consistent enforcement")
            print("VERDICT: NO_DEFECT")
            return
        if s_disposition[0] == "accept" and b_disposition[0] == "accept":
            if s_disposition[1] == b_disposition[1]:
                print(f"NOTE both faces accept and the same variant wins "
                      f"({s_disposition[1]}) — consistent serde-untagged "
                      f"tolerance on a READ face (R33 family shape; read-face "
                      f"benign per the R35 calibration), second key silently "
                      f"discarded; recorded for the judge")
                print("VERDICT: NO_DEFECT")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"the SAME dual-key query payload is executed with "
                      f"DIFFERENT variants on the two faces: single face -> "
                      f"{s_disposition[1]} ({s_ids}), batch face -> "
                      f"{b_disposition[1]}; a query ported between the two "
                      f"documented faces silently changes meaning (G9 "
                      f"cross-face inconsistent disposition)")
            return
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
              f"cross-face inconsistent disposition of the same dual-key "
              f"payload: single face {s_disposition}, batch face "
              f"{b_disposition} (G9 asymmetry; R33 family)")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
