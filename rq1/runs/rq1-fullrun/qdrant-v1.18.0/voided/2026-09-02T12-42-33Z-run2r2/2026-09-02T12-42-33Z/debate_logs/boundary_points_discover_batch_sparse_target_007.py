#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_batch_sparse_target_007
# strategy: strategy3 vector-shape mismatch on the sparse target inside batch
#           entries (sparse analog of the dimension attack: indices/values
#           cardinality, uint domain, member types, dense-vs-sparse channel
#           confusion) + strategy4 special values + the batch atomicity face
# endpoint: points+discover+batch
# constraint_ids: qdrant_behavioral_points_discover_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — contract data_types
#            declares Sparse vector as {indices: [uint], values: [float]}
#            with distance always Dot; request_required_paths carries
#            target.indices AND target.values for the sparse branch; the
#            batch face adds a dispatcher-level skip risk: a bad entry
#            silently dropped breaks one-result-array-per-query alignment)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy3/4 sparse-target shape x
  qdrant_behavioral_points_discover_batch_001 — the sparse query vector
  structure (request_required_paths branch target.indices + target.values;
  data_types "{indices: [uint], values: [float]}") is attacked per-entry on
  a live sparse+dense seeded collection (mirror of the R36 single-face
  family, batch-variant re-test):
    G  guard: VALID sparse target + using="text" -> 200,
       array-of-arrays outer 1, inner 1..3 (sparse channel live; G4).
    S1 cardinality mismatch: indices [1,2,3] with values [0.5,0.5]
    S2 uint-domain violation: indices [-1] with values [0.5]
    S3 member type confusion: indices ["1","2"] with values [0.5,0.5]
    S4 empty sparse vector {indices:[], values:[]} — judge-call face:
       structurally representable; 400/422 or 200-with-valid-array are
       both defensible.
    S5 dense-array target on the sparse channel: [0.1,0.2,0.3,0.4] with
       using="text" (the named dense vector "dense" exists, so the
       mismatch is purely channel-vs-shape)
    U1 using-selector mismatch: valid sparse target with using="nope"
    M1 mixed atomicity: searches = [valid sparse entry, S1-shaped entry]
       -> whole batch must 400; 200 with TWO arrays = Type1; 200 with ONE
       array = Type4 (silent skip — alignment contract broken).
  [chunk_points+discover+batch coverage: strategy3/4 sparse-target shape +
  mixed-batch atomicity x qdrant_behavioral_points_discover_batch_001
  (this script; positive in boundary_points_discover_batch_positive_001,
  wrapper confusion in boundary_points_discover_batch_searches_type_002,
  context/pairs in boundary_points_discover_batch_context_type_003, 404 leg
  in boundary_points_discover_batch_404_004, limit matrix in
  boundary_points_discover_batch_limit_005, presence in
  boundary_points_discover_batch_presence_006, malformed stream in
  boundary_points_discover_batch_malformed_008, resource/batch-size in
  boundary_points_discover_batch_resource_009)]
Oracle: G -> 200 array-of-arrays outer 1 inner 1..3 (non-200 = valid batch
  rejected, Type1 convention per session; wrong shape = Type4); S1/S2/S3/S5/U1
  -> 400/422 clean rejection (any 2xx = Type1_IllegalSuccess: malformed
  sparse target accepted inside a batch entry); S4 -> 400/422 or
  200-with-valid-array (both NO_DEFECT; 2xx with a NON-array result =
  Type4); M1 -> 400/422 whole-batch rejection (200 with outer len 2 =
  Type1; outer len 1 = Type4 silent skip; other = Type4); 5xx with
  /healthz alive = Type3_RuntimeFailure; transport failure -> /healthz
  liveness re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_discover_batch_001).
Constraint: qdrant_behavioral_points_discover_batch_001 (bare id) — "returns
  200 [ScoredPoint]; 400 on invalid context/pairs; 404 for a missing
  collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+discover+batch -> POST /collections/{collection_name}/points/discover/batch
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

# (label, using-override or None, target value, expectation kind: pos|rej|judge)
FACES = [
    ("G valid sparse target", None, GOOD_TARGET, "pos"),
    ("S1 cardinality mismatch", None,
     {"indices": [1, 2, 3], "values": [0.5, 0.5]}, "rej"),
    ("S2 negative index (uint domain)", None,
     {"indices": [-1], "values": [0.5]}, "rej"),
    ("S3 indices as STRINGS", None,
     {"indices": ["1", "2"], "values": [0.5, 0.5]}, "rej"),
    ("S4 empty sparse vector", None,
     {"indices": [], "values": []}, "judge"),
    ("S5 dense array on sparse channel", None,
     [0.1, 0.2, 0.3, 0.4], "rej"),
    ("U1 using=nonexistent name", "nope", GOOD_TARGET, "rej"),
]


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
    """Inline liveness probe on the lightweight healthz face."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


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


def discover_batch(coll, body):
    return safe_request("POST", f"/collections/{coll}/points/discover/batch",
                        json=body, timeout=60)


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdwb7" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        for label, using_override, target, expect in FACES:
            using = using_override if using_override is not None else SPARSE_NAME
            body_ = {"searches": [{"using": using, "target": target, "limit": 3}]}
            s, body, raw = discover_batch(coll, body_)
            print(f"\n{label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, hs, hraw = healthz_alive()
                print(f"transport failure on {label} (healthz status={hs}: {hraw})")
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                          f"discover/batch returned {s}: {raw[:300]}")
                else:
                    print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
                return
            res = body.get("result") if isinstance(body, dict) else None
            good_shape = (isinstance(res, list) and len(res) == 1
                          and isinstance(res[0], list))

            if expect == "pos":
                if not (200 <= s <= 299):
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"valid sparse batch rejected with {s} (promise: "
                          f"HTTP 200): {raw[:300]}")
                    return
                if not good_shape or not (1 <= len(res[0]) <= 3):
                    got = len(res[0]) if good_shape else "non-array"
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"{label}: 200 but result outer/inner shape wrong "
                          f"({got}): {raw[:300]}")
                    return
                print(f"{label}: 200, inner len={len(res[0])} (sparse channel live)")

            elif expect == "rej":
                if 200 <= s <= 299:
                    got = len(res[0]) if good_shape else "non-array"
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"malformed sparse target ACCEPTED inside batch entry "
                          f"with status {s} (inner {got}; expected 400/422 "
                          f"clean rejection): {raw[:300]}")
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
                          f"recorded for the judge")

            else:  # judge-call face S4
                if 200 <= s <= 299:
                    if not good_shape:
                        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                              f"{label}: 200 but result is not array-of-arrays "
                              f"outer 1 (response_shape: result[] array): "
                              f"{raw[:300]}")
                        return
                    print(f"{label}: judge-call face — accepted with a valid "
                          f"result array (len={len(res[0])}); recorded for the "
                          f"judge (empty sparse vector semantics)")
                elif s in (400, 422):
                    print(f"{label}: judge-call face — {s} clean rejection; "
                          f"recorded for the judge")
                else:
                    print(f"NOTE: {label} returned {s}; recorded for the judge")

        # M1 mixed atomicity: valid sparse entry + cardinality-mismatch entry
        mixed = {"searches": [
            {"using": SPARSE_NAME, "target": dict(GOOD_TARGET), "limit": 2},
            {"using": SPARSE_NAME,
             "target": {"indices": [1, 2, 3], "values": [0.5, 0.5]}, "limit": 2},
        ]}
        s, body, raw = discover_batch(coll, mixed)
        print(f"\nM1 mixed batch (valid sparse + cardinality mismatch) -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on M1 (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — M1 "
                      f"returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — M1 5xx and healthz down")
            return
        if s in (400, 422):
            print("M1: whole-batch clean rejection (atomic 400) — alignment "
                  "contract upheld")
        elif 200 <= s <= 299:
            res = body.get("result") if isinstance(body, dict) else None
            n_out = len(res) if isinstance(res, list) else "non-array"
            if n_out == 2:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — M1: "
                      f"cardinality-mismatch entry ACCEPTED inside a mixed "
                      f"batch (status {s}, 2 result arrays out; expected "
                      f"whole-batch 400): {raw[:300]}")
                return
            if n_out == 1:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M1: "
                      f"silent skip: 2 queries in, 1 result array out "
                      f"(alignment contract: one result array per query, in "
                      f"order): {raw[:300]}")
                return
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M1: "
                  f"200 with outer result {n_out} for a 2-query batch: "
                  f"{raw[:300]}")
            return
        else:
            print(f"NOTE: M1 returned {s}; recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
