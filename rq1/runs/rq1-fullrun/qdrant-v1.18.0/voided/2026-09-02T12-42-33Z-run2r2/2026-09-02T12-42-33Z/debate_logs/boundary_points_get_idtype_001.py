#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_get_idtype_001
# strategy: strategy1 boundary-value attack (PointId u64 domain closure:
#           min=0 and max=2^64-1 must BOTH be acceptable) + strategy2
#           type-boundary attack (non-PointId entry forms must be rejected)
# endpoint: points+get
# constraint_ids: qdrant_behavioral_points_get_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/get-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — PointId is oneOf
#            u64|UUID-string; float/bool/object/array/malformed-string
#            entries must fail serde cleanly, never coerce or 5xx)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1+2 PointId entry-domain x qdrant_behavioral_points_get_002 —
  contract data_types: "PointId (ExtendedPointId): oneOf 64-bit unsigned
  integer | UUID string". Positive closure (G4: the boundary values
  THEMSELVES must be accepted): seed and retrieve id 0 (u64 MIN), id
  18446744073709551615 (u64 MAX) and a uuid — all three must come back in
  one 200 result (they are legal PointIds even when absent a get must be
  200-with-omission, and here they are seeded so they must be PRESENT).
  Negative entries, each in its OWN request for isolation: u64 MAX+1
  (18446744073709551616, integer overflow), -1 (negative), 1.5 (float),
  true (bool), null, "not-a-uuid" (string branch requires UUID format),
  {"id":1} (object), [1] (nested array) — each must be a clean 400/422.
  [chunk_points+get coverage: strategy1 defaults-matrix x _001
  (defaults_001); strategy1 selector-projection x _001 (defaults_002);
  strategy2 flag-type x _001 (type_001); strategy1 missing-arithmetic x
  _002 (missing_001); strategy1 multiplicity+duality x _002 (dupes_001);
  strategy1+2 PointId domain x _002 (this script); strategy2 ids-container
  x _002 (idtype_002); strategy6 resource x _002 (ids_size_001)]
Oracle: positive leg -> HTTP 200 with len(result)==3 and id set EXACTLY
  {0, 18446744073709551615, uuid} (u64 min and max both accepted — the
  boundary itself); every negative entry -> HTTP 400/422 (clean serde
  rejection); HTTP 200 for an illegal entry = Type1_IllegalSuccess (BS-01
  silent coercion); 4xx/missing on the positive leg = Type1_IllegalSuccess
  (legal boundary PointIds rejected); 5xx with /healthz alive =
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
U64_MIN = 0
U64_MAX = 18446744073709551615            # 2^64 - 1 (legal boundary)
U64_OVER = 18446744073709551616           # 2^64     (overflow, illegal)
UUID_ID = "c73bcdcc-2606-4b31-94a4-9d3b29a7d15e"


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
    coll = "bpgI6" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [
            {"id": U64_MIN, "vector": V, "payload": {"edge": "min"}},
            {"id": U64_MAX, "vector": V, "payload": {"edge": "max"}},
            {"id": UUID_ID, "vector": V, "payload": {"edge": "uuid"}},
        ]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        def defect(kind, leg, detail):
            print(f"VERDICT: DEFECT_FOUND ({kind}) — leg [{leg}]: {detail}")

        # ---- Positive closure: u64 MIN and MAX and uuid, seeded, one request ----
        expected = [U64_MIN, U64_MAX, UUID_ID]
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": expected}, timeout=60)
        print(f"leg positive u64-min+max+uuid -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1 and not transport_dead("leg positive closure"):
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                defect("Type3_RuntimeFailure", "positive closure",
                       f"valid boundary PointIds got {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        if s != 200:
            defect("Type1_IllegalSuccess", "positive closure",
                   f"u64 MIN/MAX/uuid are legal PointIds (seeded!) but the get returned "
                   f"{s} instead of 200-with-records: {raw[:300]}")
            return
        result = body_resp.get("result") if isinstance(body_resp, dict) else None
        if not isinstance(result, list):
            defect("Type1_IllegalSuccess", "positive closure",
                   f"200 but envelope result is not an array: {raw[:300]}")
            return
        got_ids = [rec.get("id") if isinstance(rec, dict) else None for rec in result]
        if len(got_ids) != 3 or set(got_ids) != set(expected):
            defect("Type4_StateLogicViolation", "positive closure",
                   f"seeded boundary ids {expected} must all be returned, got {got_ids}: "
                   f"{raw[:300]}")
            return
        print("leg positive closure OK: u64 min(0) and max(2^64-1) and uuid all retrieved")

        # ---- Negative entries: each illegal PointId form in its own request ----
        negative_legs = [
            ("u64 MAX+1 (overflow)", U64_OVER),
            ("negative -1",          -1),
            ("float 1.5",            1.5),
            ("bool true",            True),
            ("null entry",           None),
            ("not-a-uuid string",    "not-a-uuid"),
            ("object {id:1}",        {"id": 1}),
            ("nested array [1]",     [1]),
        ]
        for leg_name, bad in negative_legs:
            s, _, raw = safe_request("POST", f"/collections/{coll}/points",
                                     json={"ids": [bad]}, timeout=60)
            print(f"leg {leg_name} -> status={s}")
            print(f"raw: {raw[:300]}")
            if s == -1 and not transport_dead(f"leg {leg_name}"):
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    defect("Type3_RuntimeFailure", leg_name,
                           f"illegal PointId form got 5xx ({s}) instead of clean 4xx "
                           f"(parser robustness): {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if 200 <= s <= 299:
                defect("Type1_IllegalSuccess", leg_name,
                       f"illegal PointId form silently accepted (BS-01 type coercion / "
                       f"domain overflow): {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on {leg_name}; no defect conclusion")
                return
            print(f"leg {leg_name} OK: clean 4xx rejection")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
