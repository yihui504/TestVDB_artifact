#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_status_faces_001
# strategy: strategy1 behavioral-contract attack (status-code tri-face) +
#           strategy2 diagnosis-quality scoring on the two rejection faces
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence) + BS-05 (Documentation Drift
#            on the documented 400/404 status contract)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy1 status tri-face x qdrant_behavioral_points_query_001 —
  the contract fixes three status behaviors of the query endpoint:
  200 + QueryResponse {result.points: [ScoredPoint]} on a valid query;
  400 on an invalid query; 404 when the collection is missing.
  Legs (6-point Euclid dim-4 collection):
    F1 valid nearest query
       -> exactly 200; result is an OBJECT carrying a points list (per the
          published response_shape result.points — R38 shape-oracle
          cross-check); each point has an id and a numeric score
    F2 invalid query: nearest vector of WRONG DIMENSION (3 vs 4)
       -> 400-family 4xx, never 2xx, never 5xx; message rubric-scored
    F3 invalid query: malformed filter (must = "not-a-list")
       -> 400-family 4xx; message rubric-scored
    F4 missing collection (freshly random name)
       -> exactly 404 (not 400, not 500, not 200); message rubric-scored
  Rubric (R29-calibrated): param-named 1pt + format-hint 1pt + actionable
  1pt; parameter naming is informational only — Type2 is declared solely
  for rejection bodies with no usable content at all (empty / bare
  internal-error).
  [chunk_points+query semantic coverage — see variant_domain_001 for the
  full 10-script coverage list; this script = status-faces x
  qdrant_behavioral_points_query_001]
Oracle: F1 -> HTTP 200 with body.result.points a non-empty list of objects
  each having id and numeric score; F2/F3 -> 400-family (400/422) with a
  non-empty JSON error body; any 2xx on F2/F3 = Type1_IllegalSuccess;
  F4 -> HTTP 404; F4 returning 400 or 2xx = Type4_StateLogicViolation
  (documented status misrouted); 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz re-check then
  SCRIPT_ERROR (constraint qdrant_behavioral_points_query_001).
Constraint: qdrant_behavioral_points_query_001 (bare id) — "returns 200
  QueryResponse {result: [ScoredPoint], next_page_offset?}; 400 on an
  invalid query; 404 when the collection is missing" (evidence_tier:
  explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query        -> POST /collections/{collection_name}/points/query
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
SEED = [{"id": i, "vector": [float(i - 41), 1.0, 0.0, 0.5]} for i in range(41, 47)]

FORMAT_HINTS = ["must be", "expected", "should be", "valid", "range", "type",
                "dimension", "dim", "minimum", "maximum", "unknown", "invalid",
                "parse", "deserialize", "validation", "not found", "exist"]
ACTION_HINTS = ["correct", "try", "use ", "change", "specify", "provide",
                "instead", "create", "collection"]


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


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqS1" + tag

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

        # ---- F1: valid query -> 200 + result.points shape ----
        s, body, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                    json={"query": {"nearest": [1.0, 1.0, 0.0, 0.5]},
                                          "limit": 3}, timeout=60)
        print(f"F1 valid query -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            transport_dead("F1 valid"); return
        if handle_5xx(s, raw, "F1 valid"):
            return
        result = body.get("result") if isinstance(body, dict) else None
        pts = result.get("points") if isinstance(result, dict) else None
        if s != 200 or not isinstance(pts, list) or not pts:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F1: valid "
                  f"query must return 200 with result.points a non-empty list "
                  f"(published response_shape result.points[]), got status={s}, "
                  f"result={json.dumps(result)[:150]}: {raw[:250]}")
            return
        for p in pts:
            if "id" not in p or not isinstance(p.get("score"), (int, float)):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F1: "
                      f"ScoredPoint must carry id and numeric score, got "
                      f"{json.dumps(p)[:150]}: {raw[:250]}")
                return
        status_val = body.get("status") if isinstance(body, dict) else None
        if status_val != "ok":
            print(f"NOTE F1: envelope status field is {status_val!r} (expected "
                  f"'ok') — recorded, not judged")
        print("F1 OK: 200 with result.points list of ScoredPoints")

        # ---- F2: invalid query — wrong-dimension vector ----
        s, _, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                 json={"query": {"nearest": [1.0, 2.0, 3.0]},
                                       "limit": 3}, timeout=60)
        print(f"F2 wrong-dim vector -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1:
            transport_dead("F2 wrong dim"); return
        if handle_5xx(s, raw, "F2 wrong dim"):
            return
        if 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F2: a dim-3 "
                  f"vector against a dim-4 collection is an invalid query per the "
                  f"documented 400 contract, got {s}: {raw[:250]}")
            return
        if not (400 <= s <= 499):
            print(f"VERDICT: SCRIPT_ERROR — F2 unexpected status {s}; no defect "
                  f"conclusion")
            return
        score, _ = score_error_quality(raw, ["dimension", "dim", "vector", "size"])
        print(f"F2 OK: invalid query rejected with {s}; rubric score={score}/3")
        if score < 0:
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — F2: rejection "
                  f"carries no usable diagnostic content: {raw[:200]}")
            return

        # ---- F3: invalid query — malformed filter ----
        s, _, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                 json={"query": {"nearest": [1.0, 1.0, 0.0, 0.5]},
                                       "filter": {"must": "not-a-list"},
                                       "limit": 3}, timeout=60)
        print(f"F3 malformed filter -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1:
            transport_dead("F3 bad filter"); return
        if handle_5xx(s, raw, "F3 bad filter"):
            return
        if 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F3: filter.must "
                  f"as a bare string is structurally invalid (must is a list of "
                  f"conditions per the Filter data type), got {s}: {raw[:250]}")
            return
        if not (400 <= s <= 499):
            print(f"VERDICT: SCRIPT_ERROR — F3 unexpected status {s}; no defect "
                  f"conclusion")
            return
        score, _ = score_error_quality(raw, ["filter", "must", "condition"])
        print(f"F3 OK: malformed filter rejected with {s}; rubric score={score}/3")
        if score < 0:
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — F3: rejection "
                  f"carries no usable diagnostic content: {raw[:200]}")
            return

        # ---- F4: missing collection -> exactly 404 ----
        missing = "spqNOPE" + tag
        s, _, raw = safe_request("POST", f"/collections/{missing}/points/query",
                                 json={"query": {"nearest": [1.0, 1.0, 0.0, 0.5]},
                                       "limit": 3}, timeout=60)
        print(f"F4 missing collection -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1:
            transport_dead("F4 missing collection"); return
        if handle_5xx(s, raw, "F4 missing collection"):
            return
        if s != 404:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F4: the "
                  f"documented status for a query against a missing collection is "
                  f"404, got {s}: {raw[:250]}")
            return
        score, _ = score_error_quality(raw, ["collection", "not found", missing])
        print(f"F4 OK: missing collection -> 404; rubric score={score}/3")
        if score < 0:
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — F4: 404 body "
                  f"carries no usable diagnostic content: {raw[:200]}")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
