#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_404_003
# strategy: strategy1 boundary attack on the collection_name path dimension
#           (the "404 for a missing collection" leg of the endpoint promise;
#           same body run against a live collection first so the 404
#           attributes to missingness, not to a malformed request)
# endpoint: points+discover
# constraint_ids: qdrant_behavioral_points_discover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01/BS-04 (collection_name is a path parameter — coercion or
#            routing gaps could answer a discover on a nonexistent collection
#            with 2xx (fabricated results) or a wrong 4xx class instead of
#            the promised 404)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 missing-collection x qdrant_behavioral_points_discover_001 —
  the "404 for a missing collection" leg. A ghost collection name is PROVEN
  unused via the collections+exists face (no fake 200 from a name guess):
    G  guard: the exact same valid sparse discover body against a LIVE seeded
       collection -> 200, result array — proves the body is valid, so any 4xx
       on the ghost run attributes to missingness alone.
    N1 full valid body (target + context + using + limit) on the ghost
       -> 404 exactly.
    N2 minimal valid body (target-only) on the ghost -> 404 exactly.
    N3 invalid body (context as STRING) on the ghost -> any 4xx; the returned
       class (404 vs 400 precedence) is recorded as a NOTE for the G9
       disposition-consistency check, not a standalone defect.
  [chunk_points+discover coverage: strategy1 404 leg x
  qdrant_behavioral_points_discover_001 (this script; positive/shape in
  boundary_points_discover_positive_001, context type-confusion in
  boundary_points_discover_context_type_002, limit matrix in
  boundary_points_discover_limit_004, presence matrix in
  boundary_points_discover_presence_005, sparse-target shape in
  boundary_points_discover_sparse_target_006, filter family mirror in
  boundary_points_discover_filter_type_007, malformed stream in
  boundary_points_discover_malformed_008)]
Oracle: N1/N2 -> HTTP 404 exactly (2xx = Type1_IllegalSuccess: discover
  fabricated a success on a missing collection; non-404 4xx = NOTE for the
  G9 cross-face disposition check; 5xx with /healthz alive =
  Type3_RuntimeFailure); N3 -> any 4xx recorded (precedence note); G -> 200
  with result array 1..3 (other = Type4; non-200 = valid discover rejected,
  Type1 convention per session); transport failure -> /healthz liveness
  re-check then SCRIPT_ERROR (constraint qdrant_behavioral_points_discover_001).
Constraint: qdrant_behavioral_points_discover_001 (bare id) — "returns 200
  [ScoredPoint]; 400 on invalid context/pairs; 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+discover       -> POST /collections/{collection_name}/points/discover
  collections+exists    -> GET  /collections/{collection_name}/exists
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
FULL_BODY = {"using": SPARSE_NAME, "target": GUARD_TARGET,
             "context": GUARD_CONTEXT, "limit": 3}
MINI_BODY = {"using": SPARSE_NAME, "target": GUARD_TARGET, "limit": 3}
BAD_BODY = {"using": SPARSE_NAME, "target": GUARD_TARGET,
            "context": "text", "limit": 3}


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


def collection_exists(name):
    """collections+exists face: result.exists boolean."""
    s, body, raw = safe_request("GET", f"/collections/{name}/exists", timeout=30)
    if s == -1 or not (200 <= s <= 299):
        return None, s, raw
    result = body.get("result") if isinstance(body, dict) else None
    got = result.get("exists") if isinstance(result, dict) else None
    return got, s, raw


def fresh_ghost_name():
    """uuid-tagged name PROVEN unused via collections+exists (no fake 200)."""
    for _ in range(4):
        name = "bpdw3no" + uuid.uuid4().hex[:10]
        got, s, raw = collection_exists(name)
        if got is False:
            return name
    return None


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
    coll = "bpdw3" + tag
    ghost = fresh_ghost_name()
    if ghost is None:
        print("could not prove a ghost collection name unused (exists face)")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # ---- G: guard — same valid body on the LIVE collection -> 200 ----
        s, body, raw = discover(coll, FULL_BODY)
        print(f"\nG guard valid body on live collection -> status={s}")
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
                  f"but result not an array of 1..3: {raw[:300]}")
            return
        print(f"G: 200, result array len={len(res)}; ghost {ghost} proven absent")

        # ---- N1/N2: valid bodies on the ghost collection -> 404 exactly ----
        for label, body_ in (("N1 full valid body", FULL_BODY),
                             ("N2 target-only valid body", MINI_BODY)):
            s, _, raw = discover(ghost, body_)
            print(f"\n{label} on ghost collection -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                transport_dead(label)
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                          f"discover on missing collection returned {s}: {raw[:300]}")
                else:
                    print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
                return
            if 200 <= s <= 299:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"discover FABRICATED success (status {s}) on the missing "
                      f"collection {ghost}; promise says 404: {raw[:300]}")
                return
            if s == 404:
                print(f"{label}: 404 exactly as promised")
            else:
                print(f"NOTE: {label} returned {s} instead of 404 — non-404 4xx "
                      f"on a missing collection; recorded for the G9 "
                      f"disposition-consistency check")

        # ---- N3: invalid body on the ghost -> precedence note (not a defect) ----
        s, _, raw = discover(ghost, BAD_BODY)
        print(f"\nN3 invalid body on ghost collection -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            transport_dead("N3")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — N3: "
                      f"invalid body on missing collection returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — N3 5xx and healthz down")
            return
        if 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — N3: invalid "
                  f"body ACCEPTED with status {s} on the missing collection "
                  f"{ghost} (promise: 400/404): {raw[:300]}")
            return
        if s in (400, 404, 422):
            print(f"N3: {s} (400-vs-404 precedence on missing collection + "
                  f"invalid body — NOTE for the judge)")
        else:
            print(f"NOTE: N3 returned {s}; recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
