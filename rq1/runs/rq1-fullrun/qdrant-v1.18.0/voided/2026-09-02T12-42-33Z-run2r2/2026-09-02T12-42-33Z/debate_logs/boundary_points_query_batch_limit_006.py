#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_batch_limit_006
# strategy: strategy1 boundary-value attack on searches[].limit — the batch
#           entries embed the same QueryRequest schema whose limit carries
#           the documented min-1 promise (qdrant_range_points_query_001);
#           every value is measured on BOTH the batch face and the single
#           query face in the same run (G9 cross-face parity)
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001, qdrant_range_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — clients trust that limit>=1
#            is enforced inside batch entries exactly as on the single face;
#            a batch wrapper that skips per-entry validation accepts
#            limit=0/-1 silently and breaks pagination arithmetic)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 per-entry limit boundary x
  qdrant_behavioral_points_query_batch_001, oracle ground
  qdrant_range_points_query_001 ("limit minimum 1 (default 10)" — the
  QueryRequest schema embedded in every searches[] element). Each value is
  sent as a single-entry batch AND as the identical single-face body (G9
  parity; both faces measured live in this run):
    L1    limit=1  (min legal closure) -> 200, exactly 1 point on both faces
    L0    limit=0  (min-1 boundary)    -> 400/422 on both faces
    Lneg  limit=-1 (negative boundary) -> 400/422 on both faces
    Ltype limit="3" (string type)      -> 400/422 on both faces
  [chunk_points+query+batch coverage: strategy1 positive order/count core x
  behavioral_points_query_batch_001 (positive_001); assertion 404 leg x
  behavioral_points_query_batch_001 (404_002); strategy2 searches wrapper
  type x behavioral_points_query_batch_001 (searches_type_003); strategy2
  entry presence matrix x behavioral_points_query_batch_001 (presence_004);
  R33-family dual-key enum discard x behavioral_points_query_batch_001
  (dualkey_005); strategy1 per-entry limit x behavioral_points_query_batch_001
  + range_points_query_001 min-1 ground (this script); strategy1 per-entry
  offset x behavioral_points_query_batch_001 + range_points_query_001 min-0
  ground (offset_007); mixed-variant universal-queries promise x
  behavioral_points_query_batch_001 (mixed_008); strategy6 batch-size
  resource x behavioral_points_query_batch_001 (resource_009); strategy7
  malformed stream x behavioral_points_query_batch_001 (malformed_010)]
Oracle: L1 -> 200 on both faces with exactly 1 point (count mismatch =
  Type4; rejection = Type1_IllegalSuccess convention: valid documented
  request); L0/Lneg/Ltype -> 400/422 on both faces (2xx on a face where the
  min-1 promise applies = Type1_IllegalSuccess); a disposition MISMATCH
  between the two faces for the same value (e.g. single rejects, batch
  accepts) = G9 same-parameter cross-face asymmetry, printed as a defect
  signal for the judge; 5xx with /healthz alive = Type3_RuntimeFailure;
  transport failure -> /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_query_batch_001).
Constraint: qdrant_behavioral_points_query_batch_001 (bare id) — "executes
  multiple queries in one call; returns 200 with a list of per-query results;
  404 for a missing collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+batch    -> POST /collections/{collection_name}/points/query/batch
  points+query          -> POST /collections/{collection_name}/points/query
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
BLUE_VEC = [0.0, 1.0, 0.0, 0.0]

# (label, limit value, expectation kind: "pos" | "rej")
FACES = [
    ("L1 limit=1 (min legal closure)", 1, "pos"),
    ("L0 limit=0 (min-1 boundary)", 0, "rej"),
    ("Lneg limit=-1 (negative)", -1, "rej"),
    ("Ltype limit=\"3\" (string)", "3", "rej"),
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


def point_vec(i):
    if i <= RED_N:
        return [1.0, round(0.001 * i, 4), 0.0, 0.0]
    return [round(0.001 * i, 4), 1.0, 0.0, 0.0]


def setup(coll):
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}},
                             timeout=60)
    if s not in (200, 201):
        return False, raw
    pts = [{"id": i, "vector": point_vec(i),
            "payload": {"grp": "red" if i <= RED_N else "blue", "rank": i}}
           for i in range(1, N_SEED + 1)]
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": pts}, params={"wait": "true"},
                             timeout=120)
    if s not in (200, 201):
        return False, raw
    return True, ""


def both_faces(coll, limit_value):
    """Send the identical entry body to the batch face (single-entry batch)
    and the single face; return ((s_batch, body_b, raw_b), (s_single, ...))."""
    entry = {"query": {"nearest": list(BLUE_VEC)}, "limit": limit_value}
    b = safe_request("POST", f"/collections/{coll}/points/query/batch",
                     json={"searches": [entry]}, timeout=60)
    g = safe_request("POST", f"/collections/{coll}/points/query",
                     json=entry, timeout=60)
    return b, g


def n_points_batch(body):
    if not isinstance(body, dict):
        return None
    res = body.get("result")
    if not isinstance(res, list) or len(res) != 1:
        return None
    elem = res[0]
    if not isinstance(elem, dict) or not isinstance(elem.get("points"), list):
        return None
    return len(elem["points"])


def n_points_single(body):
    if not isinstance(body, dict):
        return None
    res = body.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("points"), list):
        return None
    return len(res["points"])


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqb6" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        for label, lv, expect in FACES:
            (sb, bb, rb), (sg, bg, rg) = both_faces(coll, lv)
            print(f"\n{label} -> batch status={sb}, single status={sg}")
            print(f"batch raw: {rb[:300]}")
            print(f"single raw: {rg[:300]}")
            if sb == -1 or sg == -1:
                alive, hs, hraw = healthz_alive()
                print(f"transport failure on {label} (healthz status={hs}: {hraw})")
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
                return
            for st_, rw_, face in ((sb, rb, "batch"), (sg, rg, "single")):
                if 500 <= st_ <= 599:
                    alive, _, _ = healthz_alive()
                    if alive:
                        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — "
                              f"{label} on {face} face: returned {st_}: "
                              f"{rw_[:300]}")
                    else:
                        print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
                    return

            acc_b = 200 <= sb <= 299
            acc_g = 200 <= sg <= 299

            if expect == "pos":
                if not acc_b:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — "
                          f"{label}: valid documented request rejected on the "
                          f"batch face with {sb} (promise: HTTP 200): "
                          f"{rb[:300]}")
                    return
                if not acc_g:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — "
                          f"{label}: valid documented request rejected on the "
                          f"single face with {sg}: {rg[:300]}")
                    return
                nb, ng = n_points_batch(bb), n_points_single(bg)
                if nb != 1:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"{label}: batch face returned {nb} points "
                          f"(expected exactly 1): {rb[:300]}")
                    return
                if ng != 1:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"{label}: single face returned {ng} points "
                          f"(expected exactly 1): {rg[:300]}")
                    return
                print(f"{label}: upheld on both faces (exactly 1 point each)")

            else:  # rej
                if acc_b:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — "
                          f"{label}: ACCEPTED on the batch face with {sb} "
                          f"(limit min-1 promise, "
                          f"qdrant_range_points_query_001, applies to the "
                          f"embedded QueryRequest): {rb[:300]}")
                    return
                if acc_g:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — "
                          f"{label}: ACCEPTED on the single face with {sg} "
                          f"(limit min-1 promise, "
                          f"qdrant_range_points_query_001): {rg[:300]}")
                    return
                rej_b = sb in (400, 422)
                rej_g = sg in (400, 422)
                if rej_b != rej_g:
                    print(f"NOTE (G9): {label} disposition asymmetry — batch "
                          f"{sb} vs single {sg}; recorded for the judge")
                else:
                    low = (rb or "").lower()
                    named = any(t in low for t in ("limit", "range", "minimum",
                                                   "invalid", "expected"))
                    note = ("diagnostics name the limit construct"
                            if named else
                            "NOTE (strategy5): rejection text names no limit "
                            "token — diagnostics gap recorded for the judge")
                    print(f"{label}: clean rejection on both faces "
                          f"(batch={sb}, single={sg}); {note}")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
