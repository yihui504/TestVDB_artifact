#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_count_exact_type_005
# strategy: strategy2 type-boundary attack (exact boolean parameter type
#           confusion) + strategy4 special-value face on the documented
#           approximate face (exact=false)
# endpoint: points+count
# constraint_ids: qdrant_behavioral_points_count_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/count-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the boolean `exact` flag
#            is the classic serde-coercion victim: "true"/1/[] flowing through
#            as truthy) + BS-09 (exact=false is the estimation face; the
#            documented approximation must still stay within [0, total])
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 exact-flag type-confusion x qdrant_behavioral_points_count_001
  — the promise "exact=true (default) performs an exact count" makes `exact`
  (type boolean per contract parameters) load-bearing: if a wrong-typed
  value coerces through, the caller cannot know which face answered. Faces
  on a LIVE 12-point collection (8 berlin / 4 paris):
    F1 exact="true"  (string for boolean)  -> 400/422; 2xx = Type1.
    F2 exact=1       (integer for boolean) -> 400/422; 2xx = Type1.
    F3 exact=null    (explicit null vs omitted default) -> 200 with
       count == 12 (default-true face); 4xx recorded as NOTE (asymmetric
       strictness); 200 with count != 12 = Type4.
    F4 exact=false   (DOCUMENTED approximate face — BS-09) -> 200 with
       0 <= count <= 12; a deviation from 12 is by-design approximation and
       NOT a defect; out-of-range count (negative / > total) or 5xx IS a
       defect; 4xx on the documented-valid false face = Type1.
    F5 exact=[]      (array for boolean)    -> 400/422; 2xx = Type1.
  [chunk_points+count coverage: strategy2 type-confusion x exact x
  qdrant_behavioral_points_count_001 + strategy4 exact=false sanity face
  (this script; filter type confusion in boundary_points_count_filter_type_003,
  min_should branch in boundary_points_count_min_should_004; baselines in
  boundary_points_count_all_001 / boundary_points_count_filter_arith_002,
  malformed bodies in boundary_points_count_malformed_006)]
Oracle: F1/F2/F5 -> 400/422 clean; any 2xx = Type1_IllegalSuccess (boolean
  type violation coerced silently); F3 -> 200 count==12 (mismatch =
  Type4_StateLogicViolation; 4xx = NOTE); F4 -> 200 with 0 <= count <= 12
  (out-of-range = Type4_StateLogicViolation; 4xx = Type1_IllegalSuccess —
  documented-valid face rejected; 5xx = Type3_RuntimeFailure); transport
  failure -> /healthz liveness re-check then SCRIPT_ERROR
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


coll = ""


def run_count(exact_value, label, sentinel="__OMIT__"):
    """POST one count request with the given exact face; returns (s, count, raw)."""
    body = {}
    if exact_value is not sentinel:
        body["exact"] = exact_value
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
    coll = "bpcE5" + tag

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

        # ---- F1: exact="true" (string for boolean) ----
        s, count, raw = run_count("true", "F1 exact=\"true\" (string for boolean)")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F1: string "
                      f"exact crashed the count face with {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F1 5xx and healthz down")
            return
        if 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F1: exact="
                  f"\"true\" (string) silently accepted with {s} (parameter type "
                  f"boolean); caller cannot tell which face answered: "
                  f"{raw[:300]}")
            return
        print(f"F1: rejected with {s} (clean)")

        # ---- F2: exact=1 (integer for boolean) ----
        s, count, raw = run_count(1, "F2 exact=1 (integer for boolean)")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F2: integer "
                      f"exact crashed the count face with {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F2 5xx and healthz down")
            return
        if 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F2: exact=1 "
                  f"(integer) silently accepted with {s} (parameter type "
                  f"boolean): {raw[:300]}")
            return
        print(f"F2: rejected with {s} (clean)")

        # ---- F3: exact=null vs omitted default ----
        s, count, raw = run_count(None, "F3 exact=null (explicit null vs omitted default)")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F3: null "
                      f"exact crashed the count face with {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F3 5xx and healthz down")
            return
        if not (200 <= s <= 299):
            notes.append(f"F3: status {s} (null exact rejected while omitted "
                         f"default is accepted — asymmetric, defensible "
                         f"strictness, judge call)")
            print(f"F3: NOTE — {s} recorded for the judge")
        elif count != N_SEED:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F3: "
                  f"exact=null must resolve to the default true face "
                  f"(count == {N_SEED}), got {count}: {raw[:300]}")
            return
        else:
            print(f"F3: 200 with count == {count} == N_SEED (null = default face)")

        # ---- F4: exact=false — documented approximate face sanity (BS-09) ----
        s, count, raw = run_count(False, "F4 exact=false (documented approximate face)")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F4: "
                      f"exact=false count returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F4 5xx and healthz down")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F4: "
                  f"exact=false is a documented-valid face, rejected with "
                  f"{s}: {raw[:300]}")
            return
        if not (isinstance(count, int) and not isinstance(count, bool)):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F4: "
                  f"result.count not an integer: {raw[:300]}")
            return
        if count < 0 or count > N_SEED:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F4: "
                  f"approximate count must stay within [0, {N_SEED}], got "
                  f"{count}: {raw[:300]}")
            return
        if count != N_SEED:
            print(f"F4: approximate count {count} != {N_SEED} — by-design "
                  f"estimation (BS-09), not a defect; recorded for the judge")
        else:
            print(f"F4: approximate count == {N_SEED} (within [0, {N_SEED}])")

        # ---- F5: exact=[] (array for boolean) ----
        s, count, raw = run_count([], "F5 exact=[] (array for boolean)")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F5: array "
                      f"exact crashed the count face with {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F5 5xx and healthz down")
            return
        if 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F5: exact=[] "
                  f"(array) silently accepted with {s} (parameter type "
                  f"boolean): {raw[:300]}")
            return
        print(f"F5: rejected with {s} (clean)")

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
