#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_batch_limit_005
# strategy: strategy1 boundary-value attack on searches[].limit (required per
#           contract request_required_paths "searches[].limit"; OpenAPI
#           minimum 1) + the batch atomicity face with a limit violator in
#           a mixed batch
# endpoint: points+discover+batch
# constraint_ids: qdrant_behavioral_points_discover_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — per-entry limit could be
#            clamped-to-default instead of validated inside a batch; and a
#            mixed batch could silently skip the violating entry, breaking
#            the one-result-array-per-query alignment)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 limit boundary matrix x
  qdrant_behavioral_points_discover_batch_001 — searches[].limit is the one
  required per-entry field (request_required_paths); the matrix below is
  run per-entry on the batch face (single-entry batches keep attribution
  clean), then the mixed-batch atomicity face:
    G  guard: limit=1 (min closure) -> 200, inner EXACTLY 1 (arithmetic:
       9 candidates, plain-index full scan below default
       indexing_threshold — boundary closure must be ACCEPTED).
    B1 limit=0        (min - 1)
    B2 limit=-1       (negative)
    B3 limit=-100     (deep negative)
    B4 limit missing  (required-path absence)
    B5 limit="3"      (string; type confusion)
    B6 limit=3.5      (float; type confusion)
    B7 limit=null     (explicit null)
    M1 mixed atomicity: searches = [{target,limit:2}, {target,limit:0}] ->
       whole batch must 400; 200 with TWO arrays = Type1 (limit=0 entry
       accepted); 200 with ONE array = Type4 (silent skip — alignment
       contract: one result array per query, in order).
  [chunk_points+discover+batch coverage: strategy1 searches[].limit matrix
  + mixed-batch atomicity x qdrant_behavioral_points_discover_batch_001
  (this script; positive in boundary_points_discover_batch_positive_001,
  wrapper confusion in boundary_points_discover_batch_searches_type_002,
  context/pairs in boundary_points_discover_batch_context_type_003, 404 leg
  in boundary_points_discover_batch_404_004, presence in
  boundary_points_discover_batch_presence_006, sparse-target shape in
  boundary_points_discover_batch_sparse_target_007, malformed stream in
  boundary_points_discover_batch_malformed_008, resource/batch-size in
  boundary_points_discover_batch_resource_009)]
Oracle: B1..B7 -> 400/422 clean rejection (any 2xx = Type1_IllegalSuccess:
  out-of-domain per-entry limit accepted; schema minimum is 1); G -> 200
  with inner array EXACTLY 1 (0 or >1 = Type4 count violation; non-200 =
  valid batch rejected, Type1 convention); M1 -> 400/422 whole-batch
  rejection (200 with outer len 2 = Type1; outer len 1 = Type4 silent
  skip; other outer len = Type4); 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz liveness re-check
  then SCRIPT_ERROR (constraint qdrant_behavioral_points_discover_batch_001).
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

# B4 uses a sentinel because None means "absent from the dict"
_ABSENT = object()

# (label, limit value or _ABSENT)
FACES = [
    ("B1 limit=0", 0),
    ("B2 limit=-1", -1),
    ("B3 limit=-100", -100),
    ("B4 limit missing", _ABSENT),
    ("B5 limit='3' (string)", "3"),
    ("B6 limit=3.5 (float)", 3.5),
    ("B7 limit=null", None),
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
    coll = "bpdwb5" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # G guard: min closure limit=1 -> 200, inner EXACTLY 1
        s, body, raw = discover_batch(coll, {"searches": [{"target": 1, "limit": 1}]})
        print(f"G limit=1 (min closure) -> status={s}")
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
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — limit=1 "
                  f"(boundary closure) rejected with {s} (promise: HTTP 200): "
                  f"{raw[:300]}")
            return
        inner = res[0] if (isinstance(res, list) and len(res) == 1
                           and isinstance(res[0], list)) else None
        if inner is None or len(inner) != 1:
            got = len(inner) if inner is not None else "bad shape"
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — G: "
                  f"limit=1 over 9 candidates returned {got} results "
                  f"(arithmetic expectation: exactly 1): {raw[:300]}")
            return
        print("G guard: limit=1 accepted, inner exactly 1 (boundary closure)")

        for label, lim in FACES:
            entry = {"target": 1}
            if lim is not _ABSENT:
                entry["limit"] = lim
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
            if 200 <= s <= 299:
                res = body.get("result") if isinstance(body, dict) else None
                n = (len(res[0]) if isinstance(res, list) and len(res) == 1
                     and isinstance(res[0], list) else "bad shape")
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"ACCEPTED with status {s} (inner {n}; expected 400/422 — "
                      f"schema minimum for limit is 1 and the field is "
                      f"required): {raw[:300]}")
                return
            if s in (400, 422):
                low = raw.lower()
                named = any(t in low for t in ("limit", "minimum", "integer",
                                               "range", "bound"))
                note = ("diagnostics name the limit construct"
                        if named else
                        "NOTE (strategy5): rejection text names no limit-family "
                        "token — diagnostics gap recorded for the judge")
                print(f"{label}: {s} clean rejection; {note}")
            else:
                print(f"NOTE: {label} returned {s}; recorded for the judge")

        # M1 mixed atomicity: valid limit=2 + limit=0 in ONE batch
        mixed = {"searches": [{"target": 1, "limit": 2},
                              {"target": 2, "limit": 0}]}
        s, body, raw = discover_batch(coll, mixed)
        print(f"\nM1 mixed batch (limit=2 + limit=0) -> status={s}")
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
                      f"limit=0 entry ACCEPTED inside a mixed batch (status "
                      f"{s}, 2 result arrays out; expected whole-batch 400): "
                      f"{raw[:300]}")
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
