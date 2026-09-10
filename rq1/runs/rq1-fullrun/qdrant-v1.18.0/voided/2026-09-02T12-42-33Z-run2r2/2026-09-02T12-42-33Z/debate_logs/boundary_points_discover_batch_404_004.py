#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_batch_404_004
# strategy: strategy1/2 contract-leg attack — the 404 leg of the endpoint
#           promise ("404 for a missing collection") on the batch face,
#           including the precedence face (missing collection + invalid
#           searches)
# endpoint: points+discover+batch
# constraint_ids: qdrant_behavioral_points_discover_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — a batch dispatcher that
#            routes per-entry could forget the collection-existence gate and
#            answer 200 with fabricated/empty arrays for a collection that
#            does not exist)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1/2 404-leg x qdrant_behavioral_points_discover_batch_001 —
  the "404 for a missing collection" leg is attacked on the batch face:
    G  guard: valid single-entry batch on an EXISTING collection -> 200,
       array-of-arrays outer len 1 (proves routing + channel live; G4).
    N1 missing collection + VALID searches -> 404 exactly (promise leg).
    N2 missing collection + INVALID searches ([{}]) -> precedence face:
       404 (existence gate first) or 400 (validation first) are both
       defensible dispositions — recorded for the judge; only a 2xx is a
       defect on either face (data invented for a nonexistent collection).
  [chunk_points+discover+batch coverage: 404 leg + routing precedence x
  qdrant_behavioral_points_discover_batch_001 (this script; positive in
  boundary_points_discover_batch_positive_001, wrapper confusion in
  boundary_points_discover_batch_searches_type_002, context/pairs+atomicity
  in boundary_points_discover_batch_context_type_003, limit matrix in
  boundary_points_discover_batch_limit_005, presence in
  boundary_points_discover_batch_presence_006, sparse-target shape in
  boundary_points_discover_batch_sparse_target_007, malformed stream in
  boundary_points_discover_batch_malformed_008, resource/batch-size in
  boundary_points_discover_batch_resource_009)]
Oracle: N1 -> 404 exactly (2xx = Type1_IllegalSuccess: results invented for
  a nonexistent collection; 400/422 on N1 = judge note — validation before
  the documented existence gate, contract-leg deviation recorded); N2 ->
  404 or 400/422 both NO_DEFECT (2xx = Type1); G -> 200 array-of-arrays
  outer len 1 inner 1..3 (other = Type4; non-200 = valid batch rejected,
  Type1 convention); 5xx with /healthz alive = Type3_RuntimeFailure;
  transport failure -> /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_discover_batch_001).
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
    coll = "bpdwb4" + tag
    ghost = "bpdwb4" + tag + "ghost"  # never created

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        valid_searches = {"searches": [{"target": 1, "limit": 3}]}

        # G guard on the existing collection
        s, body, raw = discover_batch(coll, valid_searches)
        print(f"G existing collection -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — guard "
                      f"returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        res = body.get("result") if isinstance(body, dict) else None
        if not (200 <= s <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — valid batch "
                  f"rejected with {s} (promise: HTTP 200): {raw[:300]}")
            return
        if not (isinstance(res, list) and len(res) == 1 and isinstance(res[0], list)
                and 1 <= len(res[0]) <= 3):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — guard: "
                  f"result not array-of-arrays outer 1 inner 1..3: {raw[:300]}")
            return
        print("G guard: batch channel live on the existing collection")

        # N1 missing collection + valid searches -> 404 exactly
        s, body, raw = discover_batch(ghost, valid_searches)
        print(f"\nN1 missing collection + valid searches -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on N1 (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — N1 "
                      f"returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — N1 5xx and healthz down")
            return
        if s == 404:
            low = raw.lower()
            named = any(t in low for t in ("not found", "collection", "doesn", "does not"))
            note = ("diagnostics name the collection"
                    if named else
                    "NOTE (strategy5): 404 text names no collection token — "
                    "diagnostics gap recorded for the judge")
            print(f"N1: 404 exactly as promised; {note}")
        elif 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — N1: 2xx "
                  f"({s}) for a collection that does not exist (promise: 404): "
                  f"{raw[:300]}")
            return
        elif s in (400, 422):
            print(f"NOTE: N1 returned {s} instead of the documented 404 — "
                  f"validation-before-existence deviation recorded for the "
                  f"judge (contract-leg deviation, not auto-defect)")
        else:
            print(f"NOTE: N1 returned {s}; recorded for the judge")

        # N2 missing collection + invalid searches -> precedence face
        s, body, raw = discover_batch(ghost, {"searches": [{}]})
        print(f"\nN2 missing collection + invalid searches -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on N2 (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — N2 "
                      f"returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — N2 5xx and healthz down")
            return
        if s in (404, 400, 422):
            print(f"N2: {s} (precedence face: {'existence gate first' if s == 404 else 'validation first'}); "
                  f"both dispositions defensible — recorded for the judge")
        elif 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — N2: 2xx "
                  f"({s}) on a nonexistent collection with an invalid batch: "
                  f"{raw[:300]}")
            return
        else:
            print(f"NOTE: N2 returned {s}; recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal (ghost was never created)


if __name__ == "__main__":
    main()
