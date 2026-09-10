#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_batch_searches_type_002
# strategy: strategy2 type-boundary attack on the batch wrapper parameter
#           "searches" (array[DiscoverRequest], required per contract
#           parameters AND request_required_paths) — wrapper-shape faces that
#           exist only on the batch face, not on the single discover face
# endpoint: points+discover+batch
# constraint_ids: qdrant_behavioral_points_discover_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde gaps could accept a
#            null/object/string/number wrapper or null/array-shaped entries
#            with 200 and undefined batch semantics; the wrapper is the one
#            construct the single-discover round could not exercise)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 wrapper type-confusion x
  qdrant_behavioral_points_discover_batch_001 — the searches wrapper
  (contract: searches = array[DiscoverRequest], required) is attacked with
  wrapper-shape faces, each isolated so the only invalid part is the wrapper
  construct under test:
    G  guard: VALID {"searches": [valid entry]} -> 200, result
       array-of-arrays, outer len 1, inner 1..3 (proves the batch path live
       before any 400 is trusted; G4 pairing).
    W1 wrapper missing      body {}                       (request_required_paths: searches)
    W2 wrapper null         {"searches": null}
    W3 wrapper as OBJECT    {"searches": {"target": 1, "limit": 3}}
    W4 wrapper as STRING    {"searches": "text"}
    W5 wrapper as NUMBER    {"searches": 42}
    W6 null ENTRY           {"searches": [null]}
    W7 array-shaped ENTRY   {"searches": [[]]}
    W8 empty wrapper        {"searches": []}   — judge-call face: an empty
       batch is structurally representable; 200 with result==[] OR 400/422
       are both defensible (recorded for the judge).
  [chunk_points+discover+batch coverage: strategy2 searches-wrapper
  type-confusion x qdrant_behavioral_points_discover_batch_001 (this script;
  positive/alignment in boundary_points_discover_batch_positive_001,
  context/pairs type-confusion+atomicity in
  boundary_points_discover_batch_context_type_003, 404 leg in
  boundary_points_discover_batch_404_004, limit matrix in
  boundary_points_discover_batch_limit_005, presence in
  boundary_points_discover_batch_presence_006, sparse-target shape in
  boundary_points_discover_batch_sparse_target_007, malformed stream in
  boundary_points_discover_batch_malformed_008, resource/batch-size in
  boundary_points_discover_batch_resource_009)]
Oracle: W1..W7 -> 400/422 clean rejection (any 2xx = Type1_IllegalSuccess:
  malformed searches wrapper accepted — envelope on such 2xx must still be
  array-of-arrays, else Type4; 5xx with /healthz alive = Type3_RuntimeFailure);
  W8 -> 200 with result==[] or 400/422 (both NO_DEFECT; 200 with a NON-array
  result or a NON-empty result = Type4: zero queries cannot produce hits);
  G -> 200 array-of-arrays outer len 1 inner 1..3 (other = Type4; non-200 =
  valid batch rejected, Type1 convention per session); transport failure ->
  /healthz liveness re-check then SCRIPT_ERROR (constraint
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
VALID_ENTRY = {"target": 1, "limit": 3}

# (label, full request body, expectation kind: "pos" | "rej" | "judge")
FACES = [
    ("G valid single-entry batch", {"searches": [dict(VALID_ENTRY)]}, "pos"),
    ("W1 wrapper missing", {}, "rej"),
    ("W2 wrapper null", {"searches": None}, "rej"),
    ("W3 wrapper as OBJECT", {"searches": {"target": 1, "limit": 3}}, "rej"),
    ("W4 wrapper as STRING", {"searches": "text"}, "rej"),
    ("W5 wrapper as NUMBER", {"searches": 42}, "rej"),
    ("W6 null ENTRY", {"searches": [None]}, "rej"),
    ("W7 array-shaped ENTRY", {"searches": [[]]}, "rej"),
    ("W8 empty wrapper []", {"searches": []}, "judge"),
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


def dense_vec(i):
    base = 0.1 if i <= RED_N else 0.9
    return [round(base + 0.001 * i, 4)] * DIM


def setup(coll):
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}},
                             timeout=60)
    if s not in (200, 201):
        return False, raw
    pts = [{"id": i, "vector": dense_vec(i),
            "payload": {"grp": "red" if i <= RED_N else "blue"}}
           for i in range(1, N_SEED + 1)]
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": pts}, params={"wait": "true"},
                             timeout=120)
    if s not in (200, 201):
        return False, raw
    return True, ""


def discover_batch(coll, body):
    return safe_request("POST", f"/collections/{coll}/points/discover/batch",
                        json=body, timeout=60)


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdwb2" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        for label, body_, expect in FACES:
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
            is_arr_of_arr = (isinstance(res, list) and
                             all(isinstance(r, list) for r in res))

            if expect == "pos":
                if not (200 <= s <= 299):
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"valid batch rejected with {s} (promise: HTTP 200): "
                          f"{raw[:300]}")
                    return
                if not is_arr_of_arr or len(res) != 1 or not (1 <= len(res[0]) <= 3):
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"{label}: 200 but result not array-of-arrays len 1 "
                          f"with inner 1..3 (response_shape result[]: array): "
                          f"{raw[:300]}")
                    return
                print(f"{label}: 200, outer len={len(res)}, inner len={len(res[0])} "
                      f"(batch channel live)")

            elif expect == "rej":
                if 200 <= s <= 299:
                    shape_note = ("array-of-arrays envelope intact"
                                  if is_arr_of_arr else
                                  "AND envelope is not array-of-arrays (Type4 "
                                  "compounding)")
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"malformed searches wrapper ACCEPTED with status {s} "
                          f"({shape_note}; expected 400/422 clean rejection): "
                          f"{raw[:300]}")
                    return
                if s in (400, 422):
                    low = raw.lower()
                    named = any(t in low for t in ("searches", "batch", "request",
                                                   "array", "entry", "discover"))
                    note = ("diagnostics name the wrapper construct"
                            if named else
                            "NOTE (strategy5): rejection text names no "
                            "wrapper-family token — diagnostics gap recorded "
                            "for the judge")
                    print(f"{label}: {s} clean rejection; {note}")
                else:
                    print(f"NOTE: {label} returned {s} (neither 2xx nor 400/422); "
                          f"recorded for the judge — unexpected rejection class")

            else:  # judge-call face (W8 empty wrapper)
                if 200 <= s <= 299:
                    if not isinstance(res, list):
                        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                              f"{label}: 200 but result is not an array "
                              f"(response_shape: result array): {raw[:300]}")
                        return
                    if len(res) != 0:
                        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                              f"{label}: 200 for ZERO queries but result has "
                              f"{len(res)} arrays (zero queries cannot produce "
                              f"hits): {raw[:300]}")
                        return
                    print(f"{label}: judge-call face — 200 with result==[] "
                          f"(empty-batch semantics); recorded for the judge")
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
