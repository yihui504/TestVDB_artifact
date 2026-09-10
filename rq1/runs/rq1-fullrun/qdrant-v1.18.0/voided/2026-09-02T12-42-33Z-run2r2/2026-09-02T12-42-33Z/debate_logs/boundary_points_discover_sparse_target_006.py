#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_sparse_target_006
# strategy: strategy3 vector-shape mismatch (sparse analog of the dimension
#           attack: indices/values cardinality, uint domain, member types,
#           dense-vs-sparse channel confusion) + strategy4 special values,
#           plus one using-selector mismatch face — the 400 leg of the
#           endpoint promise on the sparse target structure
# endpoint: points+discover
# constraint_ids: qdrant_behavioral_points_discover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — contract data_types
#            declares Sparse vector as {indices: [uint], values: [float]}
#            with distance always Dot; request_required_paths carries
#            target.indices AND target.values for the sparse branch; serde
#            gaps could accept mismatched cardinalities, signed/negative
#            indices, string members or a dense array on the sparse channel)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy3/4 sparse-target shape x qdrant_behavioral_points_discover_001 —
  the sparse query vector structure (request_required_paths branch
  target.indices + target.values; data_types "{indices: [uint],
  values: [float]}") is attacked on a live sparse+dense seeded collection:
    G  guard: VALID sparse target + using="text" -> 200, result array 1..3
       (proves the sparse channel live before any 400 is trusted).
    S1 cardinality mismatch: indices [1,2,3] with values [0.5,0.5]
       -> 400/422 clean; 2xx = Type1_IllegalSuccess.
    S2 uint-domain violation: indices [-1] with values [0.5]
       -> 400/422 clean; 2xx = Type1_IllegalSuccess.
    S3 member type confusion: indices ["1","2"] with values [0.5,0.5]
       -> 400/422 clean; 2xx = Type1_IllegalSuccess.
    S4 empty sparse vector {indices:[], values:[]} — judge-call face:
       400/422 (validation) or 200 with a valid result array are both
       defensible (an empty sparse vector is structurally representable);
       5xx = Type3; anything else recorded for the judge.
    S5 dense-array target on the sparse channel: target=[0.1,0.2,0.3,0.4]
       with using="text" (the named dense vector "dense" exists, so the
       mismatch is purely channel-vs-shape) -> 400/422 clean;
       2xx = Type1_IllegalSuccess.
    U1 using-selector mismatch: valid sparse target with using="nope"
       (no such vector name in the collection) -> 400/422 clean;
       2xx = Type1_IllegalSuccess.
  [chunk_points+discover coverage: strategy3/4 sparse-target shape x
  qdrant_behavioral_points_discover_001 (this script; positive/shape in
  boundary_points_discover_positive_001, context type-confusion in
  boundary_points_discover_context_type_002, 404 leg in
  boundary_points_discover_404_003, limit matrix in
  boundary_points_discover_limit_004, presence matrix in
  boundary_points_discover_presence_005, filter family mirror in
  boundary_points_discover_filter_type_007, malformed stream in
  boundary_points_discover_malformed_008)]
Oracle: G -> 200 result array 1..3 (non-200 = valid discover rejected,
  Type1 convention per session; wrong length/shape = Type4); S1/S2/S3/S5/U1
  -> 400/422 clean rejection (any 2xx = Type1_IllegalSuccess: malformed
  sparse target accepted); S4 -> 400/422 or 200-with-valid-array (both
  NO_DEFECT; 2xx with a NON-array result = Type4); 5xx with /healthz alive
  = Type3_RuntimeFailure; transport failure -> /healthz liveness re-check
  then SCRIPT_ERROR (constraint qdrant_behavioral_points_discover_001).
Constraint: qdrant_behavioral_points_discover_001 (bare id) — "returns 200
  [ScoredPoint]; 400 on invalid context/pairs; 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+discover       -> POST /collections/{collection_name}/points/discover
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
GOOD_TARGET = {"indices": [1, 2, 3], "values": [1.0, 1.0, 1.0]}

# (label, using-override or None, target value, expectation kind)
# kind "pos" = valid -> 200 array; "rej" = 400/422; "judge" = dual-accept face
FACES = [
    ("G valid sparse target", None, GOOD_TARGET, ("pos",)),
    ("S1 cardinality mismatch", None,
     {"indices": [1, 2, 3], "values": [0.5, 0.5]}, ("rej",)),
    ("S2 negative index (uint domain)", None,
     {"indices": [-1], "values": [0.5]}, ("rej",)),
    ("S3 indices as STRINGS", None,
     {"indices": ["1", "2"], "values": [0.5, 0.5]}, ("rej",)),
    ("S4 empty sparse vector", None,
     {"indices": [], "values": []}, ("judge",)),
    ("S5 dense array on sparse channel", None,
     [0.1, 0.2, 0.3, 0.4], ("rej",)),
    ("U1 using=nonexistent name", "nope", GOOD_TARGET, ("rej",)),
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


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdw6" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        for label, using_override, target, expect in FACES:
            using = using_override if using_override is not None else SPARSE_NAME
            body_ = {"using": using, "target": target, "limit": 3}
            s, body, raw = discover(coll, body_)
            print(f"\n{label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                transport_dead(label)
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                          f"discover returned {s}: {raw[:300]}")
                else:
                    print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
                return
            res = body.get("result") if isinstance(body, dict) else None
            is_arr = isinstance(res, list)

            if expect[0] == "pos":
                if not (200 <= s <= 299):
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"valid sparse discover rejected with {s} (promise: "
                          f"HTTP 200): {raw[:300]}")
                    return
                if not is_arr or not (1 <= len(res) <= 3):
                    got = len(res) if is_arr else "non-array"
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"{label}: 200 but result {got} outside [1, 3]: "
                          f"{raw[:300]}")
                    return
                print(f"{label}: 200, result array len={len(res)} (sparse channel live)")

            elif expect[0] == "rej":
                if 200 <= s <= 299:
                    got = len(res) if is_arr else "non-array"
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"malformed sparse target ACCEPTED with status {s} "
                          f"(result length {got}; expected 400/422 clean "
                          f"rejection): {raw[:300]}")
                    return
                if s in (400, 422):
                    low = raw.lower()
                    named = any(t in low for t in ("indices", "values", "vector",
                                                   "target", "using", "dimension"))
                    note = ("diagnostics name the vector construct"
                            if named else
                            "NOTE (strategy5): rejection text names no "
                            "vector-family token — diagnostics gap recorded "
                            "for the judge")
                    print(f"{label}: {s} clean rejection; {note}")
                else:
                    print(f"NOTE: {label} returned {s} (neither 2xx nor 400/422); "
                          f"recorded for the judge — unexpected rejection class")

            else:  # judge-call dual-accept face
                if 200 <= s <= 299:
                    if not is_arr:
                        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                              f"{label}: 200 but result is not an array "
                              f"(response_shape: result array): {raw[:300]}")
                        return
                    print(f"{label}: judge-call face — accepted with a valid "
                          f"result array (len={len(res)}); recorded for the "
                          f"judge (empty sparse vector semantics)")
                elif s in (400, 422):
                    print(f"{label}: judge-call face — {s} clean rejection; "
                          f"recorded for the judge")
                else:
                    print(f"NOTE: {label} returned {s}; recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
