#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_count_min_should_004
# strategy: strategy2 type/branch-boundary attack (min_should branch: required
#           paths of the chosen anyOf branch + degenerate empty conditions +
#           min_count value boundaries), semantic face per BS-01/BS-05
# endpoint: points+count
# constraint_ids: qdrant_behavioral_points_count_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/count-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust) + BS-05 (the threat model
#            lists 'empty filter with min_should' as the count-endpoint
#            blindspot; request_required_paths declares
#            filter.min_should.conditions AND filter.min_should.min_count as
#            required once the branch is invoked)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 min_should-branch x qdrant_behavioral_points_count_001 —
  the exact-count promise is probed through the min_should branch of Filter
  ({should?, min_should?, must?, must_not?} per contract data_types). Faces
  on a LIVE 12-point collection (8 berlin / 4 paris):
    F1 VALID branch positive control — {"conditions":[berlin],"min_count":1}
       -> 200 with count == 8 (proves the branch works before probing it).
    F2 required-path omission probe (INTENTIONAL: min_count missing from the
       invoked min_should branch; request_required_paths lists
       filter.min_should.min_count as required for this branch) -> 400/422
       clean; 2xx = Type1_IllegalSuccess (required branch field accepted
       missing — the count then rests on an undeclared default).
    F3 empty conditions + min_count=1 (BS-05 'empty filter with min_should')
       — logically UNSATISFIABLE (0 conditions available, 1 required):
       clean outcomes are 400/422 (validation) or 200 with count == 0
       (strict semantics); 200 with count == 12 is recorded as NOTE
       (empty-clause-ignored convention vs unsatisfiable semantics — judge
       call vs published docs); 5xx = Type3.
    F4 min_count=2 of [berlin(8), paris(4)] — no point carries both cities
       -> 200 with count == 0 (arithmetic-derived); other count = Type4.
    F5 min_count=0 with [berlin] — 'at least 0' imposes no constraint
       -> 200 with count == 12; 200 with count == 8 (0 silently treated as
       1) = Type4 signal; 400/422 recorded as NOTE (value-range judge call).
  [chunk_points+count coverage: strategy2 min_should-branch x
  qdrant_behavioral_points_count_001 (this script; plain filter type
  confusion in boundary_points_count_filter_type_003, exact type confusion
  in boundary_points_count_exact_type_005; baselines in
  boundary_points_count_all_001 / boundary_points_count_filter_arith_002,
  malformed bodies in boundary_points_count_malformed_006)]
Oracle: F1 -> 200 count==8; F2 -> 400/422 (2xx = Type1_IllegalSuccess);
  F3 -> 400/422 or 200 count==0 (200 count==12 = NOTE for judge); F4 ->
  200 count==0 (other 200 count = Type4_StateLogicViolation); F5 -> 200
  count==12 (200 count==8 = Type4_StateLogicViolation; 4xx = NOTE); any 5xx
  with /healthz alive = Type3_RuntimeFailure; transport failure ->
  /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_count_001).
Constraint: qdrant_behavioral_points_count_001 (bare id) — "exact=true
  (default) performs an exact count (slower); an omitted filter counts all
  points" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+count         -> POST /collections/{collection_name}/points/count
  collections+create   -> PUT  /collections/{collection_name}
  collections+delete   -> DELETE /collections/{collection_name}
  points+upsert        -> PUT  /collections/{collection_name}/points
  healthz              -> GET  /healthz
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
N_SEED = 12
BERLIN_N = 8
PARIS_N = 4  # BERLIN_N + PARIS_N == N_SEED
V = [0.1, 0.2, 0.3, 0.4]


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/ordering/timeout) via params= — never stuffed into the body.
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


def transport_dead(where):
    """Transport-branch liveness re-check (lightweight healthz face only)."""
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return False


BERLIN_COND = {"key": "city", "match": {"value": "berlin"}}
PARIS_COND = {"key": "city", "match": {"value": "paris"}}


def ms(conditions=None, min_count=None):
    """Build {"filter": {"min_should": {...}}} — omit keys by passing nothing."""
    inner = {"conditions": conditions}
    if min_count is not None:
        inner["min_count"] = min_count
    return {"filter": {"min_should": inner}}


coll = ""


def run_count(body, label):
    """POST one count request; returns (status, count_or_None, raw)."""
    s, b, raw = safe_request("POST", f"/collections/{coll}/points/count",
                             json=body, timeout=60)
    print(f"\n{label} -> status={s}")
    print(f"raw: {raw[:400]}")
    if s == -1:
        transport_dead(label)
        return None, None, None
    count = None
    if s == 200 and isinstance(b, dict) and isinstance(b.get("result"), dict):
        count = b["result"].get("count")
    return s, count, raw


def main():
    global coll
    tag = uuid.uuid4().hex[:8]
    coll = "bpcM4" + tag

    # Arrange: own collection + seed set (wait=true => durable before counting)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    points = []
    for i in range(1, N_SEED + 1):
        city = "berlin" if i <= BERLIN_N else "paris"
        points.append({"id": i, "vector": V, "payload": {"city": city}})
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": points}, params={"wait": "true"}, timeout=120)
    if s not in (200, 201):
        print(f"setup upsert failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        notes = []

        # ---- F1: valid min_should branch (positive control) ----
        s, count, raw = run_count(ms([BERLIN_COND], 1), "F1 min_should [berlin], min_count=1")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F1: valid "
                      f"min_should count returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F1 5xx and healthz down")
            return
        if not (200 <= s <= 299) or count != BERLIN_N:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F1: valid "
                  f"min_should branch must return 200 with count=={BERLIN_N}, "
                  f"got status={s} count={count}: {raw[:300]}")
            return
        print(f"F1: count == {count} == {BERLIN_N} (branch functional)")

        # ---- F2: required-path omission (min_count missing) — intentional probe ----
        s, count, raw = run_count(ms([BERLIN_COND], None),
                                  "F2 min_should conditions present, min_count MISSING "
                                  "(required-path omission probe)")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F2: "
                      f"min_count-omission probe returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F2 5xx and healthz down")
            return
        if 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F2: min_should "
                  f"branch accepted WITHOUT its required min_count path "
                  f"(request_required_paths: filter.min_should.min_count); count "
                  f"{count} rests on an undeclared default: {raw[:300]}")
            return
        print(f"F2: rejected with {s} (required path enforced)")

        # ---- F3: empty conditions + min_count=1 (unsatisfiable) ----
        s, count, raw = run_count(ms([], 1),
                                  "F3 min_should conditions=[], min_count=1 (unsatisfiable)")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F3: empty-"
                      f"conditions min_should returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F3 5xx and healthz down")
            return
        if 200 <= s <= 299:
            if count == 0:
                print("F3: 200 with count == 0 (strict unsatisfiable semantics)")
            elif count == N_SEED:
                notes.append("F3: 200 with count == N_SEED — empty-clause-ignored "
                             "convention vs unsatisfiable min_count=1 semantics "
                             "(judge call against published filtering docs)")
                print("F3: NOTE — 200 count == N_SEED recorded for the judge")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F3: "
                      f"empty conditions cannot match a strict subset; only 0 "
                      f"(unsatisfiable) or {N_SEED} (clause ignored) are "
                      f"defensible, got {count}: {raw[:300]}")
                return
        else:
            print(f"F3: rejected with {s} (clean validation of empty conditions)")

        # ---- F4: min_count=2 of [berlin, paris] -> 0 (arithmetic-derived) ----
        s, count, raw = run_count(ms([BERLIN_COND, PARIS_COND], 2),
                                  "F4 min_should [berlin,paris], min_count=2")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F4: "
                      f"min_count=2 count returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F4 5xx and healthz down")
            return
        if not (200 <= s <= 299):
            notes.append(f"F4: status {s} (min_count == len(conditions) edge "
                         f"rejected — value-range judge call)")
            print(f"F4: NOTE — {s} recorded for the judge")
        elif count != 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F4: no "
                  f"seeded point carries both city values, 'at least 2 of "
                  f"[berlin, paris]' must count 0, got {count}: {raw[:300]}")
            return
        else:
            print("F4: count == 0 (arithmetic-derived: no point satisfies both)")

        # ---- F5: min_count=0 with [berlin] -> no constraint -> N_SEED ----
        s, count, raw = run_count(ms([BERLIN_COND], 0),
                                  "F5 min_should [berlin], min_count=0")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F5: "
                      f"min_count=0 count returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F5 5xx and healthz down")
            return
        if not (200 <= s <= 299):
            notes.append(f"F5: status {s} (min_count=0 rejected — value-range "
                         f"judge call)")
            print(f"F5: NOTE — {s} recorded for the judge")
        elif count == N_SEED:
            print(f"F5: count == {N_SEED} (min_count=0 imposes no constraint)")
        elif count == BERLIN_N:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F5: "
                  f"min_count=0 silently behaves as min_count=1 (count "
                  f"{BERLIN_N} instead of {N_SEED}): {raw[:300]}")
            return
        else:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F5: "
                  f"min_count=0 must impose no constraint (expected "
                  f"{N_SEED}), got {count}: {raw[:300]}")
            return

        if notes:
            for n in notes:
                print(f"NOTE (judge call): {n}")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
