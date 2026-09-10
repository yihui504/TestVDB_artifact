#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_facet_002
# strategy: filter_semantics
# endpoint: facet
# constraint_ids: qdrant_behavioral_facet_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/facet
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the FacetRequest.filter contract "only
#           consider points that satisfy these conditions" promises subset-restricted
#           aggregation; the standing R17 lesson flags facet as the search-adjacent
#           semantic endpoint where filter semantics apply. A facet whose counts are
#           computed over the whole collection while a filter is present = silent
#           wrong-result drift, the exact failure class docs-vs-impl drift hides.)
"""
Attack: filter_semantics (strategy 7) x qdrant_behavioral_facet_001 on facet
  (chunk_facet unit assertions::qdrant_behavioral_facet_001 - the OpenAPI
  FacetRequest.filter description: "Filter conditions - only consider points that
  satisfy these conditions", evidence_tier=explicit, level=endpoint; also the
  search-adjacent standing lesson R17: facet on filtered subsets). Facet on a
  keyword-indexed key with a Filter attached must aggregate counts over the filtered
  subset ONLY - one filter construct per probe:
    F1 must   year == 2023 (match on integer payload year)
    F2 must   genre == alpha (match on the indexed facet key itself)
    F3 must   year >= 2024 (range, lower bound)
    F4 must   year <= 2020 (range, upper bound)
    F5 must_not year == 2022 (exclusion)
  Each probe's expected {value:count} map is derived python-side from the SAME
  deterministic fixture point list that was upserted (client-side list = ground
  truth of the inserted state; server response compared against it).
  Subset invariant (metamorphic fold of strategy 6): for every genre value returned
  by a filtered facet, its filtered count must be <= its unfiltered count (facet on
  the same fixture without filter) - a filter that ever INCREASES a value's count is
  structurally impossible under correct subset semantics.
  R17 reconciliation (G10): the 400-no-suitable-index clause of the behavioral unit
  is executed in semantic_facet_003 (diagnosis_quality x qdrant_state_facet_001);
  this script owns only the filter-semantics face of the unit.
Oracle: on a live sfa02_* collection with genre keyword-indexed and 25 points
  (genre alpha=10/beta=8/gamma=5/delta=2, year = 2020 + point_id % 5), every facet
  {key: genre, filter: F1..F5} returns HTTP 200 whose result.hits {value:count} set
  equals the python-computed Counter over the filter-matching subset exactly (any
  4xx on these legal requests = Type1_IllegalRejection; any missing/extra hit or
  count mismatch on a 200 = Type4_StateLogicViolation; a filtered count exceeding
  the unfiltered count for the same value = Type4_StateLogicViolation); a 5xx or
  transport failure with /healthz not alive = Type3_RuntimeFailure; setup/transport
  failure with /healthz alive = SCRIPT_ERROR (G8).

Constraint anchor qdrant_behavioral_facet_001 (explicit, endpoint) - full assertion
  text: "facet on an indexed key returns HTTP 200 with value/count hits; facet on a
  key without a MatchValue-capable index returns 400, not a wrong result"; filter
  semantics leg sourced from the versioned OpenAPI FacetRequest.filter description
  quoted above (https://api.qdrant.tech/v-1-18-x/api-reference/points/facet).

[chunk_facet coverage: filter_semantics x qdrant_behavioral_facet_001 (facet filter
  subset-count semantics F1-F5 + unfiltered-subset monotonic invariant)]
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
PATH_FACET = "/collections/{collection_name}/facet"
PATH_CREATE = "/collections/{collection_name}"
PATH_DELETE = "/collections/{collection_name}"
PATH_UPSERT = "/collections/{collection_name}/points"
PATH_INDEX = "/collections/{collection_name}/index"

PFX = uuid.uuid4().hex[:8]
COLL = "sfa02_" + PFX
DIM = 4
DIST = {"alpha": 10, "beta": 8, "gamma": 5, "delta": 2}  # genre ground truth
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


def judge_filter_probe(probe, expected, unfiltered, status, raw):
    """Filtered facet: 200 + hits {value:count} == expected Counter; each returned
    value's count must be <= its unfiltered count (subset monotonicity)."""
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if 400 <= status < 500:
        return (f"DEFECT_FOUND (Type1_IllegalRejection) - '{probe}' documented-legal "
                f"filtered facet request rejected with {status}: {str(raw)[:250]}")
    if status != 200:
        return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"
    hits, err = parse_hits(raw)
    if err:
        return f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' HTTP 200 but {err}"
    got = {}
    for h in hits:
        if not isinstance(h, dict) or "value" not in h or "count" not in h:
            return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' hit entry lacks "
                    f"value/count: {str(h)[:200]}")
        got[str(h.get("value"))] = h.get("count")
    if got != dict(expected):
        return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' filtered facet "
                f"counts mismatch: got {json.dumps(got)}, expected "
                f"{json.dumps(dict(expected))} (filter must restrict the aggregation "
                f"to the matching subset): {str(raw)[:300]}")
    for value, cnt in got.items():
        if unfiltered.get(value, 0) < cnt:
            return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' value {value} "
                    f"filtered count {cnt} exceeds its unfiltered count "
                    f"{unfiltered.get(value, 0)} - subset monotonicity violated: {str(raw)[:300]}")
    return None


def main():
    print(f"ownership prefix: {PFX} collection={COLL}")
    # deterministic fixture: 25 points; year = 2020 + (pid % 5) -> each (genre, year)
    # combination count is a pure function of the construction loop below
    pts = []
    pid = 1
    for genre, cnt in DIST.items():
        for _ in range(cnt):
            pts.append({"id": pid, "vector": [0.1] * DIM,
                        "payload": {"genre": genre, "year": 2020 + (pid % 5)}})
            pid += 1
    all_genre = Counter(p["payload"]["genre"] for p in pts)
    if dict(all_genre) != DIST:
        print(f"fixture self-check failed: {dict(all_genre)} != {DIST}")
        print("VERDICT: SCRIPT_ERROR - fixture construction bug, no defect conclusion")
        return
    # python-side ground truth for each filter construct
    expected = {
        "F1 year==2023": Counter(p["payload"]["genre"] for p in pts if p["payload"]["year"] == 2023),
        "F2 genre==alpha": Counter(p["payload"]["genre"] for p in pts if p["payload"]["genre"] == "alpha"),
        "F3 year>=2024": Counter(p["payload"]["genre"] for p in pts if p["payload"]["year"] >= 2024),
        "F4 year<=2020": Counter(p["payload"]["genre"] for p in pts if p["payload"]["year"] <= 2020),
        "F5 must_not year==2022": Counter(p["payload"]["genre"] for p in pts if p["payload"]["year"] != 2022),
    }
    filters = {
        "F1 year==2023": {"must": [{"key": "year", "match": {"value": 2023}}]},
        "F2 genre==alpha": {"must": [{"key": "genre", "match": {"value": "alpha"}}]},
        "F3 year>=2024": {"must": [{"key": "year", "range": {"gte": 2024}}]},
        "F4 year<=2020": {"must": [{"key": "year", "range": {"lte": 2020}}]},
        "F5 must_not year==2022": {"must_not": [{"key": "year", "match": {"value": 2022}}]},
    }
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

        # ---- unfiltered reference facet (needed for the subset invariant) ----
        st, _, raw = safe_request("POST", PATH_FACET.format(collection_name=quote(COLL, safe="")),
                                  json={"key": "genre"}, timeout=60)
        print(f"[reference facet key=genre (no filter)] status={st} raw={str(raw)[:400]}")
        if st != 200:
            print(f"VERDICT: SCRIPT_ERROR - reference facet failed status={st}: {str(raw)[:200]}")
            return
        ref_hits, err = parse_hits(raw)
        if err:
            print(f"VERDICT: SCRIPT_ERROR - reference facet parse failed: {err}")
            return
        unfiltered = {str(h.get("value")): h.get("count") for h in ref_hits if isinstance(h, dict)}

        # ---- Act: filtered facet probes ----
        for name in ("F1 year==2023", "F2 genre==alpha", "F3 year>=2024",
                     "F4 year<=2020", "F5 must_not year==2022"):
            body = {"key": "genre", "filter": filters[name]}
            st, _, raw = safe_request("POST",
                                      PATH_FACET.format(collection_name=quote(COLL, safe="")),
                                      json=body, timeout=60)
            print(f"[probe {name}] facet with filter -> status={st} raw={str(raw)[:400]}")
            v = judge_filter_probe(name, expected[name], unfiltered, st, raw)
            if v is not None:
                print("VERDICT: " + v)
                return
        print("OK: all five filtered-facet probes returned counts over the filtered "
              "subset only; subset monotonicity held")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
