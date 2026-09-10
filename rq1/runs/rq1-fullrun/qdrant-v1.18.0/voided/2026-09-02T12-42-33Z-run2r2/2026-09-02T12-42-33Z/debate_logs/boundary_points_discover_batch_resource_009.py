#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_batch_resource_009
# strategy: strategy6 resource-limit / DoS attack on the batch face —
#           batch WIDTH (entries per batch) x per-entry limit EXTREMES.
#           Implementation-layer limits, not contract boundaries: 200-accept
#           is NOT a defect here (limit is an upper bound; returning fewer
#           is legal); the defect signal is 5xx / OOM / hang / crash
# endpoint: points+discover+batch
# constraint_ids: qdrant_behavioral_points_discover_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-07 (Resource Exhaustion Optimism — the batch dispatcher may
#            preallocate per-entry result buffers from limit (qdrant #8406
#            class: allocator capacity from limit-product) or fan out N
#            sub-searches without a batch-size cap; v1.18 exposes
#            strict_mode_config.search_max_batchsize / max_query_limit as
#            OPTIONAL guardrails, default off, so the default path is the
#            attack surface). No group_size parameter exists on this
#            endpoint, so the group_size x limit combo sub-strategy has NO
#            applicable target here (honest coverage note).
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 resource-limit x
  qdrant_behavioral_points_discover_batch_001 — extreme-but-spec-legal
  values on the batch face (acceptance is legal; crash is the defect):
    G  guard: 3-entry batch, limit=1 each -> 200, outer len EXACTLY 3,
       each inner EXACTLY 1 (baseline alignment before extremes).
    R1 batch WIDTH: 200 identical valid entries (limit=1) -> 200 with
       outer len EXACTLY 200 (N-in/N-out under load), or a clean 400/422
       batch-size cap; 5xx/OOM/hang = Type3.
    R2 per-entry limit EXTREME: single entry limit=2147483647 (INT_MAX)
       -> 200 with inner <= 9 (only 9 seeded points; duplicate ids within
       the inner array = Type4 id-collision) or clean 400/422; 5xx = Type3.
    R3 per-entry limit BEYOND i32: limit=10**12 -> same expectations.
    R4 width x extreme COMBO: 50 entries each limit=10**9 (the #8406-class
       preallocation product) -> 200 with outer len EXACTLY 50 and each
       inner <= 9 with unique ids, or clean 400/422; 5xx/OOM/hang = Type3.
  [chunk_points+discover+batch coverage: strategy6 resource/batch-size x
  qdrant_behavioral_points_discover_batch_001 (this script; positive in
  boundary_points_discover_batch_positive_001, wrapper confusion in
  boundary_points_discover_batch_searches_type_002, context/pairs in
  boundary_points_discover_batch_context_type_003, 404 leg in
  boundary_points_discover_batch_404_004, limit matrix in
  boundary_points_discover_batch_limit_005, presence in
  boundary_points_discover_batch_presence_006, sparse-target shape in
  boundary_points_discover_batch_sparse_target_007, malformed stream in
  boundary_points_discover_batch_malformed_008)]
Oracle: strategy-6 convention (OPPOSITE of strategy-1): 200-accept is
  NO_DEFECT (limit is an upper bound; <=9 results legal) and 400/422
  explicit rejection is NO_DEFECT; the DEFECT signal is 5xx / OOM / panic
  / capacity-overflow text (Type3_RuntimeFailure, /healthz alive) or a
  request HANG while /healthz stays alive (Type3 resource exhaustion;
  timeout -> liveness re-check before any Type3, per G8); alignment on
  any 200: outer len EXACTLY N (else Type4) and inner arrays with unique
  ids and len <= 9 (else Type4); G -> 200 outer 3 inner 1 each; transport
  failure with /healthz down -> SCRIPT_ERROR (constraint
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
CRASH_TOKENS = ("oom", "out of memory", "panic", "capacity overflow", "killed",
                "allocation")


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


def discover_batch(coll, body, timeout=90):
    return safe_request("POST", f"/collections/{coll}/points/discover/batch",
                        json=body, timeout=timeout)


def ids_of(arr):
    """ids of one inner array; None if any element lacks an id."""
    out = []
    for p in arr:
        if not isinstance(p, dict) or "id" not in p:
            return None
        out.append(p.get("id"))
    return out


def handle_resource_face(label, coll, body_, n_entries, timeout):
    """Strategy-6 adjudication: crash/hang = Type3; accept or clean reject = pass.

    Returns True to continue the family, False after printing a verdict.
    """
    s, resp_body, raw = discover_batch(coll, body_, timeout=timeout)
    print(f"\n{label} -> status={s}")
    print(f"raw: {str(raw)[:400]}")
    if s == -1:
        # transport branch: G8 — liveness re-check BEFORE any Type3 judgment
        alive, hs, hraw = healthz_alive()
        if not alive:
            print(f"transport failure on {label} and /healthz down "
                  f"(status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return False
        low = str(raw).lower()
        hang = any(k in low for k in ("timed out", "timeout", "readtimeout",
                                      "expired"))
        if hang:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                  f"request HANG (client timeout) while /healthz stayed "
                  f"alive — resource exhaustion on the batch path: "
                  f"{str(raw)[:200]}")
        else:
            print(f"NOTE: transport failure on {label} with /healthz alive "
                  f"({str(raw)[:150]}); recorded for the judge — not judged "
                  f"as a defect without the hang signature")
            print("VERDICT: NO_DEFECT")
        return False
    if 500 <= s <= 599:
        alive, _, _ = healthz_alive()
        if alive:
            low = str(raw).lower()
            crashy = any(k in low for k in CRASH_TOKENS)
            tag = ("OOM/panic text present" if crashy else
                   f"server error {s}")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                  f"{tag} with /healthz alive: {str(raw)[:300]}")
        else:
            print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
        return False
    if s in (400, 422):
        print(f"{label}: {s} explicit rejection — legal for a resource-class "
              f"value (batch-size/limit cap); NO_DEFECT for this face")
        return True
    if not (200 <= s <= 299):
        print(f"NOTE: {label} returned {s} (neither 2xx nor 400/422); "
              f"recorded for the judge")
        return True

    # 200: acceptance is legal; only alignment/shape can still betray a defect
    res = resp_body.get("result") if isinstance(resp_body, dict) else None
    if not isinstance(res, list):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: "
              f"200 but result is not an array (response_shape: result "
              f"array): {str(raw)[:300]}")
        return False
    if len(res) != n_entries:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: "
              f"batch alignment broken under load: {n_entries} queries in, "
              f"{len(res)} result arrays out: {str(raw)[:300]}")
        return False
    total = 0
    for idx, arr in enumerate(res):
        if not isinstance(arr, list):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: "
                  f"inner result[{idx}] is not an array: {str(arr)[:150]}")
            return False
        ids = ids_of(arr)
        if ids is None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: "
                  f"inner result[{idx}] has non-object/id-less members")
            return False
        if len(ids) > N_SEED:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: "
                  f"inner result[{idx}] has {len(ids)} hits but only "
                  f"{N_SEED} points exist (fabrication or duplication)")
            return False
        if len(set(ids)) != len(ids):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: "
                  f"duplicate ids within inner result[{idx}]: {ids}")
            return False
        total += len(arr)
    print(f"{label}: 200 accepted (legal) — outer len={len(res)} aligned, "
          f"inner arrays well-formed, {total} hits total (<= {N_SEED} each)")
    return True


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdwb9" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # G guard: 3 entries, limit 1 each
        body_g = {"searches": [{"target": 1, "limit": 1} for _ in range(3)]}
        s, resp_body, raw = discover_batch(coll, body_g)
        print(f"G 3-entry baseline -> status={s}")
        print(f"raw: {str(raw)[:400]}")
        if s == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if not (200 <= s <= 299):
            print(f"NOTE: G returned {s}; recorded for the judge — extremes "
                  f"below still adjudicated on their own signals")
        else:
            res = resp_body.get("result") if isinstance(resp_body, dict) else None
            ok_g = (isinstance(res, list) and len(res) == 3
                    and all(isinstance(r, list) and len(r) == 1 for r in res))
            if not ok_g:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — G: "
                      f"baseline 3x limit=1 batch not aligned "
                      f"(outer {len(res) if isinstance(res, list) else 'non-array'}): "
                      f"{str(raw)[:300]}")
                return
            print("G guard: outer len=3, inner len=1 each (baseline aligned)")

        # R1 batch WIDTH: 200 entries
        body_r1 = {"searches": [{"target": 1, "limit": 1} for _ in range(200)]}
        if not handle_resource_face("R1 width=200 entries", coll, body_r1,
                                    200, timeout=180):
            return

        # R2 per-entry limit INT_MAX
        body_r2 = {"searches": [{"target": 1, "limit": 2147483647}]}
        if not handle_resource_face("R2 limit=INT_MAX (2147483647)", coll,
                                    body_r2, 1, timeout=180):
            return

        # R3 per-entry limit beyond i32
        body_r3 = {"searches": [{"target": 1, "limit": 10 ** 12}]}
        if not handle_resource_face("R3 limit=10**12", coll, body_r3, 1,
                                    timeout=180):
            return

        # R4 width x extreme combo (50 x 1e9 — the preallocation product)
        body_r4 = {"searches": [{"target": 1, "limit": 10 ** 9}
                                for _ in range(50)]}
        if not handle_resource_face("R4 combo 50 entries x limit=1e9", coll,
                                    body_r4, 50, timeout=180):
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
