#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_default_limit_001
# strategy: strategy6 metamorphic attack (documented defaults as equivalence
#           relations) + G4 boundary closure of the min values
# endpoint: points+query
# constraint_ids: qdrant_range_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — defaults must equal the
#            documented explicit values, not merely "work")
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy6 metamorphic defaults x qdrant_range_points_query_001 —
  the contract fixes limit minimum 1 (DEFAULT 10) and offset minimum 0
  (DEFAULT 0). A default is a semantic promise, so it is attacked as an
  equivalence relation, in the deterministic id-ordered no-query mode
  (query absent without prefetch returns points ordered by their ids —
  qdrant_behavioral_points_query_004, same spec page). 15 points are
  upserted in SHUFFLED id order so insert order cannot masquerade as
  id order. Legs:
    M1 omit limit             -> exactly 10 ids == sorted(all)[:10]
    M2 limit=10 explicit      -> ids IDENTICAL to M1 (default == explicit)
    M3 limit=1 (min closure)  -> exactly 1 point, the lowest id (G4: the
                                 min itself is legal and must be accepted)
    M4 offset=0 explicit      -> ids IDENTICAL to M1 (default == explicit)
    M5 limit=15 (=N)          -> all 15 ids ascending
    M6 limit=16 (>N)          -> all 15 ids, no phantom/no error
  [chunk_points+query semantic coverage — see variant_domain_001 for the
  full 10-script coverage list; this script = metamorphic default-limit x
  qdrant_range_points_query_001]
Oracle: M1==M2==M4 as id sequences (each exactly the first 10 ids ascending);
  M3 -> [min id]; M5/M6 -> all 15 ascending. Any count/sequence mismatch =
  Type4_StateLogicViolation (documented default/range semantics violated);
  4xx on M1..M6 (all spec-legal values) = Type1_IllegalSuccess; 5xx with
  /healthz alive = Type3_RuntimeFailure; transport failure -> /healthz
  re-check then SCRIPT_ERROR (constraint qdrant_range_points_query_001).
Constraint: qdrant_range_points_query_001 (bare id) — "limit minimum 1
  (default 10); offset minimum 0 (default 0)" (evidence_tier: explicit;
  level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query        -> POST /collections/{collection_name}/points/query
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
N = 15
ALL_IDS = list(range(201, 201 + N))
# deliberately non-sorted upsert order: id-order must not be insert-order
SHUFFLED = [215, 203, 209, 201, 213, 206, 211, 204, 208, 202, 214, 207, 212, 205, 210]
SEED = [{"id": i, "vector": [float((i - 201) % 3), float((i - 201) % 5),
                             float((i - 201) % 2), 1.0]} for i in SHUFFLED]


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


def transport_dead(where):
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


def get_points(body):
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, dict) and isinstance(r.get("points"), list):
            return r["points"]
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqD1" + tag

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": SEED}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        qpath = f"/collections/{coll}/points/query"

        def leg_ids(leg, body_json):
            s, body, raw = safe_request("POST", qpath, json=body_json, timeout=60)
            print(f"{leg} -> status={s}")
            print(f"raw: {raw[:300]}")
            if s == -1:
                transport_dead(leg)
                return None
            if handle_5xx(s, raw, leg):
                return None
            if 400 <= s <= 499:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{leg}]: "
                      f"spec-legal pagination request rejected with {s}: {raw[:250]}")
                return "DEFECT"
            pts = get_points(body)
            if s != 200 or pts is None:
                print(f"VERDICT: SCRIPT_ERROR — leg [{leg}] unexpected status {s}; "
                      f"no defect conclusion")
                return None
            return [p.get("id") for p in pts]

        m1 = leg_ids("M1 omit limit", {})
        if m1 in (None, "DEFECT"):
            return
        m2 = leg_ids("M2 limit=10 explicit", {"limit": 10})
        if m2 in (None, "DEFECT"):
            return
        m3 = leg_ids("M3 limit=1 (min closure)", {"limit": 1})
        if m3 in (None, "DEFECT"):
            return
        m4 = leg_ids("M4 offset=0 explicit", {"limit": 10, "offset": 0})
        if m4 in (None, "DEFECT"):
            return
        m5 = leg_ids("M5 limit=15 (=N)", {"limit": 15})
        if m5 in (None, "DEFECT"):
            return
        m6 = leg_ids("M6 limit=16 (>N)", {"limit": 16})
        if m6 in (None, "DEFECT"):
            return

        expect_first10 = sorted(ALL_IDS)[:10]
        if m1 != expect_first10:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M1: omitted "
                  f"limit must default to 10 -> first 10 ids ascending "
                  f"{expect_first10}, got {m1}")
            return
        print("M1 OK: default limit returns the first 10 ids ascending")
        if m2 != m1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M2: explicit "
                  f"limit=10 must equal the default: {m2} != {m1}")
            return
        print("M2 OK: limit=10 == default")
        if m3 != [min(ALL_IDS)]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M3: limit=1 "
                  f"(documented minimum) must return exactly the lowest id "
                  f"[{min(ALL_IDS)}], got {m3}")
            return
        print("M3 OK: limit=1 accepted, returns the single lowest id")
        if m4 != m1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M4: explicit "
                  f"offset=0 must equal the default: {m4} != {m1}")
            return
        print("M4 OK: offset=0 == default")
        if sorted(m5) != sorted(ALL_IDS) or m5 != sorted(ALL_IDS):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M5: limit=15 "
                  f"over 15 points must return all 15 ids ascending, got {m5}")
            return
        print("M5 OK: limit=N returns all ids ascending")
        if sorted(m6) != sorted(ALL_IDS):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M6: limit>N "
                  f"must return all 15 real ids (no phantom, no error), got {m6}")
            return
        print("M6 OK: limit>N clamps to the real point count")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
