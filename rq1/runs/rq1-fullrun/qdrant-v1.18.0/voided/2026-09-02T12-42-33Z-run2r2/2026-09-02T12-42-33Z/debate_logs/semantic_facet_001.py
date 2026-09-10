#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_facet_001
# strategy: behavioral_contract
# endpoint: facet
# constraint_ids: qdrant_behavioral_facet_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/facet
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the v-1-18-x behavioral contract promises a
#            200 with real {value,count} hits on an indexed key and a 404 for a missing
#            collection; the facet description paraphrase "{response: [...]}" conflicts
#            with the spec-derived envelope result.hits[].{value,count} - spec wins,
#            adjudication reads result.hits with a measured-only facet_hits alias
#            tolerance. The count values themselves are the falsifiable payload: a 200
#            whose hit counts do not equal the inserted ground truth = Type4.)
"""
Attack: behavioral_contract (strategy 1) x qdrant_behavioral_facet_001 on facet
  (chunk_facet unit assertions::qdrant_behavioral_facet_001 - assertion: "facet on an
  indexed key returns HTTP 200 with value/count hits; facet on a key without a
  MatchValue-capable index returns 400, not a wrong result", evidence_tier=explicit,
  level=endpoint). Legs constructed here:
    leg A (indexed-key success + count semantics): keyword-indexed genre field holding a
      known distribution (alpha=10, beta=8, gamma=5, delta=2 over 25 points) - facet
      must return HTTP 200 with result.hits[] entries {value, count} whose value/count
      SET equals the ground truth exactly (missing/extra hits or wrong counts on a 200
      = Type4_StateLogicViolation); the top-1 hit must be the maximum-count value
      (selection semantics of "aggregate hit counts of payload values").
    leg B (missing collection): facet on a never-created collection must return HTTP 404
      (per the behavioral contract's 404 clause) - a 200 with data or a 400 instead of
      404 for a missing collection = Type4_StateLogicViolation (state mis-reconciled
      with the endpoint's documented 404 contract).
  The 400-no-suitable-index clause of this unit is co-owned with the system-level state
  constraint qdrant_state_facet_001 and is executed inside semantic_facet_003
  (diagnosis_quality) with richer constructs (unindexed key AND text-indexed key) - no
  duplication here.
  R17 reconciliation (G10): the no-index 400 leg = semantic_facet_003; the limit-face
  probes of the same unit live in semantic_facet_004 (type coercion) and
  semantic_facet_005 (default-10/truncation semantics); boundary_facet_001 owns the
  below-min limit rejection face. This script = pure behavioral success/404 legs.
Oracle: on a live sfa01_* collection with genre keyword-indexed holding exactly
  alpha=10, beta=8, gamma=5, delta=2 (25 points, no deletions): facet {key: genre}
  returns HTTP 200 and result.hits contains exactly the 4 value/count pairs
  {alpha:10, beta:8, gamma:5, delta:2} with the maximum-count value alpha as the top
  hit (any 4xx on this legal request = Type1_IllegalRejection; a 200 with a missing/
  extra hit or a wrong count = Type4_StateLogicViolation); facet on the never-created
  collection sfac01_<missing>_none returns HTTP 404 (a 200 with any data or a 400
  instead = Type4_StateLogicViolation); a 5xx or transport failure with /healthz not
  alive = Type3_RuntimeFailure; setup/transport failure with /healthz alive =
  SCRIPT_ERROR (G8).

Constraint anchor qdrant_behavioral_facet_001 (explicit, endpoint): "facet on an
  indexed key returns HTTP 200 with value/count hits; facet on a key without a
  MatchValue-capable index returns 400, not a wrong result" - source_url
  https://api.qdrant.tech/v-1-18-x/api-reference/points/facet (doc_quote: "Faceting
  works only on a payload field with an index supporting MatchValue conditions;
  returns 200 {response: [FacetValueHit {value, count}]}; 404; 400 (including when no
  suitable index exists)." - the {response:[...]} paraphrase conflicts with the
  response_shape grid result.hits[].{value,count}; spec-derived fields win, D3b).

[chunk_facet coverage: behavioral_contract x qdrant_behavioral_facet_001 (leg A
  success/count semantics + leg B 404-missing-collection; no-index 400 clause co-owned
  by semantic_facet_003)]
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
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ----
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    for _p in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or str(TARGET).lower() != "qdrant":
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap three-layer fallback failed)")
    sys.exit(2)

# URL registry - verbatim from raw_knowledge.json api_endpoints[].url
#   facet -> /collections/{collection_name}/facet (method POST)
#   collections+create -> /collections/{collection_name} (method PUT)
#   collections+delete -> /collections/{collection_name} (method DELETE)
#   points+upsert -> /collections/{collection_name}/points (method PUT)
#   index+create -> /collections/{collection_name}/index (method PUT)
#   healthz -> /healthz (method GET)
PATH_FACET = "/collections/{collection_name}/facet"
PATH_CREATE = "/collections/{collection_name}"
PATH_DELETE = "/collections/{collection_name}"
PATH_UPSERT = "/collections/{collection_name}/points"
PATH_INDEX = "/collections/{collection_name}/index"

PFX = uuid.uuid4().hex[:8]
COLL = "sfa01_" + PFX
COLL_MISSING = "sfa01_" + PFX + "_never_created"
DIM = 4
DIST = {"alpha": 10, "beta": 8, "gamma": 5, "delta": 2}  # fixture ground truth
N_POINTS = sum(DIST.values())  # 25


def safe_request(method, endpoint, json=None, timeout=30, params=None):
    """Safe HTTP wrapper per agents/_target_api_reference.md. Returns (status, body, raw)."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(method=method, url=url, json=json,
                                    headers=headers, timeout=timeout, params=params)
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


def transport_or_5xx(probe, status, raw):
    """Verdict text for transport failure / 5xx after /healthz re-check."""
    hs, _, hraw = healthz()
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    if status <= 0:
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) - probe '{probe}' transport "
                    f"failure and /healthz={hs} (service down)")
        return f"SCRIPT_ERROR - probe '{probe}' transport failure with /healthz={hs} alive"
    return (f"DEFECT_FOUND (Type3_RuntimeFailure) - probe '{probe}' got {status} "
            f"with /healthz={hs}")


def parse_hits(raw):
    """
    Envelope parse per response_shape: result.hits[] with {value, count}.
    Returns (hits_list, alias_used, err). Alias tolerance: result.facet_hits accepted
    when hits absent (measured-only; primary parse is the declared result.hits).
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


def judge_success_leg(probe, status, raw):
    """Legal indexed-key facet: 200 + exact {value:count} set == ground truth."""
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if 400 <= status < 500:
        return (f"DEFECT_FOUND (Type1_IllegalRejection) - '{probe}' documented-legal facet "
                f"request on an indexed key rejected with {status}: {str(raw)[:250]}")
    if status != 200:
        return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"
    hits, alias, err = parse_hits(raw)
    print(f"OK(200): '{probe}' hits_key=facet_hits[{alias}] len={len(hits) if isinstance(hits, list) else 'NA'}")
    if err:
        return f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' HTTP 200 but {err}"
    if len(hits) != len(DIST):
        return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' HTTP 200 with "
                f"{len(hits)} hits, expected {len(DIST)} distinct values: {str(raw)[:300]}")
    got = {}
    for h in hits:
        if not isinstance(h, dict) or "value" not in h or "count" not in h:
            return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' hit entry lacks "
                    f"value/count: {str(h)[:200]}")
        got[str(h.get("value"))] = h.get("count")
    if got != DIST:
        return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' facet hit counts "
                f"mismatch: got {json.dumps(got)}, expected {json.dumps(DIST)}: {str(raw)[:300]}")
    # top-1 selection semantics: max-count value must be the first hit
    if hits and str(hits[0].get("value")) != "alpha":
        return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' top hit is "
                f"{hits[0].get('value')}, expected the maximum-count value alpha: {str(raw)[:300]}")
    return None


def main():
    print(f"ownership prefix: {PFX} collection={COLL} missing-collection-probe={COLL_MISSING}")
    try:
        # ---- Arrange: collection + keyword index + fixture with known genre counts ----
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
        # sanity: payload ground truth counter must match the design constant
        truth = Counter(p["payload"]["genre"] for p in pts)
        if dict(truth) != DIST:
            print(f"setup fixture self-check failed: {dict(truth)} != {DIST}")
            print("VERDICT: SCRIPT_ERROR - fixture construction bug, no defect conclusion")
            return
        st, _, raw = safe_request("PUT", PATH_INDEX.format(collection_name=quote(COLL, safe="")),
                                  json={"field_name": "genre", "field_schema": "keyword"},
                                  timeout=60, params={"wait": "true"})
        if st != 200:
            print(f"setup keyword index on genre failed status={st}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
            return

        # ---- Leg A: indexed-key success with exact value/count ground truth ----
        st, body, raw = safe_request("POST", PATH_FACET.format(collection_name=quote(COLL, safe="")),
                                     json={"key": "genre"}, timeout=60)
        print(f"[leg A facet key=genre] status={st} raw={str(raw)[:500]}")
        v = judge_success_leg("leg A facet key=genre", st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return

        # ---- Leg B: facet on a never-created collection must be 404 ----
        st, body, raw = safe_request("POST", PATH_FACET.format(collection_name=quote(COLL_MISSING, safe="")),
                                     json={"key": "genre"}, timeout=60)
        print(f"[leg B facet on missing collection] status={st} raw={str(raw)[:300]}")
        if st <= 0 or 500 <= st <= 599:
            v = transport_or_5xx("leg B missing collection", st, raw)
            if v is not None:
                print("VERDICT: " + v)
            return
        if st == 404:
            print(f"OK(404): missing collection answered 404: {str(raw)[:200]}")
            print("OK: leg A exact counts verified, leg B 404 verified")
            print("VERDICT: NO_DEFECT")
            return
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - facet on the "
              f"never-created collection returned {st} instead of the documented 404: "
              f"{str(raw)[:300]}")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
