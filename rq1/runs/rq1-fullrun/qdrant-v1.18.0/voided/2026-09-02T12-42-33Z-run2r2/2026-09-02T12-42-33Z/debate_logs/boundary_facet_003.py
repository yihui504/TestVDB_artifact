#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_facet_003
# strategy: strategy1_state_both_directions
# endpoint: facet
# constraint_ids: qdrant_state_facet_001
# source_url: https://qdrant.tech/documentation/manage-data/payload/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-04 (Boundary Default Optimism — facet's index requirement assumed enforced:
#            a facet on a key WITHOUT a MatchValue-capable payload index is documented to be
#            rejected with 400; a silent 200-with-hits would mean the requirement is not
#            gated at all, i.e. the validation boundary does not exist)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 both-direction state x qdrant_state_facet_001 (facet requires a payload
index supporting MatchValue conditions, e.g. keyword; without a suitable index the request
fails with 400 [DOC payload]) — positive control: facet on the keyword-indexed key genre
returns 200 with the exact fixture counts (proves the fixture/setup makes facet succeed, so
the negative probes are measuring the index requirement and nothing else); negatives:
facet on (a) an existing payload key mood that has NO index, (b) an existing payload key
score carrying a FLOAT payload index (range-only; not MatchValue-capable per the DOC
sentence), (c) a key ghost_key that exists in no point and has no index — each documented
to fail with 400
[chunk_facet coverage: strategy1 both-direction x qdrant_state_facet_001]
Oracle: on a live bfa003_* collection (genre keyword-indexed with exactly x=4, y=4, z=4;
mood unindexed with 12 values; score float-indexed), facet key=genre -> HTTP 200 with
result.hits exactly {x:4, y:4, z:4} (4xx here = Type1_IllegalRejection of the documented-
legal face; wrong counts on a 200 = Type4); facet key=mood, key=score and key=ghost_key
each return HTTP 400/422 per [DOC payload] "without a suitable index the request fails
with 400" — any 2xx-with-hits on those keys = Type1_IllegalSuccess candidate (raw text
printed for judge-doc reconciliation); 5xx with /healthz alive = Type3_RuntimeFailure
Constraint: qdrant_state_facet_001 (bare id) — "facet works only on a payload field that
has an index supporting MatchValue conditions (e.g. keyword index); without a suitable
index the request fails with 400" (evidence_tier: explicit; level: system)

Shape anchor (D3b): facet success face declares result.hits[] {value, count} (spec wins
over the "{response: [...]}" paraphrase). Negative probes are judged primarily on the HTTP
status code (400-class documented); raw text is always printed for the judge.
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

COLL = "bfa003_" + uuid.uuid4().hex[:10]  # unique-prefix discipline
DIM = 4
GENRE_DIST = {"x": 4, "y": 4, "z": 4}  # genre values x 12 points
MOODS = ["calm", "lively", "quiet", "stormy"]  # unindexed string values
KEY_INDEXED = "genre"     # keyword index (MatchValue-capable) -> positive control
KEY_UNINDEXED = "mood"    # existing payload key, no index -> 400 expected
KEY_FLOAT_INDEXED = "score"  # float payload index (range-only) -> 400 expected
KEY_GHOST = "ghost_key"   # key present in no point, no index -> 400 expected


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


def facet_key(key):
    """POST facet on the given payload key (limit 10)."""
    return safe_request("POST", PATH_FACET.format(collection_name=quote(COLL, safe="")),
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


def judge_negative(probe, key, status, raw):
    """
    Negative probe (key without a MatchValue-capable index): documented 400.
    A 2xx-with-hits is a Type1_IllegalSuccess candidate (accepted although the
    DOC payload page promises a 400); the raw text is printed for judge-doc
    reconciliation of the exact failure reason.
    """
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if status == 404:
        return f"SCRIPT_ERROR - probe '{probe}' got 404 on a live collection: {raw[:200]}"
    if 400 <= status < 500:
        print(f"OK(reject): '{probe}' key={key} -> {status}: {str(raw)[:250]}")
        return None
    if 200 <= status < 300:
        print(f"raw body of the 2xx accept: {str(raw)[:400]}")
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) - probe '{probe}' facet on key "
                f"{key!r} (no MatchValue-capable index) accepted with {status}, while the "
                f"constraint declares [DOC payload] 'without a suitable index the request "
                f"fails with 400'")
    return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"


def judge_positive_control(status, raw):
    """Keyword-indexed key must facet 200 with exactly the fixture counts."""
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx("positive control genre", status, raw)
    if status != 200:
        return (f"DEFECT_FOUND (Type1_IllegalRejection) - positive control: facet on the "
                f"keyword-indexed key 'genre' rejected with {status}: {str(raw)[:250]}")
    hits, err = parse_hits(raw)
    if err:
        return f"DEFECT_FOUND (Type4_StateLogicViolation) - positive control HTTP 200 but {err}"
    got = {}
    for h in hits:
        if isinstance(h, dict) and "value" in h and "count" in h:
            got[str(h.get("value"))] = h.get("count")
    if got != GENRE_DIST:
        return (f"DEFECT_FOUND (Type4_StateLogicViolation) - positive control counts "
                f"mismatch: got {got}, expected {GENRE_DIST}: {str(raw)[:300]}")
    print(f"OK(positive control): genre facet -> 200 hits={got}")
    return None


def main():
    # ---- Arrange: indexed key + no-index key + float-index key over 12 points ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    pts = []
    pid = 1
    for genre, cnt in GENRE_DIST.items():
        for i in range(cnt):
            pts.append({"id": pid,
                        "vector": [0.1] * DIM,
                        "payload": {"genre": genre,
                                    "mood": MOODS[(pid + i) % len(MOODS)],
                                    "score": float(pid * 1.5)}})
            pid += 1
    st, _, raw = safe_request("PUT", PATH_UPSERT.format(collection_name=quote(COLL, safe="")),
                              json={"points": pts}, timeout=60, params={"wait": "true"})
    if st != 200:
        print(f"setup upsert {len(pts)} points failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # keyword index on genre (MatchValue-capable) + float index on score (range-only)
    st, _, raw = safe_request("PUT", PATH_INDEX.format(collection_name=quote(COLL, safe="")),
                              json={"field_name": "genre", "field_schema": "keyword"},
                              timeout=60, params={"wait": "true"})
    if st != 200:
        print(f"setup keyword index on genre failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return
    st, _, raw = safe_request("PUT", PATH_INDEX.format(collection_name=quote(COLL, safe="")),
                              json={"field_name": "score", "field_schema": "float"},
                              timeout=60, params={"wait": "true"})
    if st != 200:
        print(f"setup float index on score failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # ---- Positive control: the indexed key facets (setup validity + promise face) ----
    st, _, raw = facet_key(KEY_INDEXED)
    print(f"[probe positive control] facet key=genre -> status={st}")
    v = judge_positive_control(st, raw)
    if v is not None:
        print("VERDICT: " + v)
        return

    # ---- Negatives: keys without a MatchValue-capable index must 400 ----
    for probe, key in (("unindexed existing key 'mood'", KEY_UNINDEXED),
                       ("float-indexed key 'score' (range-only)", KEY_FLOAT_INDEXED),
                       ("ghost key 'ghost_key' (no points, no index)", KEY_GHOST)):
        st, _, raw = facet_key(key)
        print(f"[probe {probe}] facet key={key} -> status={st}")
        v = judge_negative(probe, key, st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return

    print("OK: facet 200 only on the MatchValue-capable indexed key; unindexed/float-indexed/"
          "ghost keys rejected with 400 as documented")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
