#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_facet_002
# strategy: strategy6_resource_limit
# endpoint: facet
# constraint_ids: qdrant_resource_facet_limit_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/facet
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-07 (Resource Exhaustion Optimism — facet limit has NO documented maximum in
#            the v-1-18-x spec, so spec-legal huge limits must complete gracefully; an
#            allocator/index-scan blowup on a big limit would be a service-level crash)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 resource-limit x qdrant_resource_facet_limit_001 (facet limit, inferred
resource bound: spec declares minimum 1 and no maximum; spec-legal extreme values must
complete, be rejected with an explicit error, or fail with a documented service error —
never crash/OOM/panic/hang) — probes facet limit=1000000, limit=100000000 and
limit=2147483647 (INT_MAX) against a keyword-indexed fixture of 1001 distinct values, plus
one exact=true variant at limit=1000000 to double the counting path (G6 mutation
justification: exact=true swaps the index-fast count for the point-scan count path, the
most expensive legitimate execution a facet request can trigger)
[chunk_facet coverage: strategy6 x qdrant_resource_facet_limit_001]
Oracle: on a live bfa002_* collection (tag keyword-indexed, 1001 distinct values over 1100
points), facet limit=1e6/1e8/2147483647 and the exact=true variant each return HTTP 200
with at most 1001 hits (limit is an upper bound: fewer hits only if values are fewer — any
200 is NO_DEFECT here) or an explicit 4xx reject (NO_DEFECT per the resource assertion);
a 5xx/connection reset/panic/OOM or a client timeout followed by a dead /healthz =
Type3_RuntimeFailure (crash/DoS); a transport failure with /healthz alive = SCRIPT_ERROR
Constraint: qdrant_resource_facet_limit_001 (bare id) — "inferred: any spec-legal facet
limit (>= 1) must complete, be rejected with an error, or fail with a documented service
error - never crash the service" (evidence_tier: inferred; level: system)

Shape anchor (D3b): facet success face declares result.hits[] {value, count}; only
length-bound assertions are made (<= 1001 distinct), never exact-length (an internal
truncation would be an observation, not a resource defect).
Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  facet              -> POST   /collections/{collection_name}/facet
  collections+create -> PUT    /collections/{collection_name}
  collections+delete -> DELETE /collections/{collection_name}
  points+upsert      -> PUT    /collections/{collection_name}/points
  index+create       -> PUT    /collections/{collection_name}/index
  healthz            -> GET    /healthz
"""

import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ---
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
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)

# URL registry - verbatim from raw_knowledge.json api_endpoints[].url
PATH_FACET = "/collections/{collection_name}/facet"
PATH_CREATE = "/collections/{collection_name}"
PATH_DELETE = "/collections/{collection_name}"
PATH_UPSERT = "/collections/{collection_name}/points"
PATH_INDEX = "/collections/{collection_name}/index"

COLL = "bfa002_" + uuid.uuid4().hex[:10]  # unique-prefix discipline
DIM = 4
N_UNIQ = 1000   # distinct tag values tag_uniq_0000..tag_uniq_0999 (one point each)
N_HOT = 100     # hot value repeated on N_HOT points
N_DISTINCT = N_UNIQ + 1  # 1001 distinct facet values


def safe_request(method, endpoint, json=None, timeout=10, params=None):
    """Safe HTTP wrapper (agents/_target_api_reference.md). Returns (status, body, raw)."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(method=method, url=url, json=json,
                                    params=params, headers=headers, timeout=timeout)
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except Exception:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def healthz():
    """Lightweight liveness probe (G8: transport/5xx re-checked against /healthz)."""
    return safe_request("GET", "/healthz", timeout=5)


def cleanup():
    """Teardown: best-effort delete of ONLY the collection this script created."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")),
                     timeout=30, params={"timeout": 30})
    except Exception:
        pass  # cleanup failures are non-fatal


def facet_extreme(limit, exact=None):
    """POST facet with an extreme limit (optional exact flag). Long client timeout."""
    body = {"key": "tag", "limit": limit}
    if exact is not None:
        body["exact"] = exact
    return safe_request("POST", PATH_FACET.format(collection_name=quote(COLL, safe="")),
                        json=body, timeout=120)


def parse_hits(raw):
    """Envelope parse per response_shape result.hits[]; alias facet_hits tolerated."""
    try:
        body = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None, f"response not JSON: {str(raw)[:200]}"
    if not isinstance(body, dict):
        return None, f"response not an object: {str(raw)[:200]}"
    res = body.get("result")
    if not isinstance(res, dict):
        return None, f"envelope result missing/not object: {str(raw)[:200]}"
    if isinstance(res.get("hits"), list):
        return res["hits"], None
    if isinstance(res.get("facet_hits"), list):
        return res["facet_hits"], None
    return None, f"result.hits missing/not array: {str(raw)[:250]}"


def judge_probe(probe, limit, status, raw):
    """
    Resource-class judging (opposite of strategy 1): a crash is the defect;
    a 200 with <= distinct-values hits OR an explicit 4xx is NOT a defect.
    """
    if status <= 0 or 500 <= status <= 599:
        hs, _, hraw = healthz()
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        if status <= 0:
            if hs <= 0 or hs >= 500:
                return (f"DEFECT_FOUND (Type3_RuntimeFailure) - probe '{probe}' transport "
                        f"failure and /healthz={hs} (service down)")
            return f"SCRIPT_ERROR - probe '{probe}' transport failure with /healthz={hs} alive"
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) - probe '{probe}' spec-legal limit="
                f"{limit} got {status} with /healthz={hs}")
    if 200 <= status < 300:
        hits, err = parse_hits(raw)
        if err:
            return (f"DEFECT_FOUND (Type4_StateLogicViolation) - probe '{probe}' HTTP 200 "
                    f"but {err}")
        if len(hits) > N_DISTINCT:
            return (f"DEFECT_FOUND (Type4_StateLogicViolation) - probe '{probe}' HTTP 200 "
                    f"with {len(hits)} hits, more than the {N_DISTINCT} distinct fixture "
                    f"values: {str(raw)[:250]}")
        # 200 with <= distinct values: limit is an upper bound, completion is legal
        print(f"OK(complete): '{probe}' -> {status}, hits={len(hits)} (distinct={N_DISTINCT})")
        return None
    if 400 <= status < 500:
        # explicit rejection of an extreme-but-spec-legal limit = graceful handling
        print(f"OK(reject): '{probe}' -> {status}: {str(raw)[:250]}")
        return None
    return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"


def main():
    # ---- Arrange: 1100 points / 1001 distinct values over a keyword-indexed key ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    pts = []
    pid = 1
    for i in range(N_UNIQ):
        pts.append({"id": pid, "vector": [0.1] * DIM,
                    "payload": {"tag": f"tag_uniq_{i:04d}"}})
        pid += 1
    for _ in range(N_HOT):
        pts.append({"id": pid, "vector": [0.1] * DIM, "payload": {"tag": "hot"}})
        pid += 1
    st, _, raw = safe_request("PUT", PATH_UPSERT.format(collection_name=quote(COLL, safe="")),
                              json={"points": pts}, timeout=120, params={"wait": "true"})
    if st != 200:
        print(f"setup upsert {len(pts)} points failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    st, _, raw = safe_request("PUT", PATH_INDEX.format(collection_name=quote(COLL, safe="")),
                              json={"field_name": "tag", "field_schema": "keyword"},
                              timeout=120, params={"wait": "true"})
    if st != 200:
        print(f"setup keyword index on tag failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # ---- Act + Assert: extreme spec-legal limits must never crash the service ----
    for probe, lim, exact in (("limit=1000000", 1_000_000, None),
                              ("limit=1000000 exact=true", 1_000_000, True),
                              ("limit=100000000", 100_000_000, None),
                              ("limit=2147483647 (INT_MAX)", 2_147_483_647, None)):
        st, _, raw = facet_extreme(lim, exact)
        print(f"[probe {probe}] facet limit={lim} exact={exact} -> status={st}")
        v = judge_probe(probe, lim, st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return

    print(f"OK: extreme facet limits 1e6/1e8/INT_MAX (and exact=true variant) all completed "
          f"without crash; service alive")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
