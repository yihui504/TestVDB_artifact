#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_batch_malformed_008
# strategy: strategy7 malformed input / character fuzzing on the batch face
#           (malformed JSON stream, NUL bytes raw and JSON-escaped, lone
#           UTF-16 surrogate, 1MB overlong string) — raw bodies sent via
#           data= so client-side JSON serialization cannot pre-reject them
# endpoint: points+discover+batch
# constraint_ids: qdrant_behavioral_points_discover_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde/stream layers
#            trusted to receive well-formed JSON and legal Unicode; a
#            parser panic leaks internal errors or 5xx on input that a
#            robust 4xx gate should absorb; the batch wrapper adds one more
#            nesting level for the parser to mishandle)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed stream x
  qdrant_behavioral_points_discover_batch_001 — the batch face receives
  raw-byte bodies (data=, never json=, so the client cannot pre-reject
  them; strategy-7 safety wrapper discipline):
    G  guard: hand-built VALID JSON body as bytes (same content the json=
       face accepts) -> 200, array-of-arrays outer 1 (raw path live).
    F1 truncated JSON        b'{"searches": [{'
    F2 trailing comma        b'{"searches": [{"target": 1, "limit": 1}],}'
    F3 bare NUL byte inside the body (after "1")
    F4 JSON-escaped NUL in a filter key ("gr\\u0000p") — judge-call face:
       syntax-legal JSON carrying a control character; clean 400 or
       acceptance-with-valid-array are both defensible, 5xx = Type3.
    F5 lone UTF-16 surrogate escape in a match value ("re\\ud800d") —
       judge-call face: syntax-legal JSON, illegal Unicode scalar.
    F6 overlong string: 1MB filter key -> 400/413/422 or 200 (key simply
       matches nothing) are all non-defects; OOM/5xx = Type3.
  [chunk_points+discover+batch coverage: strategy7 malformed stream x
  qdrant_behavioral_points_discover_batch_001 (this script; positive in
  boundary_points_discover_batch_positive_001, wrapper confusion in
  boundary_points_discover_batch_searches_type_002, context/pairs in
  boundary_points_discover_batch_context_type_003, 404 leg in
  boundary_points_discover_batch_404_004, limit matrix in
  boundary_points_discover_batch_limit_005, presence in
  boundary_points_discover_batch_presence_006, sparse-target shape in
  boundary_points_discover_batch_sparse_target_007, resource/batch-size in
  boundary_points_discover_batch_resource_009)]
Oracle: F1/F2/F3 -> 400/422 clean rejection (any 2xx = Type1_IllegalSuccess:
  malformed JSON stream accepted); F4/F5 -> 400/422 or 200-with-valid-
  array-of-arrays (both recorded for the judge; 200 with a NON-array
  result = Type4); F6 -> 400/413/422 or 200 all NO_DEFECT; G -> 200
  array-of-arrays outer 1 inner 1..1 (non-200 = raw-path regression,
  Type1 convention; wrong shape = Type4); 5xx anywhere with /healthz
  alive = Type3_RuntimeFailure; transport failure -> /healthz liveness
  re-check then SCRIPT_ERROR (constraint
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

VALID_RAW = b'{"searches": [{"target": 1, "limit": 1}]}'

# (label, raw body bytes, timeout, expectation kind: "pos" | "rej" | "judge")
FACES = [
    ("F1 truncated JSON", b'{"searches": [{', 60, "rej"),
    ("F2 trailing comma",
     b'{"searches": [{"target": 1, "limit": 1}],}', 60, "rej"),
    ("F3 bare NUL byte in body",
     b'{"searches": [{"target": 1, "limit": 1\x00}]}', 60, "rej"),
    ("F4 JSON-escaped NUL in filter key",
     b'{"searches": [{"target": 1, "limit": 1, "filter": {"must": '
     b'[{"key": "gr\\u0000p", "match": {"value": "red"}}]}}]}', 60, "judge"),
    ("F5 lone UTF-16 surrogate in match value",
     b'{"searches": [{"target": 1, "limit": 1, "filter": {"must": '
     b'[{"key": "grp", "match": {"value": "re\\ud800d"}}]}}]}', 60, "judge"),
]


def safe_request(method, endpoint, json=None, timeout=60, params=None,
                 data=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    data= carries RAW bytes straight to the wire (strategy-7 discipline:
    malformed streams must bypass client-side JSON serialization).
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, headers=headers,
            timeout=timeout, params=params, data=data,
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


def discover_batch_raw(coll, raw_body, timeout=60):
    """points+discover+batch face with a raw byte body."""
    return safe_request("POST", f"/collections/{coll}/points/discover/batch",
                        data=raw_body, timeout=timeout)


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdwb8" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # G guard: the same valid body, hand-built as bytes
        s, body, raw = discover_batch_raw(coll, VALID_RAW)
        print(f"G valid raw-body batch -> status={s}")
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
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — valid raw "
                  f"body rejected with {s} (promise: HTTP 200): {raw[:300]}")
            return
        if not (isinstance(res, list) and len(res) == 1 and isinstance(res[0], list)
                and len(res[0]) == 1):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — guard: "
                  f"result not array-of-arrays outer 1 inner exactly 1 "
                  f"(limit=1 over 9 candidates): {raw[:300]}")
            return
        print("G guard: raw-body path live (200, inner exactly 1)")

        for label, raw_body, tmo, expect in FACES:
            s, body, raw = discover_batch_raw(coll, raw_body, timeout=tmo)
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
                    low = raw.lower()
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: malformed "
                          f"input triggered {s}: {raw[:300]}")
                else:
                    print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
                return
            res = body.get("result") if isinstance(body, dict) else None
            good_shape = (isinstance(res, list) and len(res) == 1
                          and isinstance(res[0], list))

            if expect == "rej":
                if 200 <= s <= 299:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"malformed JSON stream ACCEPTED with status {s} "
                          f"(expected 400/422 clean rejection): {raw[:300]}")
                    return
                if s in (400, 422):
                    print(f"{label}: {s} clean rejection")
                else:
                    print(f"NOTE: {label} returned {s}; recorded for the judge")

            else:  # judge faces F4/F5
                if 200 <= s <= 299:
                    if not good_shape:
                        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                              f"{label}: 200 but result not array-of-arrays "
                              f"outer 1: {raw[:300]}")
                        return
                    print(f"{label}: judge-call face — accepted with a valid "
                          f"result array (len={len(res[0])}); recorded for the "
                          f"judge (control-char / surrogate storage semantics)")
                elif s in (400, 422):
                    print(f"{label}: judge-call face — {s} clean rejection; "
                          f"recorded for the judge")
                else:
                    print(f"NOTE: {label} returned {s}; recorded for the judge")

        # F6 overlong string: 1MB filter key (built as raw bytes)
        key = b"k" * 1_000_000
        f6_body = (b'{"searches": [{"target": 1, "limit": 1, "filter": '
                   b'{"must": [{"key": "' + key + b'", "match": '
                   b'{"value": "red"}}]}}]}')
        s, body, raw = discover_batch_raw(coll, f6_body, timeout=120)
        print(f"\nF6 overlong 1MB filter key -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on F6 (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F6: 1MB "
                      f"key triggered {s} (resource exhaustion on the parse "
                      f"path): {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F6 5xx and healthz down")
            return
        if s in (400, 413, 422):
            print("F6: size/length rejection — clean")
        elif 200 <= s <= 299:
            res = body.get("result") if isinstance(body, dict) else None
            if not (isinstance(res, list) and len(res) == 1
                    and isinstance(res[0], list)):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F6: "
                      f"200 but result not array-of-arrays outer 1: "
                      f"{raw[:300]}")
                return
            inner = (len(res[0]) if len(res[0]) <= N_SEED else
                     f"{len(res[0])} (> {N_SEED} seeded points!)")
            if isinstance(inner, str):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F6: "
                      f"{inner}: {raw[:300]}")
                return
            print(f"F6: accepted; inner len={inner} (key matches nothing; "
                  f"non-defect)")
        else:
            print(f"NOTE: F6 returned {s}; recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
