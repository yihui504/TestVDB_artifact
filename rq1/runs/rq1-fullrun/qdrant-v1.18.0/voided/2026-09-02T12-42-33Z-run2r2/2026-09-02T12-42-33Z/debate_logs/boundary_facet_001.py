#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_facet_001
# strategy: strategy1_boundary_below_min
# endpoint: facet
# constraint_ids: qdrant_range_facet_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/facet
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — facet limit declared minimum 1 by the
#            v-1-18-x OpenAPI schema; below-min limits assumed rejected; a 2xx accept
#            would mean the limit floor is not enforced on the facet face)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary x qdrant_range_facet_001 (facet limit, asserted minimum 1,
default 10; no documented maximum) — below-minimum values limit=0, limit=-1 and limit=-100
must be rejected by POST /collections/{collection_name}/facet; boundary closure (G4
positive branch): the at-min value limit=1 must return exactly the single top hit, and the
mid/default values limit=10 and omitted-limit must return all distinct hits of the fixture
[chunk_facet coverage: strategy1 x qdrant_range_facet_001]
Oracle: on a live bfa001_* collection whose keyword-indexed genre field holds exactly
alpha=10, beta=8, gamma=5, delta=2 (25 points), facet limit=0 / -1 / -100 each return HTTP
400/422 (any 2xx = Type1_IllegalSuccess per the spec minimum 1; 5xx with /healthz alive =
Type3_RuntimeFailure); facet limit=1 returns HTTP 200 with result.hits of length exactly 1
whose entry is {value: alpha, count: 10}; facet limit=10 and facet with limit omitted both
return HTTP 200 with result.hits length exactly 4 and the exact count set {alpha:10,
beta:8, gamma:5, delta:2} (missing/extra hits or wrong counts on a 200 = Type4_
StateLogicViolation; a 4xx on the legal limit=1/10 probes = Type1_IllegalRejection)
Constraint: qdrant_range_facet_001 (bare id) — "facet limit minimum 1 (default 10); the
v-1-18-x spec documents no maximum" (evidence_tier: explicit; level: endpoint)

Shape anchor (D3b): the facet success face declares result: object with result.hits[]
(FacetValueHit {value, count}) per the api_endpoints[].response_shape (the facet description
paraphrase "{response: [...]}" conflicts with the spec-derived result.hits — spec wins).
Readback walk uses dict.get and tolerates an alias key facet_hits when hits is absent
(measured-only tolerance; the primary parse is the declared result.hits).
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

COLL = "bfa001_" + uuid.uuid4().hex[:10]  # unique-prefix discipline
DIM = 4
DIST = {"alpha": 10, "beta": 8, "gamma": 5, "delta": 2}  # known fixture distribution
N_POINTS = sum(DIST.values())  # 25


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


def facet_req(limit=None):
    """POST facet with the given limit (None = omit the limit key entirely)."""
    body = {"key": "genre"}
    if limit is not None:
        body["limit"] = limit
    return safe_request("POST", PATH_FACET.format(collection_name=quote(COLL, safe="")),
                        json=body, timeout=60)


def parse_hits(raw):
    """
    Envelope parse per response_shape: result.hits[] with {value, count}.
    Returns (hits_list, alias_used, err). Alias tolerance: if result.hits is
    absent, result.facet_hits is accepted (measured-only) and reported.
    """
    try:
        body = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None, False, f"response not JSON: {str(raw)[:200]}"
    if not isinstance(body, dict):
        return None, False, f"response not an object: {str(raw)[:200]}"
    res = body.get("result")
    if not isinstance(res, dict):
        return None, False, f"envelope result missing/not object: {str(raw)[:200]}"
    if isinstance(res.get("hits"), list):
        return res["hits"], False, None
    if isinstance(res.get("facet_hits"), list):
        return res["facet_hits"], True, None
    return None, False, f"result.hits missing/not array: {str(raw)[:250]}"


def transport_or_5xx(probe, status, raw):
    """Verdict for transport failure / 5xx after /healthz re-check. Returns verdict or None."""
    hs, _, hraw = healthz()
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    if status <= 0:
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) - probe '{probe}' transport failure "
                    f"and /healthz={hs} (service down)")
        return f"SCRIPT_ERROR - probe '{probe}' transport failure with /healthz={hs} alive"
    return (f"DEFECT_FOUND (Type3_RuntimeFailure) - probe '{probe}' got {status} "
            f"with /healthz={hs}")


def judge_reject_probe(probe, attack_val, status, raw):
    """Below-min probe: expect 4xx reject; any 2xx = Type1_IllegalSuccess."""
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if status == 404:
        return f"SCRIPT_ERROR - probe '{probe}' got 404 on a live collection: {raw[:200]}"
    if 400 <= status < 500:
        print(f"OK(reject): '{probe}' -> {status}: {str(raw)[:250]}")
        return None
    if 200 <= status < 300:
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) - '{probe}' facet limit={attack_val} "
                f"accepted with {status} although the v-1-18-x spec declares minimum 1: "
                f"{str(raw)[:300]}")
    return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"


def judge_accept_probe(probe, expected_len, expected_dist, status, raw):
    """
    Legal-value probe (at-min / mid / default): expect 200 with the declared
    result.hits shape and the exact fixture-derived hit set.
    expected_dist None -> only the length is checked (top-1 probe).
    """
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if 400 <= status < 500:
        return (f"DEFECT_FOUND (Type1_IllegalRejection) - '{probe}' documented-legal facet "
                f"request rejected with {status}: {str(raw)[:250]}")
    if status != 200:
        return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"
    hits, alias, err = parse_hits(raw)
    print(f"OK(200): '{probe}' hits_key=facet_hits[{alias}] len="
          f"{len(hits) if isinstance(hits, list) else 'NA'}")
    if err:
        return f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' HTTP 200 but {err}"
    if len(hits) != expected_len:
        return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' HTTP 200 with "
                f"{len(hits)} hits, expected {expected_len}: {str(raw)[:300]}")
    if expected_dist is None:
        return None  # length already verified (top-1 probe)
    got = {}
    for h in hits:
        if not isinstance(h, dict) or "value" not in h or "count" not in h:
            return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' hit entry lacks "
                    f"value/count: {str(h)[:200]}")
        got[str(h.get("value"))] = h.get("count")
    if got != expected_dist:
        return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' facet hit counts "
                f"mismatch: got {got}, expected {expected_dist}: {str(raw)[:300]}")
    return None


def main():
    # ---- Arrange: collection + indexed payload fixture (genre counts known exactly) ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    pts = []
    pid = 1
    for genre, cnt in DIST.items():
        for _ in range(cnt):
            pts.append({"id": pid, "vector": [0.1] * DIM, "payload": {"genre": genre}})
            pid += 1
    st, _, raw = safe_request("PUT", PATH_UPSERT.format(collection_name=quote(COLL, safe="")),
                              json={"points": pts}, timeout=60, params={"wait": "true"})
    if st != 200:
        print(f"setup upsert {len(pts)} points failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    st, _, raw = safe_request("PUT", PATH_INDEX.format(collection_name=quote(COLL, safe="")),
                              json={"field_name": "genre", "field_schema": "keyword"},
                              timeout=60, params={"wait": "true"})
    if st != 200:
        print(f"setup keyword index on genre failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # ---- Act + Assert: below-minimum limits must be rejected ----
    for probe, val in (("limit=0 (min-1)", 0), ("limit=-1 (negative)", -1),
                       ("limit=-100 (deep negative)", -100)):
        st, _, raw = facet_req(val)
        print(f"[probe {probe}] facet limit={val} -> status={st}")
        v = judge_reject_probe(probe, val, st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return

    # ---- Boundary closure (G4 positive branch): at-min / mid / default must be accepted ----
    st, _, raw = facet_req(1)
    print(f"[probe limit=1 (at-min)] -> status={st}")
    v = judge_accept_probe("limit=1 (at-min)", 1, None, st, raw)
    if v is not None:
        print("VERDICT: " + v)
        return
    # the single hit must be the top-count value alpha with count 10 (fixture design: no ties)
    hits, _, err = parse_hits(raw)
    if err:
        print(f"VERDICT: SCRIPT_ERROR - top-1 readback parse failed: {err}")
        return
    top = hits[0]
    if top.get("value") != "alpha" or top.get("count") != 10:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - limit=1 returned top hit "
              f"{top}, expected alpha/count 10: {str(raw)[:300]}")
        return

    for probe, lim in (("limit=10 (mid/default)", 10), ("limit omitted (default)", None)):
        st, _, raw = facet_req(lim)
        print(f"[probe {probe}] -> status={st}")
        v = judge_accept_probe(probe, 4, DIST, st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return

    print("OK: limit=0/-1/-100 rejected (400/422), limit=1 and limit=10/omitted accepted "
          "with exact expected hit sets")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
