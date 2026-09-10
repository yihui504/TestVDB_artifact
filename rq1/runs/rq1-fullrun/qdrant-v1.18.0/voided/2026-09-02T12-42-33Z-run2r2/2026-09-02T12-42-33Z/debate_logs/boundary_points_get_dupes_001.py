#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_get_dupes_001
# strategy: strategy1 boundary-value attack (input multiplicity + PointId
#           oneOf branch duality — duplicates in the requested ids list and
#           the int|uuid oneOf closure of "one Record per found id")
# endpoint: points+get
# constraint_ids: qdrant_behavioral_points_get_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/get-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — duplicate requested ids are
#            the multiplicity boundary of 'one Record per found id'; a
#            naive per-request-id loop would echo duplicate Records and
#            silently double-count for clients)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 multiplicity + oneOf duality x
  qdrant_behavioral_points_get_002 — the contract promises "one Record per
  found id". Two faces: (a) multiplicity — request the same id several
  times (int ids [1,1,1,2] and a repeated uuid): the result must contain
  exactly one Record per FOUND id (no duplicate echo); (b) PointId oneOf
  duality — seed int ids AND a uuid id, request them together (both oneOf
  branches legal in one request), plus a WELL-FORMED but absent uuid
  ("00000000-0000-0000-0000-000000999999" parses as UUID, exists nowhere)
  to close the missing-id promise on the uuid branch too (a malformed
  string is NOT used here — that would be a type error, not a missing id).
  [chunk_points+get coverage: strategy1 defaults-matrix x _001
  (defaults_001); strategy1 selector-projection x _001 (defaults_002);
  strategy2 flag-type x _001 (type_001); strategy1 missing-arithmetic x
  _002 (missing_001); strategy1 multiplicity+duality x _002 (this
  script); strategy1+2 PointId domain x _002 (idtype_001); strategy2
  ids-container x _002 (idtype_002); strategy6 resource x _002
  (ids_size_001)]
Oracle: dup-int leg [1,1,1,2] -> HTTP 200 with len(result)==2 and id set
  EXACTLY {1,2} (more than one Record for a found id contradicts 'one
  Record per found id' = Type4_StateLogicViolation); dup-uuid leg ->
  len(result)==1; mixed-branch leg [2, uuid] -> len(result)==2 with both
  ids; absent-uuid leg [2, "00000000-0000-0000-0000-000000999999"] -> 200
  with len(result)==1 (well-formed missing uuid omitted, not an error —
  4xx/404 here = Type1_IllegalSuccess); 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz re-check then
  SCRIPT_ERROR (constraint qdrant_behavioral_points_get_002).
Constraint: qdrant_behavioral_points_get_002 (bare id) — "batch get returns
  HTTP 200 with one Record per found id; ids that do not exist are omitted
  from the result without erroring" (evidence_tier: explicit; level:
  endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+get          -> POST /collections/{collection_name}/points   (body field ids is REQUIRED — R31/R37 lesson)
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
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
V = [0.5, 0.25, 0.125, 0.0625]
UUID_ID = "c73bcdcc-2606-4b31-94a4-9d3b29a7d15e"      # seeded, uuid branch
ABSENT_UUID = "00000000-0000-0000-0000-000000999999"  # well-formed, never seeded


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
    """Inline liveness probe on the lightweight healthz face."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def transport_dead(where):
    """Transport-branch liveness re-check (lightweight healthz face only)."""
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return False


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpgU5" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [
            {"id": 1, "vector": V, "payload": {"kind": "int"}},
            {"id": 2, "vector": V, "payload": {"kind": "int"}},
            {"id": UUID_ID, "vector": V, "payload": {"kind": "uuid"}},
        ]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        def defect(kind, leg, detail):
            print(f"VERDICT: DEFECT_FOUND ({kind}) — leg [{leg}]: {detail}")

        # (leg_name, requested_ids, expected_found_ids)
        legs = [
            ("dup-int [1,1,1,2]",   [1, 1, 1, 2],                     [1, 2]),
            ("dup-uuid x2",         [UUID_ID, UUID_ID],               [UUID_ID]),
            ("mixed oneOf [2,uuid]", [2, UUID_ID],                     [2, UUID_ID]),
            ("absent-uuid branch",  [2, ABSENT_UUID],                 [2]),
        ]
        for leg_name, req_ids, expected in legs:
            s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                             json={"ids": req_ids}, timeout=60)
            print(f"leg {leg_name} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1 and not transport_dead(f"leg {leg_name}"):
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    defect("Type3_RuntimeFailure", leg_name,
                           f"valid get returned {s} with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s in (400, 404, 422):
                defect("Type1_IllegalSuccess", leg_name,
                       f"get of legal PointIds (all well-formed; missing ones must be "
                       f"omitted from a 200 result) errored with {s}: {raw[:300]}")
                return
            if s != 200:
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on {leg_name}; no defect conclusion")
                return
            result = body_resp.get("result") if isinstance(body_resp, dict) else None
            if not isinstance(result, list):
                defect("Type1_IllegalSuccess", leg_name,
                       f"200 but envelope result is not an array: {raw[:300]}")
                return
            got_ids = [rec.get("id") if isinstance(rec, dict) else None for rec in result]
            if len(got_ids) != len(expected) or set(got_ids) != set(expected):
                defect("Type4_StateLogicViolation", leg_name,
                       f"'one Record per found id' broken: requested {req_ids} "
                       f"(found set {expected}) must yield EXACTLY {len(expected)} records "
                       f"{expected}, got {len(got_ids)} records {got_ids} "
                       f"(duplicate echo or omission): {raw[:300]}")
                return
            print(f"leg {leg_name} OK: exactly one Record per found id")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
