#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_params_bounds_001
# strategy: strategy1 behavioral-contract attack (SearchParams range closure)
#           + strategy2 diagnosis-quality scoring on the rejection faces
# endpoint: points+query
# constraint_ids: qdrant_range_points_query_002
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-04 (boundary closure) + BS-02 (Error Message Negligence on
#            the rejection legs, scored with the R29-calibrated rubric)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy1 SearchParams range closure x qdrant_range_points_query_002 —
  the contract fixes SearchParams.hnsw_ef minimum 1 and the ACORN scale
  within [0.0, 1.0] (default 0.4). Spec-derived field cross-check (D3b/R38):
  the published v1.18.x OpenAPI spells the ACORN object as
  params.acorn = {enable: bool, max_selectivity: number, minimum 0,
  maximum 1, default 0.4}; the contract prose calls it acorn_scale. The
  spec-derived name (max_selectivity) carries the hard oracle; the doc-side
  name is probed as a G9 disposition-asymmetry NOTE only. Legs (all on a
  nearest query over 8 seeded points, exact=true for determinism):
    B1 hnsw_ef=1  (min closure)     -> 200, top-1 == query point
    B2 hnsw_ef=0  (< min)           -> 4xx; 2xx = Type1_IllegalSuccess
    B3 acorn.max_selectivity=0.0    -> 200 (closure low)
    B4 acorn.max_selectivity=1.0    -> 200 (closure high)
    B5 acorn.max_selectivity=1.5    -> 4xx; 2xx = Type1 (range violated)
    B6 acorn.max_selectivity=-0.1   -> 4xx; 2xx = Type1 (range violated)
    B7 acorn.acorn_scale=0.4 (doc name) -> disposition NOTE only (naming
       drift between doc prose and published spec; G9 asymmetry record)
  Rejection-leg messages are rubric-scored (param-named 1pt, format-hint
  1pt, actionable 1pt). Per the R38 standing lesson (R29: Type2 error
  naming has NO anchor in qdrant), parameter naming is NOT a hard oracle:
  a Type2 defect is declared only for a message with no usable content at
  all (empty body or a bare "internal error" with no hint).
  [chunk_points+query semantic coverage — see variant_domain_001 for the
  full 10-script coverage list; this script = params-range x
  qdrant_range_points_query_002]
Oracle: B1/B3/B4 -> HTTP 200 with result.points non-empty and top-1 id ==
  301 with score 1.0 (Euclid self-match); B2/B5/B6 -> 400-family 4xx whose
  body carries usable validation content; any 2xx on B2/B5/B6 =
  Type1_IllegalSuccess (documented range not enforced); 5xx with /healthz
  alive = Type3_RuntimeFailure; empty/internal-error-only rejection body =
  Type2_PoorDiagnostics; transport failure -> /healthz re-check then
  SCRIPT_ERROR (constraint qdrant_range_points_query_002).
Constraint: qdrant_range_points_query_002 (bare id) — "SearchParams:
  hnsw_ef minimum 1; acorn_scale within [0.0, 1.0] (default 0.4)"
  (evidence_tier: explicit; level: endpoint)

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
IDS = list(range(301, 309))
SEED = [{"id": i, "vector": [float((i - 301)), float((i - 301) % 3),
                             0.0, 1.0]} for i in IDS]
ANCHOR_VEC = SEED[0]["vector"]  # query point 301 -> top-1 itself, score 1.0

FORMAT_HINTS = ["must be", "expected", "should be", "valid", "range", "type",
                "minimum", "maximum", "greater", "less", "positive", "non-zero",
                "unknown", "invalid", "parse", "deserialize", "validation"]
ACTION_HINTS = ["correct", "try", "use ", "change", "specify", "provide",
                "instead", "create", "enable"]


def score_error_quality(raw, keywords):
    """
    Type-2 diagnosis quality rubric (R29-calibrated):
    -1 = unusable (no content at all) -> Type2 defect territory
     0..3 = usable to varying degree, informational only.
    body may be a dict (JSON) or str (non-JSON) — handled.
    """
    msg = json.dumps(raw).lower() if isinstance(raw, dict) else str(raw or "").lower()
    if not msg.strip():
        return -1, ""
    if "internal error" in msg and "internal server error" in msg \
            and not any(h in msg for h in FORMAT_HINTS + ACTION_HINTS):
        return -1, msg
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


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqP1" + tag

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

        def accepted_leg(leg, params_obj):
            """200-leg: exact correctness closure (top-1 self-match)."""
            s, body, raw = safe_request("POST", qpath,
                                        json={"query": {"nearest": ANCHOR_VEC},
                                              "params": dict({"exact": True}, **params_obj),
                                              "limit": 8}, timeout=60)
            print(f"{leg} -> status={s}")
            print(f"raw: {raw[:300]}")
            if s == -1:
                transport_dead(leg)
                return False
            if handle_5xx(s, raw, leg):
                return False
            pts = get_points(body)
            if 400 <= s <= 499:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{leg}]: "
                      f"documented in-range SearchParams value rejected with {s}: "
                      f"{raw[:250]}")
                return False
            if s != 200 or pts is None or not pts:
                print(f"VERDICT: SCRIPT_ERROR — leg [{leg}] unexpected outcome "
                      f"status={s}; no defect conclusion")
                return False
            if pts[0].get("id") != 301 or abs(float(pts[0].get("score", 0.0)) - 1.0) > 1e-6:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg "
                      f"[{leg}]: exact self-match must be top-1 id 301 score 1.0, "
                      f"got id={pts[0].get('id')} score={pts[0].get('score')}: "
                      f"{raw[:250]}")
                return False
            print(f"{leg} OK: accepted, results intact")
            return True

        def rejected_leg(leg, params_obj, keywords):
            """4xx-leg: out-of-range must be rejected with usable diagnostics."""
            s, body, raw = safe_request("POST", qpath,
                                        json={"query": {"nearest": ANCHOR_VEC},
                                              "params": dict({"exact": True}, **params_obj),
                                              "limit": 8}, timeout=60)
            print(f"{leg} -> status={s}")
            print(f"raw: {raw[:300]}")
            if s == -1:
                transport_dead(leg)
                return False
            if handle_5xx(s, raw, leg):
                return False
            if 200 <= s <= 299:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{leg}]: "
                      f"documented out-of-range SearchParams value accepted with "
                      f"{s}: {raw[:250]}")
                return False
            if not (400 <= s <= 499):
                print(f"VERDICT: SCRIPT_ERROR — leg [{leg}] unexpected status {s}; "
                      f"no defect conclusion")
                return False
            score, msg = score_error_quality(raw, keywords)
            print(f"{leg} OK: rejected by {s}; diagnosis rubric score={score}/3 "
                  f"(R29: naming is informational, not an anchor)")
            if score < 0:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — leg [{leg}]: "
                      f"rejection carries no usable diagnostic content: {raw[:200]}")
                return False
            return True

        if not accepted_leg("B1 hnsw_ef=1 (min closure)", {"hnsw_ef": 1}):
            return
        if not rejected_leg("B2 hnsw_ef=0", {"hnsw_ef": 0}, ["hnsw_ef", "ef"]):
            return
        if not accepted_leg("B3 acorn.max_selectivity=0.0 (closure low)",
                            {"acorn": {"enable": True, "max_selectivity": 0.0}}):
            return
        if not accepted_leg("B4 acorn.max_selectivity=1.0 (closure high)",
                            {"acorn": {"enable": True, "max_selectivity": 1.0}}):
            return
        if not rejected_leg("B5 acorn.max_selectivity=1.5",
                            {"acorn": {"enable": True, "max_selectivity": 1.5}},
                            ["acorn", "max_selectivity", "selectivity"]):
            return
        if not rejected_leg("B6 acorn.max_selectivity=-0.1",
                            {"acorn": {"enable": True, "max_selectivity": -0.1}},
                            ["acorn", "max_selectivity", "selectivity"]):
            return

        # B7: doc-side name acorn_scale — disposition NOTE only (G9 asymmetry)
        s, body, raw = safe_request("POST", qpath,
                                    json={"query": {"nearest": ANCHOR_VEC},
                                          "params": {"exact": True,
                                                     "acorn": {"enable": True,
                                                               "acorn_scale": 0.4}},
                                          "limit": 8}, timeout=60)
        print(f"B7 acorn.acorn_scale (doc name) -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1:
            transport_dead("B7")
            return
        if handle_5xx(s, raw, "B7 acorn_scale"):
            return
        if 200 <= s <= 299:
            print("NOTE B7: doc-prose name 'acorn_scale' accepted (either aliased "
                  "or silently ignored as unknown key) — naming drift vs the "
                  "spec-derived 'max_selectivity'; disposition recorded, not judged")
        else:
            print("NOTE B7: doc-prose name 'acorn_scale' rejected with "
                  f"{s} while spec name 'max_selectivity' is accepted — G9 "
                  f"parameter-family asymmetry recorded for the doc-consistency lane")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
