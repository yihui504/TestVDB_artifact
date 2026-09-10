#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_batch_404_diag_007
# strategy: strategy2 error-diagnostics quality attack (Type-2) — the 404
#           promise's message quality and the validation-error quality on
#           the batch query face
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence — the boundary lane pinned the
#            404 STATUS on this face (404_002); this script grades the
#            MESSAGE: does the rejection tell the user WHAT is wrong and HOW
#            to fix it)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy2 diagnosis quality (Type2) x
  qdrant_behavioral_points_query_batch_001 — the assertion carries an
  explicit error promise ("404 for a missing collection"); the boundary-lane
  script boundary_points_query_batch_404_002 pinned the STATUS leg, so this
  script attacks the diagnostics QUALITY of the two rejection channels on
  the batch query face (Round-2+ Type2 focus):
    D1 missing collection: batch on a never-created collection name ->
       EXACTLY 404 per the promise; the error message is graded with the
       3-point rubric (criterion 1: the missing resource is named — the
       collection name or the word "collection"; criterion 2: a
       format/context hint; criterion 3: an actionable suggestion). A 2xx
       here would violate the 404 promise but that oracle is OWNED by the
       boundary script — recorded as NOTE cross-ref only, no duplicate
       adjudication.
    D2 validation error quality: existing collection, single-entry batch
       with limit=0 (schema minimum 1) -> 4xx expected; the message is
       graded (criterion 1: names the offending parameter "limit";
       criterion 2: bound hint e.g. at-least/minimum 1; criterion 3:
       actionable). A 200 (acceptance) has no message to grade — NOTE
       cross-ref to semantic_points_query_batch_perelem_limit_001 M-leg
       which owns the acceptance oracle.
    D3 precedence probe (NOTE only): missing collection AND limit=0 entry
       — which error wins (404 vs 422) is recorded for the judge; no
       defect claim either way.
  A 4xx whose message scores 0/3 (names nothing, hints nothing) =
  DEFECT_FOUND (Type2_PoorDiagnostics); any score >= 1 = NO_DEFECT with
  the score reported.
  [chunk_points+query+batch semantic coverage (7 scripts): search_correctness
  per-entry limit + k-nearest prefix + mixed invalid-entry atomicity +
  empty-searches N-in/N-out x behavioral_points_query_batch_001
  (perelem_limit_001); metamorphic per-entry offset window x
  behavioral_points_query_batch_001 (perelem_offset_002); filter_semantics
  per-entry exact-set closure + bleed isolation x
  behavioral_points_query_batch_001 (perelem_filter_003); behavioral_contract
  mixed-variant per-entry dispatch x behavioral_points_query_batch_001
  (mixed_variant_004); type_coercion R33-family dual-key query oneOf
  cross-face x behavioral_points_query_batch_001 (dualkey_005); metamorphic
  single vs batch-of-1 + VectorInput shorthand x
  behavioral_points_query_batch_001 (single_vs_batch_006); diagnosis_quality
  404 + validation message rubric x behavioral_points_query_batch_001
  (this)]
Oracle: D1 -> EXACTLY 404 with a message scoring >= 1/3 on the rubric
  (0/3 = Type2_PoorDiagnostics DEFECT; 2xx = NOTE, status oracle owned by
  boundary_points_query_batch_404_002); D2 -> 4xx with a message scoring
  >= 1/3 (0/3 = Type2 DEFECT; 200 = NOTE, acceptance oracle owned by
  semantic_points_query_batch_perelem_limit_001 M-leg); D3 -> disposition
  recorded as NOTE only (either precedence defensible); 5xx with /healthz
  alive = Type3_RuntimeFailure; transport failure -> /healthz liveness
  re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_query_batch_001).
Constraint: qdrant_behavioral_points_query_batch_001 (bare id) — "executes
  multiple queries in one call; returns 200 with a list of per-query results;
  404 for a missing collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+batch  -> POST /collections/{collection_name}/points/query/batch
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
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
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def bail_transport(where):
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")


def handle_5xx(rs, rraw, leg):
    if not (500 <= rs <= 599):
        return False
    alive, _, _ = healthz_alive()
    if alive:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{leg}]: {rs} "
              f"with service alive: {rraw[:300]}")
    else:
        print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
    return True


def check_error_quality(body, expected_param, extra_named=None):
    """
    Type-2 diagnosis quality rubric (session convention):
    - criterion 1: the offending resource/parameter is named
    - criterion 2: a format/range/context hint
    - criterion 3: an actionable suggestion
    body may be dict (JSON) or str (non-JSON).
    """
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    detail = []

    named = expected_param.lower() in error_msg or (
        extra_named and any(x.lower() in error_msg for x in extra_named))
    if named:
        score += 1
        detail.append("named=1")
    else:
        detail.append("named=0")

    format_hints = ["must be", "expected", "should be", "valid", "range",
                    "type", "positive", "non-zero", "at least", "minimum",
                    "doesn't exist", "does not exist", "not found"]
    if any(h in error_msg for h in format_hints):
        score += 1
        detail.append("hint=1")
    else:
        detail.append("hint=0")

    action_hints = ["correct", "try", "use", "change", "specify", "provide",
                    "create", "check"]
    if any(h in error_msg for h in action_hints):
        score += 1
        detail.append("action=1")
    else:
        detail.append("action=0")

    return score, " ".join(detail)


def main():
    tag = uuid.uuid4().hex[:8]
    missing = "spqbMiss7" + uuid.uuid4().hex[:12]   # never created
    coll = "spqbQ7" + tag

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": [{"id": 951,
                                                   "vector": [1.0, 0.0, 0.0, 0.0]}]},
                                 params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        valid_searches = [{"query": {"nearest": [0.0, 0.0, 0.0, 0.0]},
                           "params": {"exact": True}, "limit": 1}]

        # ---- D1: missing collection, valid body -> 404 + message quality ----
        s, body, raw = safe_request("POST", f"/collections/{missing}/points/query/batch",
                                    json={"searches": valid_searches}, timeout=60)
        print(f"D1 missing collection -> status={s}")
        print(f"raw: {raw[:350]}")
        if s == -1:
            bail_transport("D1")
            return
        if handle_5xx(s, raw, "D1"):
            return
        d1_score = None
        if s == 404:
            d1_score, d1_detail = check_error_quality(body, missing,
                                                       extra_named=["collection"])
            print(f"D1 404 message quality: {d1_score}/3 ({d1_detail})")
            if d1_score == 0:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — D1: 404 "
                      f"on a missing collection whose message names neither the "
                      f"collection nor any remediation: {raw[:250]}")
                return
        elif 200 <= s <= 299:
            print("NOTE D1: 2xx on a missing collection — the 404-status oracle "
                  "is owned by boundary_points_query_batch_404_002 (no "
                  "duplicate adjudication here); no message to grade")
        elif 400 <= s <= 499:
            d1_score, d1_detail = check_error_quality(body, missing,
                                                       extra_named=["collection"])
            print(f"NOTE D1: non-404 4xx ({s}) on a missing collection — "
                  f"promise-shape mismatch recorded for the judge; message "
                  f"quality {d1_score}/3 ({d1_detail})")
        else:
            print(f"VERDICT: SCRIPT_ERROR — D1 unexpected status {s}; no defect conclusion")
            return

        # ---- D2: existing collection, limit=0 entry -> 4xx + message quality ----
        s, body, raw = safe_request("POST", f"/collections/{coll}/points/query/batch",
                                    json={"searches": [{"query": {"nearest": [0.0, 0.0, 0.0, 0.0]},
                                                        "params": {"exact": True},
                                                        "limit": 0}]}, timeout=60)
        print(f"D2 limit=0 entry -> status={s}")
        print(f"raw: {raw[:350]}")
        if s == -1:
            bail_transport("D2")
            return
        if handle_5xx(s, raw, "D2"):
            return
        if 400 <= s <= 499:
            d2_score, d2_detail = check_error_quality(body, "limit")
            print(f"D2 4xx message quality: {d2_score}/3 ({d2_detail})")
            if d2_score == 0:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — D2: "
                      f"rejection of limit=0 (schema minimum 1) whose message "
                      f"names neither the parameter nor any bound: {raw[:250]}")
                return
        elif 200 <= s <= 299:
            print("NOTE D2: limit=0 entry ACCEPTED with 2xx — the acceptance "
                  "oracle is owned by semantic_points_query_batch_perelem_limit_001 "
                  "M-leg (no duplicate adjudication here); no message to grade")
        else:
            print(f"VERDICT: SCRIPT_ERROR — D2 unexpected status {s}; no defect conclusion")
            return

        # ---- D3: precedence probe (NOTE only) ----
        s, body, raw = safe_request("POST", f"/collections/{missing}/points/query/batch",
                                    json={"searches": [{"query": {"nearest": [0.0, 0.0, 0.0, 0.0]},
                                                        "params": {"exact": True},
                                                        "limit": 0}]}, timeout=60)
        print(f"D3 missing collection + limit=0 -> status={s}")
        print(f"raw: {raw[:350]}")
        if s == -1:
            bail_transport("D3")
            return
        if handle_5xx(s, raw, "D3"):
            return
        print(f"NOTE D3: error precedence on (missing collection, invalid "
              f"entry) = {s} — either 404-first or validation-first is "
              f"defensible; disposition recorded for the judge, no claim")

        print(f"diagnostics quality summary: D1 {'graded ' + str(d1_score) + '/3' if d1_score is not None else 'no 4xx message'}; "
              f"D2 graded above")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
