#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_facet_005
# strategy: behavioral_contract
# endpoint: facet
# constraint_ids: qdrant_range_facet_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/facet
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the versioned OpenAPI documents the facet
#           limit default "Max number of hits to return. Default is 10."; a runtime
#           that ignores the default (returns all distinct values when limit is
#           omitted) or truncates at a different cap silently drifts from the
#           documented aggregation semantics on the most common call shape - the
#           omitted-limit call every analytics dashboard makes)
"""
Attack: behavioral_contract (strategy 1) x qdrant_range_facet_001 on facet
  (chunk_facet unit constraints::qdrant_range_facet_001 - "facet limit minimum 1
  (default 10); the v-1-18-x spec documents no maximum", evidence_tier=explicit,
  level=endpoint). The DEFAULT and the SELECTION semantics of the limit parameter are
  only falsifiable with a fixture holding MORE distinct values than the default - a
  fixture with 12 distinct genre values whose counts are all distinct (12,11,...,1)
  over 78 points:
    D1 (default materialization): limit omitted entirely -> the documented default 10
      must truncate the response to EXACTLY the 10 highest-count values - any other
      hit count (e.g. all 12 = default silently unset / no truncation) = the "Default
      is 10" claim contradicted = Type4_StateLogicViolation (doc-drift family, run2r
      #1 defects 9/11/14 precedent: documented default vs materialized behavior).
    D2 (no maximum face): explicit limit=12 (>= number of distinct values) -> HTTP
      200 with all 12 distinct values present and complete (no undocumented cap at
      10, no error for exceeding the default).
    D3 (truncation selection semantics): limit=3 -> HTTP 200 with EXACTLY the 3
      highest-count values {g12:12, g11:11, g10:10} - "limit" selects the most
      frequent values; a response containing a lower-count value instead of a
      higher-count one = the limit feature returns the wrong aggregate subset
      (Type4_StateLogicViolation).
  The hit SET is the adjudication key (value:count pairs compared as sets - no
  response-order claim; distinct fixture counts make each top-N set unambiguous).
  R17 reconciliation (G10): boundary_facet_001 owns the below-min rejection + the
  at-min/mid acceptance face of this constraint with a 4-distinct fixture (which
  cannot falsify the default-10 claim); this script owns the default-materialization
  and top-N selection faces with a 12-distinct fixture. boundary_facet_002 owns the
  crash-safety face of qdrant_resource_facet_limit_001 (huge limits) - no
  duplication here.
Oracle: on a live sfa05_* collection with genre keyword-indexed holding exactly 12
  distinct values g1..g12 with counts 1..12 respectively (78 points, no deletions):
  facet {key: genre} with limit omitted returns HTTP 200 with result.hits of length
  exactly 10 whose value/count set equals {g12:12, g11:11, g10:10, g9:9, g8:8,
  g7:7, g6:6, g5:5, g4:4, g3:3} (the default-10 materialization; length != 10 on a
  200 = Type4_StateLogicViolation); facet {key: genre, limit: 12} returns 200 with
  all 12 values complete; facet {key: genre, limit: 3} returns 200 with exactly
  {g12:12, g11:11, g10:10}; any 4xx on these legal probes = Type1_IllegalRejection;
  5xx or transport failure with /healthz not alive = Type3_RuntimeFailure;
  setup/transport failure with /healthz alive = SCRIPT_ERROR (G8).

Constraint anchor qdrant_range_facet_001 (explicit, endpoint): "facet limit minimum 1
  (default 10); the v-1-18-x spec documents no maximum" - source_url
  https://api.qdrant.tech/v-1-18-x/api-reference/points/facet (OpenAPI
  FacetRequest.limit description "Max number of hits to return. Default is 10.").

[chunk_facet coverage: behavioral_contract x qdrant_range_facet_001 (default-10
  materialization D1, no-maximum completeness D2, top-N selection semantics D3)]
"""
import json
import os
import sys
import uuid
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
PATH_FACET = "/collections/{collection_name}/facet"
PATH_CREATE = "/collections/{collection_name}"
PATH_DELETE = "/collections/{collection_name}"
PATH_UPSERT = "/collections/{collection_name}/points"
PATH_INDEX = "/collections/{collection_name}/index"

PFX = uuid.uuid4().hex[:8]
COLL = "sfa05_" + PFX
DIM = 4
# 12 distinct genre values; value g<cnt> appears cnt times (cnt 1..12). Distinct
# counts -> each top-N set is unambiguous. Expected maps are DERIVED here, then the
# fixture is built from the SAME mapping (client-side list = inserted ground truth).
N_VALUES = 12
GENRE_COUNT = {f"g{cnt}": cnt for cnt in range(1, N_VALUES + 1)}  # g1:1 ... g12:12
EXPECTED_FULL = dict(GENRE_COUNT)  # 12 entries, all values present
TOP3 = {k: GENRE_COUNT[k] for k in ("g12", "g11", "g10")}
TOP10 = {f"g{cnt}": cnt for cnt in range(N_VALUES, N_VALUES - 10, -1)}  # g12..g3
N_POINTS = sum(GENRE_COUNT.values())  # 78


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
    """Lightweight liveness probe (G8)."""
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
    """Envelope parse per response_shape: result.hits[] with {value, count}."""
    try:
        body = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None, f"response not JSON: {str(raw)[:200]}"
    if not isinstance(body, dict):
        return None, f"response not an object: {str(raw)[:200]}"
    res = body.get("result")
    if not isinstance(res, dict):
        return None, f"envelope result missing/not object: {str(raw)[:200]}"
    for key in ("hits", "facet_hits"):  # facet_hits = measured-only alias tolerance
        if isinstance(res.get(key), list):
            return res[key], None
    return None, f"result.hits missing/not array: {str(raw)[:250]}"


def judge_limit_probe(probe, expected_map, status, raw):
    """Legal limit probe: 200 + exact value/count set == expected_map (length
    derived from the map). Hit sets compared as maps -> no response-order claim."""
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if 400 <= status < 500:
        return (f"DEFECT_FOUND (Type1_IllegalRejection) - '{probe}' documented-legal "
                f"facet request rejected with {status}: {str(raw)[:250]}")
    if status != 200:
        return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"
    hits, err = parse_hits(raw)
    if err:
        return f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' HTTP 200 but {err}"
    got = {}
    for h in hits:
        if not isinstance(h, dict) or "value" not in h or "count" not in h:
            return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' hit entry "
                    f"lacks value/count: {str(h)[:200]}")
        got[str(h.get("value"))] = h.get("count")
    if got != expected_map:
        return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' facet hits "
                f"mismatch: got {json.dumps(got)} (len {len(got)}), expected "
                f"{json.dumps(expected_map)} (len {len(expected_map)}): {str(raw)[:300]}")
    return None


def main():
    print(f"ownership prefix: {PFX} collection={COLL}")
    # fixture: g<cnt> repeated cnt times; ids sequential
    pts = []
    pid = 1
    for genre, cnt in GENRE_COUNT.items():
        for _ in range(cnt):
            pts.append({"id": pid, "vector": [0.1] * DIM, "payload": {"genre": genre}})
            pid += 1
    if len(pts) != N_POINTS:
        print(f"fixture self-check failed: {len(pts)} points != {N_POINTS}")
        print("VERDICT: SCRIPT_ERROR - fixture construction bug, no defect conclusion")
        return
    try:
        # ---- Arrange: collection + keyword index + fixture ----
        st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                                  json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
        if st not in (200, 201):
            print(f"setup create {COLL} failed status={st}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
            return
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

        # ---- D1: omitted limit must materialize the documented default 10 ----
        st, _, raw = safe_request("POST", PATH_FACET.format(collection_name=quote(COLL, safe="")),
                                  json={"key": "genre"}, timeout=60)
        print(f"[D1 facet key=genre (limit omitted, default 10)] status={st} raw={str(raw)[:400]}")
        v = judge_limit_probe("D1 omitted-limit default 10", TOP10, st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return

        # ---- D2: explicit limit=12 (no documented maximum) must return all 12 ----
        st, _, raw = safe_request("POST", PATH_FACET.format(collection_name=quote(COLL, safe="")),
                                  json={"key": "genre", "limit": 12}, timeout=60)
        print(f"[D2 facet key=genre limit=12] status={st} raw={str(raw)[:400]}")
        v = judge_limit_probe("D2 limit=12 full set", EXPECTED_FULL, st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return

        # ---- D3: limit=3 must select exactly the 3 highest-count values ----
        st, _, raw = safe_request("POST", PATH_FACET.format(collection_name=quote(COLL, safe="")),
                                  json={"key": "genre", "limit": 3}, timeout=60)
        print(f"[D3 facet key=genre limit=3] status={st} raw={str(raw)[:400]}")
        v = judge_limit_probe("D3 limit=3 top-3", TOP3, st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return

        print("OK: omitted-limit facet returned exactly the documented default 10 "
              "hits; limit=12 returned the complete 12-value set; limit=3 selected "
              "exactly the 3 highest-count values")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
