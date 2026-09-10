#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_batch_presence_006
# strategy: strategy2 presence/optionality matrix on per-entry target/context
#           (both are optional per contract parameters; the discover grammar
#           is target XOR context — the batch face re-tests the matrix and
#           the XOR edge both-present / neither-present)
# endpoint: points+discover+batch
# constraint_ids: qdrant_behavioral_points_discover_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust / presence optimism — the
#            per-entry dispatcher could accept an entry with NEITHER target
#            nor context (undefined discovery basis) or with BOTH (ambiguous
#            precedence) instead of rejecting; the single-discover face was
#            covered in R36 — this is the batch-entry re-test, same family
#            disposition compared for interface parity)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 presence matrix x
  qdrant_behavioral_points_discover_batch_001 — per-entry target/context
  presence faces, each as a single-entry batch (attribution stays clean):
    P1 target-only, point-id form   {"target": 1, "limit": 3}
    P2 target-only, vector form     {"target": [0.1]*4, "limit": 3}
    P3 context-only                 {"context": [pair], "limit": 3}
    P4 BOTH target AND context      — judge-call face: the discover grammar
       is target XOR context; a clean 400 (exactly-one-of enforced) or a
       200 with a valid array (documented precedence) are both defensible;
       recorded for the judge (parity with the single face matters more
       than the disposition itself — G9 same-family consistency).
    P5 NEITHER (only limit)         — judge-call face: same frame.
    P6 empty entry {}               — expected 400/422 (limit is the one
       required per-entry field per request_required_paths
       "searches[].limit"; absence plus no basis at all).
  [chunk_points+discover+batch coverage: strategy2 target/context presence
  matrix x qdrant_behavioral_points_discover_batch_001 (this script;
  positive in boundary_points_discover_batch_positive_001, wrapper confusion
  in boundary_points_discover_batch_searches_type_002, context/pairs in
  boundary_points_discover_batch_context_type_003, 404 leg in
  boundary_points_discover_batch_404_004, limit matrix in
  boundary_points_discover_batch_limit_005, sparse-target shape in
  boundary_points_discover_batch_sparse_target_007, malformed stream in
  boundary_points_discover_batch_malformed_008, resource/batch-size in
  boundary_points_discover_batch_resource_009)]
Oracle: P1/P2/P3 -> 200 array-of-arrays outer 1 inner 1..3 (valid faces;
  non-200 = valid batch rejected, Type1 convention; wrong shape = Type4);
  P4/P5 -> 400/422 or 200-with-valid-array (both recorded for the judge;
  200 with non-array-of-arrays result = Type4); P6 -> 400/422 (2xx =
  Type1_IllegalSuccess: required searches[].limit absent yet accepted);
  5xx with /healthz alive = Type3_RuntimeFailure; transport failure ->
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
PAIR = [{"positive": 1, "negative": 4}]

# (label, entry dict, expectation kind: "pos" | "judge" | "rej")
FACES = [
    ("P1 target-only (point id)", {"target": 1, "limit": 3}, "pos"),
    ("P2 target-only (vector)", {"target": [0.1] * DIM, "limit": 3}, "pos"),
    ("P3 context-only", {"context": [dict(p) for p in PAIR], "limit": 3}, "pos"),
    ("P4 BOTH target AND context",
     {"target": 1, "context": [dict(p) for p in PAIR], "limit": 3}, "judge"),
    ("P5 NEITHER (limit only)", {"limit": 3}, "judge"),
    ("P6 empty entry {}", {}, "rej"),
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
    coll = "bpdwb6" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        for label, entry, expect in FACES:
            s, body, raw = discover_batch(coll, {"searches": [entry]})
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
                          f"returned {s}: {raw[:300]}")
                else:
                    print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
                return
            res = body.get("result") if isinstance(body, dict) else None
            good_shape = (isinstance(res, list) and len(res) == 1
                          and isinstance(res[0], list) and 1 <= len(res[0]) <= 3)

            if expect == "pos":
                if not (200 <= s <= 299):
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"valid presence face rejected with {s} (promise: "
                          f"HTTP 200): {raw[:300]}")
                    return
                if not good_shape:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"{label}: 200 but result not array-of-arrays outer 1 "
                          f"inner 1..3: {raw[:300]}")
                    return
                print(f"{label}: 200, inner len={len(res[0])} (valid face upheld)")

            elif expect == "rej":
                if 200 <= s <= 299:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"entry with NO fields at all ACCEPTED with status "
                          f"{s} (searches[].limit is required per "
                          f"request_required_paths): {raw[:300]}")
                    return
                if s in (400, 422):
                    low = raw.lower()
                    named = any(t in low for t in ("limit", "target", "context",
                                                   "required", "missing"))
                    note = ("diagnostics name the missing construct"
                            if named else
                            "NOTE (strategy5): rejection text names no "
                            "presence-family token — diagnostics gap recorded "
                            "for the judge")
                    print(f"{label}: {s} clean rejection; {note}")
                else:
                    print(f"NOTE: {label} returned {s}; recorded for the judge")

            else:  # judge faces P4/P5
                if 200 <= s <= 299:
                    if not good_shape:
                        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                              f"{label}: 200 but result not array-of-arrays "
                              f"outer 1 inner 1..3: {raw[:300]}")
                        return
                    print(f"{label}: judge-call face — accepted with a valid "
                          f"result array (len={len(res[0])}); recorded for the "
                          f"judge (XOR/precedence semantics; compare with the "
                          f"single-discover disposition for family parity)")
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
