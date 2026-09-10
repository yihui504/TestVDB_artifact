#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_acorn_001
# strategy: strategy1 boundary-value attack on SearchParams acorn_scale
#           ([0.0, 1.0] inclusive-closure promise) with type-confusion
#           existence probes first (the acorn sub-key nesting is documented
#           as "acorn {acorn_scale}" per contract data_types — the probes
#           distinguish live-nesting from silent-drop before any Type1 call)
# endpoint: points+query
# constraint_ids: qdrant_range_points_query_002
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-01 + BS-04 (Parameter Coercion Trust + Boundary Default
#            Optimism — an out-of-range acorn_scale accepted with 200, or a
#            SearchParams sub-key silently dropped, both leave the client
#            believing ACORN behavior it never got; the weaviate round-3
#            lesson forbids calling silent-drop a Type1 without evidence)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary x qdrant_range_points_query_002 — the contract
  asserts "acorn_scale within [0.0, 1.0] (default 0.4)" inside SearchParams
  of POST /collections/{c}/points/query. Because SearchParams sub-keys are
  not re-readable (no persistence face), the script first runs TYPE-CONFUSION
  EXISTENCE PROBES on both documented nestings —
    probeN: params={"acorn": {"acorn_scale": "0.4"}}  (string in nested form)
    probeF: params={"acorn_scale": "0.4"}             (string in flat form)
  a clean 4xx on a probe proves that nesting is LIVE (serde type error on a
  real field); a 200 proves the sub-key is silently DROPPED there. Range
  legs run only on live forms:
    Amin  acorn_scale=0.0  (min closure)  -> 200 with >= 1 point
    Amax  acorn_scale=1.0  (max closure)  -> 200 with >= 1 point
    Aunder acorn_scale=-0.01 (below min)  -> 400/422 reject
    Aover acorn_scale=1.01  (above max)   -> 400/422 reject
  If NO probe 4xxes, the script reports the silent-drop observation with
  full raw evidence and does NOT claim a Type1 (unadjudicable without an
  effect-observable — judge-side call).
  [chunk_points+query coverage: strategy1+6 limit x range_points_query_001
  (limit_001); strategy1 offset x range_points_query_001 (offset_001);
  strategy1 hnsw_ef x range_points_query_002 (hnswef_001); strategy1
  acorn_scale x range_points_query_002 (this script); strategy2 oneOf-domain
  negative x type_points_query_001 (variant_type_001); strategy2 oneOf-domain
  positive closure x type_points_query_001 (variant_matrix_001); strategy2
  invalid-query/filter + 404 x behavioral_points_query_001 (envelope_001);
  strategy7 malformed stream x behavioral_points_query_001 (malformed_001);
  strategy3 by-id vector characteristic mismatch x state_points_query_001
  (byid_dim_001); state by-id missing-point x state_points_query_001
  (byid_stale_001); strategy1 query-absent id-order x
  behavioral_points_query_004 (noid_order_001); strategy1 exact=true
  pagination stability x behavioral_points_query_003 (offset_exact_001);
  strategy6 huge-offset resource x behavioral_points_query_002
  (offset_huge_001)]
Oracle: Amin/Amax -> 200 with a non-empty points array (4xx on an in-range
  documented value = Type1_IllegalSuccess); Aunder/Aover on a LIVE nesting
  -> 400 or 422 (200 = Type1_IllegalSuccess: [0.0,1.0] promise violated);
  probes that return 200 = silent-drop evidence (reported, NOT a defect
  claim); 5xx with /healthz alive = Type3_RuntimeFailure; transport
  failure -> /healthz re-check then SCRIPT_ERROR (constraint
  qdrant_range_points_query_002).
Constraint: qdrant_range_points_query_002 (bare id) — "SearchParams:
  hnsw_ef minimum 1; acorn_scale within [0.0, 1.0] (default 0.4)"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query        -> POST /collections/{collection_name}/points/query
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
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
N_SEED = 6
V = [0.5, 0.25, 0.125, 0.0625]


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/consistency) via params= — never stuffed into the body.
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
    """Inline liveness probe on the lightweight healthz face."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def extract_points(body):
    """
    Locate the ScoredPoint array in the QueryResponse envelope.
    Contract response_shape: result (object) -> result.points (array).
    A legacy list-form result is tolerated and reported (shape oracles
    cross-checked against the published OpenAPI — standing lesson).
    """
    if not isinstance(body, dict):
        return None, "body-not-dict"
    result = body.get("result")
    if isinstance(result, dict):
        pts = result.get("points")
        return (pts if isinstance(pts, list) else None), "result.points"
    if isinstance(result, list):
        return result, "result-array-observed"
    return None, "result-missing"


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqA1" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{"id": i, "vector": [v * (1.0 + i / 100.0) for v in V]} for i in range(1, N_SEED + 1)]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        base_body = {"query": {"nearest": V}, "limit": 3}

        # ---- Existence probes: does either nesting react to a wrong type? ----
        live_forms = []  # list of (label, builder)
        for plabel, pbody in (
            ("probeN nested {'acorn': {'acorn_scale': '0.4'}}",
             dict(base_body, params={"acorn": {"acorn_scale": "0.4"}})),
            ("probeF flat {'acorn_scale': '0.4'}",
             dict(base_body, params={"acorn_scale": "0.4"})),
        ):
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                     json=pbody, timeout=60)
            print(f"\n{plabel} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, _, _ = healthz_alive()
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                      "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {plabel}: type-confusion "
                          f"probe returned {s} with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s in (400, 422):
                print(f"{plabel}: LIVE (clean {s} serde/validation error)")
                if plabel.startswith("probeN"):
                    live_forms.append(("nested", lambda sc: {"acorn": {"acorn_scale": sc}}))
                else:
                    live_forms.append(("flat", lambda sc: {"acorn_scale": sc}))
            elif s == 200:
                print(f"{plabel}: silent-drop suspect (string accepted with 200 — sub-key "
                      f"not validated at this nesting)")
            else:
                print(f"VERDICT: SCRIPT_ERROR — unexpected probe status {s}; no defect conclusion")
                return

        if not live_forms:
            # Honest disposition per weaviate round-3 lesson: no live face ->
            # out-of-range acceptance is unadjudicable without effect evidence.
            print("\nOBSERVATION: neither documented acorn_scale nesting reacted to a "
                  "type-confusion probe (both 200) — SearchParams sub-keys are silently "
                  "dropped; the [0.0,1.0] range promise is UNADJUDICABLE on this face "
                  "(no persistence/readback). Raw evidence above is left for the judge; "
                  "no defect claimed by this script.")
            print("VERDICT: NO_DEFECT")
            return

        # ---- Range matrix on each live nesting ----
        for form_name, builder in live_forms:
            for label, sc, expect_ok in (
                (f"Amin[{form_name}] acorn_scale=0.0", 0.0, True),
                (f"Amax[{form_name}] acorn_scale=1.0", 1.0, True),
                (f"Aunder[{form_name}] acorn_scale=-0.01", -0.01, False),
                (f"Aover[{form_name}] acorn_scale=1.01", 1.01, False),
            ):
                s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                         json=dict(base_body, params=builder(sc)), timeout=60)
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
                        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: "
                              f"acorn_scale probe returned {s} with service alive: {raw[:300]}")
                    else:
                        print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                    return
                if expect_ok:
                    pts_a, shape = extract_points(b)
                    if s != 200 or pts_a is None:
                        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: "
                              f"in-range documented value rejected/malformed with {s}: {raw[:300]}")
                        return
                    if len(pts_a) < 1:
                        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg "
                              f"[{label}]: {N_SEED} seeded points, limit=3, got 0 points: {raw[:300]}")
                        return
                    print(f"leg {label} OK: 200 with {len(pts_a)} points (envelope {shape})")
                else:
                    if s == 200:
                        n = len(extract_points(b)[0] or [])
                        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: "
                              f"contract asserts acorn_scale within [0.0, 1.0] and this nesting "
                              f"is LIVE (probe 4xxed), yet the out-of-range value was ACCEPTED "
                              f"with 200 ({n} points): {raw[:300]}")
                        return
                    if s not in (400, 422):
                        print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                        return
                    named = "acorn" in raw.lower()
                    print(f"leg {label} OK: rejected with {s} (error names 'acorn': {named})")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
