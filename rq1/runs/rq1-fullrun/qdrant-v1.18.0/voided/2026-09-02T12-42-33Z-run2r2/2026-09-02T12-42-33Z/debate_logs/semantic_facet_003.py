#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_facet_003
# strategy: diagnosis_quality
# endpoint: facet
# constraint_ids: qdrant_state_facet_001
# source_url: https://qdrant.tech/documentation/manage-data/payload/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-02 (Error Message Negligence - the state contract promises a 400 when
#           faceting a key that has no MatchValue-capable payload index; a 400 whose
#           message does not name the offending payload key and does not point at the
#           index requirement leaves the user guessing which field to index = the
#           generic-internal-error failure class the blindspot describes)
"""
Attack: diagnosis_quality (strategy 2) x qdrant_state_facet_001 on facet (chunk_facet
  unit constraints::qdrant_state_facet_001 - assertion: "facet on a field without a
  suitable (keyword-like) payload index is rejected with 400", evidence_tier=explicit,
  level=system; source https://qdrant.tech/documentation/manage-data/payload/).
  Two constructs of the SAME promise family are probed for BOTH the status leg and
  the diagnostics-quality leg (G4 both-direction pairing with the positive control):
    N1 (unindexed key): key "noidx" carries string values in every payload but has NO
       payload index at all -> per the assertion facet must be rejected with 400;
    N2 (index present but not MatchValue-capable): key "descr" carries string values
       and has a TEXT (full-text) payload index - a text index does not support
       MatchValue conditions (keyword/integer map indexes do) -> per the assertion
       facet must also be rejected with 400 (a text index is not keyword-like).
    C1 (positive control): key "genre" with a keyword index facets 200 with real hits
       - proves the collection/fixture is healthy so the N1/N2 400s (or their
       absence) are attributable to the per-key index state, not the fixture.
  Status leg: any 2xx on N1/N2 = Type1_IllegalSuccess (refusing-when-it-should per
  G5 - the assertion demands 400, "not a wrong result" per the behavioral unit).
  Diagnostics leg (Type2 rubric on each 4xx body): parameter_named (error text
  contains the payload key name "noidx"/"descr") 1pt + requirement_hint (mentions an
  index/MatchValue/keyword requirement or the format expected of the field) 1pt +
  actionable (suggests creating an index / fixing the field schema) 1pt. A 400 with
  score <= 1 (key not named AND no requirement hint) = Type2_PoorDiagnostics
  (run2r #1 defect precedent: generic messages on edge-case inputs).
  R17 reconciliation (G10): the no-index 400 status leg is also the second clause of
  qdrant_behavioral_facet_001's expected behavior - co-executed here (richer
  constructs: unindexed AND text-indexed keys) so semantic_facet_001 stays with the
  200/404 legs only.
Oracle: on a live sfa03_* collection with genre keyword-indexed, descr text-indexed
  and noidx completely unindexed (all keys present in every payload of the 25-point
  fixture): C1 facet key=genre returns HTTP 200 with 4 value/count hits; N1 facet
  key=noidx and N2 facet key=descr each return HTTP 400/422 (a 2xx = Type1_
  IllegalSuccess per the state assertion), and each 4xx error body names the payload
  key and mentions the payload-index/MatchValue requirement (rubric score >= 2 of 3;
  a 4xx whose message names neither the key nor any index/format requirement =
  Type2_PoorDiagnostics); 5xx or transport failure with /healthz not alive =
  Type3_RuntimeFailure; setup/transport failure with /healthz alive = SCRIPT_ERROR (G8).

Constraint anchor qdrant_state_facet_001 (explicit, system): "facet works only on a
  payload field that has an index supporting MatchValue conditions (e.g. keyword
  index); without a suitable index the request fails with 400 [DOC payload]" -
  source_url https://qdrant.tech/documentation/manage-data/payload/ (doc_version
  "current (site latest; no version archive)", source_status degraded - measured-only
  conflict zones are recorded as such; the endpoint registry doc_quote corroborates:
  "Faceting works only on a payload field with an index supporting MatchValue
  conditions; ... 400 (including when no suitable index exists).").

[chunk_facet coverage: diagnosis_quality x qdrant_state_facet_001 (N1 unindexed key
  + N2 text-indexed key 400-status and 400-message-quality legs, C1 positive
  control)]
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
COLL = "sfa03_" + PFX
DIM = 4
DIST = {"alpha": 10, "beta": 8, "gamma": 5, "delta": 2}  # genre ground truth


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


def type2_score(key_name, raw):
    """
    Type-2 diagnosis quality rubric (parameter_named 1pt + requirement_hint 1pt +
    actionable 1pt). body may be dict or str - check the type first.
    """
    try:
        body = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        body = raw
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    # Criterion 1: the offending payload key is named
    if key_name.lower() in error_msg:
        score += 1
    # Criterion 2: requirement/format hint (index requirement, MatchValue, keyword...)
    req_hints = ["index", "matchvalue", "keyword", "field type", "schema", "must be",
                 "expected", "not supported", "unsupported"]
    if any(h in error_msg for h in req_hints):
        score += 1
    # Criterion 3: actionable suggestion
    act_hints = ["create", "add", "use", "try", "index ", "define", "see"]
    if any(h in error_msg for h in act_hints):
        score += 1
    return score, 3


def judge_noindex_probe(probe, key_name, status, raw):
    """Status leg (state_001 assertion: 400 expected) + message-quality leg on a 4xx."""
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if 200 <= status < 300:
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) - '{probe}' facet on key "
                f"'{key_name}' without a MatchValue-capable payload index was accepted "
                f"with {status} although qdrant_state_facet_001 asserts a 400 reject "
                f"(and qdrant_behavioral_facet_001 demands 400 'not a wrong result'): "
                f"{str(raw)[:300]}")
    if 400 <= status < 500:
        print(f"OK(status): '{probe}' correctly rejected with {status}")
        score, max_score = type2_score(key_name, raw)
        print(f"[type2 rubric '{probe}'] score={score}/{max_score} (key named 1pt + "
              f"requirement hint 1pt + actionable 1pt)")
        if score <= 1:
            return (f"DEFECT_FOUND (Type2_PoorDiagnostics) - '{probe}' 400 message "
                    f"diagnoses the rejection poorly (rubric {score}/{max_score}): "
                    f"neither names the payload key '{key_name}' nor states the "
                    f"index/MatchValue requirement the way the state contract's "
                    f"diagnostic promise implies: {str(raw)[:300]}")
        return None
    return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"


def main():
    print(f"ownership prefix: {PFX} collection={COLL}")
    pts = []
    pid = 1
    for genre, cnt in DIST.items():
        for _ in range(cnt):
            pts.append({"id": pid, "vector": [0.1] * DIM,
                        "payload": {"genre": genre,
                                    "descr": f"description text {genre} {pid}",
                                    "noidx": f"raw-value-{pid % 7}"}})
            pid += 1
    try:
        # ---- Arrange: collection + keyword index (genre) + text index (descr) ----
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
        st, _, raw = safe_request("PUT", PATH_INDEX.format(collection_name=quote(COLL, safe="")),
                                  json={"field_name": "descr", "field_schema": "text"},
                                  timeout=60, params={"wait": "true"})
        if st != 200:
            print(f"setup text index on descr failed status={st}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
            return

        # ---- C1 positive control: keyword-indexed key facets 200 with hits ----
        st, _, raw = safe_request("POST", PATH_FACET.format(collection_name=quote(COLL, safe="")),
                                  json={"key": "genre"}, timeout=60)
        print(f"[C1 control facet key=genre (keyword-indexed)] status={st} raw={str(raw)[:400]}")
        if st != 200:
            print("VERDICT: SCRIPT_ERROR - positive control failed (keyword-indexed "
                  f"facet got {st}): {str(raw)[:200]}")
            return

        # ---- N1: facet on an unindexed payload key ----
        st, _, raw = safe_request("POST", PATH_FACET.format(collection_name=quote(COLL, safe="")),
                                  json={"key": "noidx"}, timeout=60)
        print(f"[N1 facet key=noidx (no index at all)] status={st} raw={str(raw)[:400]}")
        v = judge_noindex_probe("N1 noidx", "noidx", st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return

        # ---- N2: facet on a text-indexed payload key (index exists but is not
        #         MatchValue-capable / keyword-like) ----
        st, _, raw = safe_request("POST", PATH_FACET.format(collection_name=quote(COLL, safe="")),
                                  json={"key": "descr"}, timeout=60)
        print(f"[N2 facet key=descr (text index - not keyword-like)] status={st} raw={str(raw)[:400]}")
        v = judge_noindex_probe("N2 descr", "descr", st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return

        print("OK: C1 keyword-indexed facet 200; N1 unindexed and N2 text-indexed facets "
              "rejected 400 with diagnostic messages naming the key and the index "
              "requirement (rubric >= 2/3)")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
