#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_batch_context_type_003
# strategy: strategy2 type-boundary attack on per-entry context/pairs (the
#           "400 on invalid context/pairs" leg) + the batch-only atomicity
#           face: a mixed batch (one valid + one invalid entry) must be
#           rejected WHOLE — partial success (skipping the invalid entry)
#           breaks the one-result-array-per-query alignment contract
# endpoint: points+discover+batch
# constraint_ids: qdrant_behavioral_points_discover_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — per-entry serde gaps
#            could accept a string/object context, a pair-less pair or a
#            null example inside one batch entry with 200; and a batch
#            dispatcher could silently SKIP a bad entry instead of failing
#            the batch — the alignment promise "result[]: array, one per
#            query in order" makes any skip a Type4 even when status is 200)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 context/pairs type-confusion + batch atomicity x
  qdrant_behavioral_points_discover_batch_001 — per-entry context faces
  mirror the single-discover family (R36 calibration), each sent WITH a
  valid target so the only invalid part is the context construct under
  test; then the batch-only atomicity face:
    G  guard: VALID entry (target 1 + context pair, limit 3) -> 200,
       array-of-arrays outer len 1, inner 1..3.
    C1 context as STRING      "text"
    C2 context as OBJECT      {"positive": 1, "negative": 4}  (unwrapped)
    C3 pair-less pair         [{}]                             (R35 analog)
    C4 null example           [{"positive": null, "negative": 4}]
    C5 pair as ARRAY          [[]]
    C6 context null           null — judge-call: null ~= absent (target
       already present), acceptance degrades to target-only discover.
    M1 mixed atomicity: searches = [VALID entry, C3-shaped entry] ->
       whole batch must 400. 200 with TWO arrays = Type1 (invalid entry
       accepted); 200 with ONE array = Type4 (silent skip — alignment
       contract broken: one result array per query, in order); 200 with
       any other outer shape = Type4. Count guard certifies the substrate
       (9 points) is untouched either way (read-only face).
  [chunk_points+discover+batch coverage: strategy2 context/pairs
  type-confusion + mixed-batch atomicity x
  qdrant_behavioral_points_discover_batch_001 (this script; positive in
  boundary_points_discover_batch_positive_001, wrapper confusion in
  boundary_points_discover_batch_searches_type_002, 404 leg in
  boundary_points_discover_batch_404_004, limit matrix in
  boundary_points_discover_batch_limit_005, presence in
  boundary_points_discover_batch_presence_006, sparse-target shape in
  boundary_points_discover_batch_sparse_target_007, malformed stream in
  boundary_points_discover_batch_malformed_008, resource/batch-size in
  boundary_points_discover_batch_resource_009)]
Oracle: C1..C5 -> 400/422 clean rejection (any 2xx = Type1_IllegalSuccess:
  invalid context accepted inside a batch entry); C6 -> 400/422 or
  200-with-valid-array (both recorded for the judge; 200 with non-array
  result = Type4); M1 -> 400/422 whole-batch rejection (200 with outer
  len 2 = Type1; 200 with outer len 1 = Type4 silent-skip; 200 with any
  other outer len = Type4); G -> 200 array-of-arrays outer 1 inner 1..3;
  5xx with /healthz alive = Type3_RuntimeFailure; transport failure ->
  /healthz liveness re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_discover_batch_001).
Constraint: qdrant_behavioral_points_discover_batch_001 (bare id) — "returns
  200 [ScoredPoint]; 400 on invalid context/pairs; 404 for a missing
  collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+discover+batch -> POST /collections/{collection_name}/points/discover/batch
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
VALID_CONTEXT = [{"positive": 1, "negative": 4}]

# (label, invalid context value, expectation kind: "rej" | "judge")
FACES = [
    ("C1 context as STRING", "text", "rej"),
    ("C2 context as OBJECT", {"positive": 1, "negative": 4}, "rej"),
    ("C3 pair-less pair [{}]", [{}], "rej"),
    ("C4 null example", [{"positive": None, "negative": 4}], "rej"),
    ("C5 pair as ARRAY", [[]], "rej"),
    ("C6 context null (judge face)", None, "judge"),
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


def count_points(coll):
    """Exact count guard (read-only face substrate certification)."""
    s, body, raw = safe_request("POST", f"/collections/{coll}/points/count",
                                json={"exact": True}, timeout=60)
    if s == 200 and isinstance(body, dict):
        res = body.get("result")
        if isinstance(res, dict) and isinstance(res.get("count"), int):
            return res.get("count")
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdwb3" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # G guard
        s, body, raw = discover_batch(
            coll, {"searches": [{"target": 1, "context": list(VALID_CONTEXT),
                                 "limit": 3}]})
        print(f"G valid entry -> status={s}")
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
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — valid entry "
                  f"rejected with {s} (promise: HTTP 200): {raw[:300]}")
            return
        if not (isinstance(res, list) and len(res) == 1 and isinstance(res[0], list)
                and 1 <= len(res[0]) <= 3):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — guard: "
                  f"result not array-of-arrays outer 1 inner 1..3: {raw[:300]}")
            return
        print("G guard: batch channel live")

        for label, bad_ctx, expect in FACES:
            entry = {"target": 1, "context": bad_ctx, "limit": 3}
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

            if expect == "rej":
                if 200 <= s <= 299:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"invalid context ACCEPTED inside batch entry with "
                          f"status {s} (expected 400/422 clean rejection): "
                          f"{raw[:300]}")
                    return
                if s in (400, 422):
                    low = raw.lower()
                    named = any(t in low for t in ("context", "pair", "positive",
                                                   "negative", "example"))
                    note = ("diagnostics name the context construct"
                            if named else
                            "NOTE (strategy5): rejection text names no "
                            "context-family token — diagnostics gap recorded "
                            "for the judge")
                    print(f"{label}: {s} clean rejection; {note}")
                else:
                    print(f"NOTE: {label} returned {s}; recorded for the judge")
            else:  # judge face C6
                if 200 <= s <= 299:
                    if not (isinstance(res, list) and len(res) == 1
                            and isinstance(res[0], list)):
                        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                              f"{label}: 200 but result not array-of-arrays "
                              f"outer 1: {raw[:300]}")
                        return
                    print(f"{label}: judge-call face — accepted (null ~= absent, "
                          f"target-only discover); recorded for the judge")
                elif s in (400, 422):
                    print(f"{label}: judge-call face — {s} clean rejection; "
                          f"recorded for the judge")
                else:
                    print(f"NOTE: {label} returned {s}; recorded for the judge")

        # M1 mixed atomicity: valid entry + pair-less entry in ONE batch
        mixed = {"searches": [
            {"target": 1, "context": list(VALID_CONTEXT), "limit": 2},
            {"target": 2, "context": [{}], "limit": 2},
        ]}
        s, body, raw = discover_batch(coll, mixed)
        print(f"\nM1 mixed batch (valid + pair-less) -> status={s}")
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
                      f"invalid entry ACCEPTED inside a mixed batch "
                      f"(status {s}, 2 result arrays out; expected whole-batch "
                      f"400): {raw[:300]}")
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

        cnt = count_points(coll)
        if cnt is not None and cnt != N_SEED:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — read-only "
                  f"batch face mutated the substrate: count={cnt} != {N_SEED}")
            return
        print(f"count guard: {cnt} == {N_SEED} (substrate untouched)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
