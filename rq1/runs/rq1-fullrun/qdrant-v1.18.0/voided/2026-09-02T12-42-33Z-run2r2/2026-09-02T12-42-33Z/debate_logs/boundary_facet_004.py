#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_facet_004
# strategy: strategy1_behavioral_positive
# endpoint: facet
# constraint_ids: qdrant_behavioral_facet_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/facet
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the 200/400/404 status faces of the facet
#            promise assumed honored: 200-with-wrong-counts, 400-vs-200 on an unsupported
#            key, or a non-404 on a missing collection are all boundary defaults assumed
#            correct without evidence)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 behavioral both-direction x qdrant_behavioral_facet_001 (facet on an
indexed key returns HTTP 200 with {value, count} hits; facet on a key without a
MatchValue-capable index returns 400, not a wrong result; missing collection returns 404)
— positive: keyword-indexed genre facet returns 200 whose result.hits carry the exact
value/count fixture (count correctness = the 'not a wrong result' promise on the success
face); negative: facet on the unindexed key region returns 400 (an accepted 200 whose hits
disagree with the fixture would be the 'wrong result' the assertion excludes); error face:
facet on a NONEXISTENT collection returns 404
[chunk_facet coverage: strategy1 behavioral x qdrant_behavioral_facet_001]
Oracle: on a live bfa004_* collection (genre keyword-indexed with exactly alpha=10, beta=8,
gamma=5, delta=2; region unindexed with values north/south), facet key=genre limit=10 ->
HTTP 200 with result.hits length 4 and the exact set {alpha:10, beta:8, gamma:5, delta:2}
(length/count mismatch or malformed entries on a 200 = Type4_StateLogicViolation; any 4xx
on this documented-legal request = Type1_IllegalRejection); facet key=region -> HTTP 400/
422 (a 2xx whose hits contradict the fixture counts = Type1_IllegalSuccess 'wrong result');
facet on the nonexistent collection name bfa004_<uuid>_missing -> HTTP 404 (200 =
Type1_IllegalSuccess; other non-404 status printed for the judge); 5xx with /healthz alive
= Type3_RuntimeFailure
Constraint: qdrant_behavioral_facet_001 (bare id) — "facet on an indexed key returns HTTP
200 with value/count hits; facet on a key without a MatchValue-capable index returns 400,
not a wrong result" (evidence_tier: explicit; level: endpoint)

Shape anchor (D3b): the facet success face declares result.hits[] {value, count} per
api_endpoints[].response_shape (spec wins over the "{response: [...]}" paraphrase); hit
entries are validated to carry both value and count before the fixture comparison.
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
from collections import Counter
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

COLL = "bfa004_" + uuid.uuid4().hex[:10]  # unique-prefix discipline
COLL_MISSING = COLL + "_missing"          # nonexistent collection for the 404 probe
DIM = 4
DIST = {"alpha": 10, "beta": 8, "gamma": 5, "delta": 2}  # known fixture distribution
REGIONS = ["north", "south"]  # REGIONS[pid % 2]: odd ids -> south, even ids -> north
# expected unindexed-key region counts over ids 1..25 if a facet were served (odd=13 south)
EXPECTED_REGIONS = dict(Counter("south" if i % 2 == 1 else "north" for i in range(1, 26)))


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


def facet_on(coll, key):
    """POST facet on the given payload key of the given collection (limit 10)."""
    return safe_request("POST", PATH_FACET.format(collection_name=quote(coll, safe="")),
                        json={"key": key, "limit": 10}, timeout=60)


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


def judge_200_counts(probe, status, raw, expected_dist):
    """Positive face: 200 whose result.hits equal the fixture distribution exactly."""
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if status != 200:
        return (f"DEFECT_FOUND (Type1_IllegalRejection) - '{probe}' documented-legal facet "
                f"request rejected with {status}: {str(raw)[:250]}")
    hits, err = parse_hits(raw)
    if err:
        return f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' HTTP 200 but {err}"
    if len(hits) != len(expected_dist):
        return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' HTTP 200 with "
                f"{len(hits)} hits, expected {len(expected_dist)}: {str(raw)[:300]}")
    got = {}
    for h in hits:
        if not isinstance(h, dict) or "value" not in h or "count" not in h:
            return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' hit entry lacks "
                    f"value/count: {str(h)[:200]}")
        got[str(h.get("value"))] = h.get("count")
    if got != expected_dist:
        return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' facet returned a WRONG "
                f"result: got {got}, expected {expected_dist}: {str(raw)[:300]}")
    print(f"OK(200 counts): '{probe}' -> hits={got}")
    return None


def main():
    # ---- Arrange: fixture with indexed genre key and unindexed region key ----
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
            pts.append({"id": pid, "vector": [0.1] * DIM,
                        "payload": {"genre": genre,
                                    "region": REGIONS[pid % len(REGIONS)]}})
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

    # ---- Positive: indexed key -> 200 with exact value/count hits ----
    st, _, raw = facet_on(COLL, "genre")
    print(f"[probe positive indexed key] facet key=genre -> status={st}")
    v = judge_200_counts("indexed key genre", st, raw, DIST)
    if v is not None:
        print("VERDICT: " + v)
        return

    # ---- Negative: unindexed key -> documented 400, never a wrong 200 result ----
    st, _, raw = facet_on(COLL, "region")
    print(f"[probe negative unindexed key] facet key=region -> status={st}")
    if st <= 0 or 500 <= st <= 599:
        v = transport_or_5xx("unindexed key region", st, raw)
        print("VERDICT: " + v)
        return
    if 200 <= st < 300:
        print(f"raw body of the 2xx accept: {str(raw)[:400]}")
        hits, err = parse_hits(raw)
        if err:
            print("VERDICT: " + f"DEFECT_FOUND (Type1_IllegalSuccess) - unindexed key "
                  f"'region' accepted ({st}) with malformed hits: {err}")
            return
        got = {}
        for h in hits:
            if isinstance(h, dict) and "value" in h and "count" in h:
                got[str(h.get("value"))] = h.get("count")
        if got != EXPECTED_REGIONS:
            print("VERDICT: " + f"DEFECT_FOUND (Type1_IllegalSuccess + wrong result) - "
                  f"unindexed key 'region' accepted with {st} and hits {got} contradicting "
                  f"the fixture {EXPECTED_REGIONS}: {str(raw)[:300]}")
            return
        print("VERDICT: " + f"DEFECT_FOUND (Type1_IllegalSuccess) - unindexed key 'region' "
              f"accepted with {st} although the assertion declares 400 for keys without a "
              f"MatchValue-capable index")
        return
    if 400 <= st < 500:
        print(f"OK(reject): unindexed key region -> {st}: {str(raw)[:250]}")
    else:
        print(f"VERDICT: SCRIPT_ERROR - uninterpreted status {st} for the unindexed-key probe")
        return

    # ---- Error face: nonexistent collection -> 404 ----
    st, _, raw = facet_on(COLL_MISSING, "genre")
    print(f"[probe missing collection] facet on {COLL_MISSING} -> status={st}")
    if st <= 0 or 500 <= st <= 599:
        v = transport_or_5xx("missing collection", st, raw)
        print("VERDICT: " + v)
        return
    if st == 404:
        print(f"OK(404): missing collection -> {st}: {str(raw)[:250]}")
    elif 200 <= st < 300:
        print("VERDICT: " + f"DEFECT_FOUND (Type1_IllegalSuccess) - facet on the nonexistent "
              f"collection {COLL_MISSING} accepted with {st}: {str(raw)[:300]}")
        return
    else:
        print(f"non-404 status {st} on a missing collection (printed for the judge): "
              f"{str(raw)[:300]}")
        print("VERDICT: NO_DEFECT")
        return

    print("OK: indexed key facets 200 with exact value/count hits; unindexed key facets 400; "
          "missing collection facets 404")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
