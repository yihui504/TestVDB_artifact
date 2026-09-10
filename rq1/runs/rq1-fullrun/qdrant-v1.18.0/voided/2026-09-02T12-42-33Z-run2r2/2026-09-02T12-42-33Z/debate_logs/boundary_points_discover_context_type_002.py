#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_context_type_002
# strategy: strategy2 type-boundary attack (the "400 on invalid context/pairs"
#           leg of the endpoint promise; BS-01 type-coercion faces on the
#           context array and its pair members, each with an exact-count state
#           guard separating silent no-op acceptance from real read activity)
# endpoint: points+discover
# constraint_ids: qdrant_behavioral_points_discover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the spec declares context
#            as array[{positive,negative}]; serde coercion gaps could let a
#            string/object context, an int clause, a null example or an
#            array-shaped pair through with 200 and undefined discovery
#            semantics). R35 family note: the same grammar class was
#            destructive on points+delete (matcher-less conditions); here the
#            face is READ-ONLY, so acceptance is non-destructive Type1 and the
#            same-family disposition (count R34 NOT / delete R35 DEFECT /
#            discover = read-only member) is the adjudication frame.
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-confusion x qdrant_behavioral_points_discover_001 — the
  "400 on invalid context/pairs" leg is attacked with five type-confused
  context bodies (contract parameter spec: context = array[{positive,
  negative}]), each sent WITH a valid sparse target so the only invalid part
  is the context construct under test:
    G  guard: VALID context pair [{"positive": 1, "negative": 4}] + sparse
       target, using="text", limit=3 -> 200, result array 1..3 elements —
       proves the discover path live before any 400 is trusted (G4 pairing).
    T1 context as STRING          "text"
    T2 context as OBJECT          {"positive": 1, "negative": 4}  (unwrapped)
    T3 pair-less pair             [{}]                             (R35 analog)
    T4 null example               [{"positive": null, "negative": 4}]
    T5 pair as ARRAY              [[]]
  Each invalid face: expected 400/422 clean rejection (promise: 400). 2xx =
  invalid context ACCEPTED (Type1_IllegalSuccess — non-destructive read-only
  face; count guard certifies the substrate was untouched). 5xx = Type3.
  Rejection text scanned for context-family tokens (strategy 5 diagnostics
  note for the judge, not a standalone defect per session convention).
  [chunk_points+discover coverage: strategy2 context/pairs type-confusion x
  qdrant_behavioral_points_discover_001 (this script; positive/shape in
  boundary_points_discover_positive_001, 404 leg in
  boundary_points_discover_404_003, limit matrix in
  boundary_points_discover_limit_004, presence matrix in
  boundary_points_discover_presence_005, sparse-target shape in
  boundary_points_discover_sparse_target_006, filter family mirror in
  boundary_points_discover_filter_type_007, malformed stream in
  boundary_points_discover_malformed_008)]
Oracle: T1..T5 -> 400/422 clean rejection (any 2xx = Type1_IllegalSuccess:
  invalid context accepted; the acceptance is non-destructive by construction
  — certified by exact count == 9 before/after; 5xx with /healthz alive =
  Type3_RuntimeFailure); G -> 200 with result array 1..3 elements (other =
  Type4; non-200 = valid discover rejected, Type1 convention per session);
  transport failure -> /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_discover_001).
Constraint: qdrant_behavioral_points_discover_001 (bare id) — "returns 200
  [ScoredPoint]; 400 on invalid context/pairs; 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+discover       -> POST /collections/{collection_name}/points/discover
  points+count          -> POST /collections/{collection_name}/points/count
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
  points+upsert         -> PUT  /collections/{collection_name}/points
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
N_SEED = 9
RED_N = 3
SPARSE_NAME = "text"
DENSE_NAME = "dense"
GUARD_TARGET = {"indices": [1, 2, 3], "values": [1.0, 1.0, 1.0]}
GUARD_CONTEXT = [{"positive": 1, "negative": 4}]

# (label, invalid context value, context-family tokens expected in diagnostics)
FACES = [
    ("T1 context as STRING", "text"),
    ("T2 context as OBJECT", {"positive": 1, "negative": 4}),
    ("T3 pair-less pair [{}]", [{}]),
    ("T4 null example", [{"positive": None, "negative": 4}]),
    ("T5 pair as ARRAY", [[]]),
]


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/ordering/timeout) via params= — never stuffed into the body.
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


def transport_dead(where):
    """Transport-branch liveness re-check (lightweight healthz face only)."""
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return False


def sparse_vec(i):
    """Sparse vector per cluster: red over indices 1..3, blue over 4..6."""
    if i <= RED_N:
        return {"indices": [1, 2, 3], "values": [round(0.9 + 0.02 * i, 3), 0.8, 0.7]}
    return {"indices": [4, 5, 6], "values": [round(0.9 - 0.01 * i, 3), 0.85, 0.6]}


def dense_vec(i):
    """Dense vector per cluster (Cosine; absolute scores are never asserted)."""
    base = 0.1 if i <= RED_N else 0.9
    return [round(base + 0.001 * i, 4)] * DIM


def setup(coll):
    """Own collection: named dense vector + named sparse vector + 9 points."""
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {DENSE_NAME: {"size": DIM, "distance": "Cosine"}},
                                   "sparse_vectors": {SPARSE_NAME: {}}}, timeout=60)
    if s not in (200, 201):
        return False, raw
    pts = []
    for i in range(1, N_SEED + 1):
        pts.append({"id": i,
                    "vector": {DENSE_NAME: dense_vec(i), SPARSE_NAME: sparse_vec(i)},
                    "payload": {"grp": "red" if i <= RED_N else "blue"}})
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": pts}, params={"wait": "true"}, timeout=120)
    if s not in (200, 201):
        return False, raw
    return True, ""


def discover(coll, body):
    """points+discover face."""
    return safe_request("POST", f"/collections/{coll}/points/discover",
                        json=body, timeout=60)


def exact_count(coll):
    """Exact count via the points+count face (result.count integer per shape)."""
    s, body, raw = safe_request("POST", f"/collections/{coll}/points/count",
                                json={"exact": True}, timeout=60)
    if s == -1 or not (200 <= s <= 299):
        return None, s, raw
    result = body.get("result") if isinstance(body, dict) else None
    got = result.get("count") if isinstance(result, dict) else None
    return got, s, raw


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdw2" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        cnt, cs, craw = exact_count(coll)
        if cnt != N_SEED:
            print(f"seed count = {cnt} (status={cs}), expected {N_SEED}: {str(craw)[:200]}")
            print("VERDICT: SCRIPT_ERROR — setup baseline mismatch")
            return
        print(f"seed baseline: exact count == {N_SEED}")

        # ---- G: guard — VALID context pair + sparse target -> 200, 1..3 ----
        gbody = {"using": SPARSE_NAME, "target": GUARD_TARGET,
                 "context": GUARD_CONTEXT, "limit": 3}
        s, body, raw = discover(coll, gbody)
        print(f"\nG guard valid context -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            transport_dead("G guard")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — G: valid "
                      f"discover returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — G 5xx and healthz down")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — G: valid "
                  f"discover rejected with {s} (promise: HTTP 200): {raw[:300]}")
            return
        res = body.get("result") if isinstance(body, dict) else None
        if not isinstance(res, list) or not (1 <= len(res) <= 3):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — G: 200 "
                  f"but result not an array of 1..3 (response_shape: result "
                  f"array): {raw[:300]}")
            return
        print(f"G: 200, result array len={len(res)} (guard live)")

        # ---- T1..T5: invalid context faces (valid target kept) ----
        for label, ctx in FACES:
            body_ = {"using": SPARSE_NAME, "target": GUARD_TARGET,
                     "context": ctx, "limit": 3}
            s, _, raw = discover(coll, body_)
            print(f"\n{label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                transport_dead(label)
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                          f"invalid context crashed the endpoint with {s}: {raw[:300]}")
                else:
                    print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
                return
            if 200 <= s <= 299:
                cnt2, _, _ = exact_count(coll)
                blast = ("substrate untouched (read-only silent acceptance)"
                         if cnt2 == N_SEED else
                         f"UNEXPECTED state change: count {N_SEED} -> {cnt2}")
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"invalid context ACCEPTED with status {s} (promise: 400); "
                      f"read-only face so acceptance is non-destructive; "
                      f"count guard: {blast}: {raw[:300]}")
                return
            if s in (400, 422):
                low = raw.lower()
                named = any(t in low for t in ("context", "pair", "positive",
                                               "negative", "example", "condition"))
                note = ("diagnostics name the context construct"
                        if named else
                        "NOTE (strategy5): rejection text names no context-family "
                        "token — diagnostics gap recorded for the judge")
                print(f"{label}: {s} clean rejection; {note}")
            else:
                print(f"NOTE: {label} returned {s} (neither 2xx nor 400/422); "
                      f"recorded for the judge — unexpected rejection class")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
