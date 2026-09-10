#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_get_defaults_002
# strategy: strategy1 boundary-value attack (selector-branch closure of the
#           opt-in promise: with_payload as {include}/{exclude} selector —
#           each documented branch projected exactly)
# endpoint: points+get
# constraint_ids: qdrant_behavioral_points_get_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-04 (Boundary Default Optimism — the selector branches are
#            the fine-grained opt-in; a server that ignores the projection
#            and returns the full payload silently breaks least-privilege
#            reads)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 selector-projection closure x
  qdrant_behavioral_points_get_001 — the promise "payload returned only when
  opted in" has three documented opt-in forms: with_payload=true (all),
  {"include":[...]} (project to listed keys), {"exclude":[...]} (omit listed
  keys). Seeded p1 payload {"a":1,"b":2,"c":3,"nested":{"k":"v"}} and p2
  payload {} (empty-payload edge of the same projection). Legs: baseline
  true; include ["a","c"]; exclude ["a"]; exclude every top-level key;
  include applied to the empty-payload point. Every leg judged on the EXACT
  key set projected.
  [chunk_points+get coverage: strategy1 defaults-matrix x _001
  (defaults_001); strategy1 selector-projection x _001 (this script);
  strategy2 flag-type x _001 (type_001); strategy1 missing-arithmetic x
  _002 (missing_001); strategy1 multiplicity+duality x _002 (dupes_001);
  strategy1+2 PointId domain x _002 (idtype_001); strategy2 ids-container
  x _002 (idtype_002); strategy6 resource x _002 (ids_size_001)]
Oracle: every leg -> HTTP 200; include ["a","c"] leg -> p1 record payload
  keys EXACTLY {"a","c"} with values 1 and 3; exclude ["a"] leg -> keys
  EXACTLY {"b","c","nested"}; exclude-all leg -> payload == {}; baseline
  true leg -> full payload equality; empty-payload point -> payload is a
  dict with no keys leaked beyond the projected set; vector never returned
  (no with_vector opt-in anywhere). Wrong/extra/missing projected keys =
  Type4_StateLogicViolation (selector projection promise broken); 4xx on
  these valid selector requests = Type1_IllegalSuccess; 5xx with /healthz
  alive = Type3_RuntimeFailure; transport failure -> /healthz re-check then
  SCRIPT_ERROR (constraint qdrant_behavioral_points_get_001).
Constraint: qdrant_behavioral_points_get_001 (bare id) — "with_payload/
  with_vector default false: retrieval omits payload and vector unless
  opted in" (evidence_tier: explicit; level: endpoint)

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
P1_FULL = {"a": 1, "b": 2, "c": 3, "nested": {"k": "v"}}
ALL_KEYS = {"a", "b", "c", "nested"}


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


def handle_5xx(rs, rraw, leg):
    """5xx branch with liveness re-check; True means handled (caller returns)."""
    if not (500 <= rs <= 599):
        return False
    alive, _, _ = healthz_alive()
    if alive:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{leg}]: valid "
              f"selector get returned {rs} with service alive: {rraw[:300]}")
    else:
        print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
    return True


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpgS2" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [
            {"id": 1, "vector": V, "payload": P1_FULL},
            {"id": 2, "vector": V, "payload": {}},
        ]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        def rec_by_id(recs, rid):
            for r in recs:
                if isinstance(r, dict) and r.get("id") == rid:
                    return r
            return None

        # ---- Leg 1: baseline with_payload=true -> full payload (positive pairing) ----
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": [1, 2], "with_payload": True}, timeout=60)
        print(f"leg 1 baseline true -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            transport_dead("leg 1 baseline")
            return
        if handle_5xx(s, raw, "1 baseline"):
            return
        result = body_resp.get("result") if isinstance(body_resp, dict) else None
        if s != 200 or not isinstance(result, list):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [1 baseline]: "
                  f"valid opt-in get rejected/malformed with {s}: {raw[:300]}")
            return
        r1 = rec_by_id(result, 1)
        if r1 is None or r1.get("payload") != P1_FULL:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [1 baseline]: "
                  f"p1 payload {json.dumps(r1.get('payload') if r1 else None)[:160]} != full "
                  f"{json.dumps(P1_FULL)[:160]}: {raw[:200]}")
            return
        print("leg 1 OK: baseline true returns full payload")

        # ---- Leg 2: include ["a","c"] -> keys EXACTLY {a,c} ----
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": [1], "with_payload": {"include": ["a", "c"]}},
                                         timeout=60)
        print(f"leg 2 include[a,c] -> status={s}")
        if s == -1:
            transport_dead("leg 2 include")
            return
        if handle_5xx(s, raw, "2 include"):
            return
        result = body_resp.get("result") if isinstance(body_resp, dict) else None
        if s != 200 or not isinstance(result, list):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [2 include]: valid "
                  f"include-selector get rejected/malformed with {s}: {raw[:300]}")
            return
        r1 = rec_by_id(result, 1)
        pl = r1.get("payload") if r1 is not None else "NO_RECORD"
        if not isinstance(pl, dict) or set(pl.keys()) != {"a", "c"} or pl.get("a") != 1 or pl.get("c") != 3:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [2 include]: "
                  f"include [a,c] must project payload keys EXACTLY to a=1,c=3, got "
                  f"{json.dumps(pl)[:200]}: {raw[:200]}")
            return
        print("leg 2 OK: include projects exactly {a,c}")

        # ---- Leg 3: exclude ["a"] -> keys EXACTLY {b,c,nested} ----
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": [1], "with_payload": {"exclude": ["a"]}},
                                         timeout=60)
        print(f"leg 3 exclude[a] -> status={s}")
        if s == -1:
            transport_dead("leg 3 exclude")
            return
        if handle_5xx(s, raw, "3 exclude"):
            return
        result = body_resp.get("result") if isinstance(body_resp, dict) else None
        if s != 200 or not isinstance(result, list):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [3 exclude]: valid "
                  f"exclude-selector get rejected/malformed with {s}: {raw[:300]}")
            return
        r1 = rec_by_id(result, 1)
        pl = r1.get("payload") if r1 is not None else "NO_RECORD"
        if not isinstance(pl, dict) or set(pl.keys()) != (ALL_KEYS - {"a"}):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [3 exclude]: "
                  f"exclude [a] must leave keys EXACTLY {sorted(ALL_KEYS - {'a'})}, got "
                  f"{json.dumps(pl)[:200]}: {raw[:200]}")
            return
        print("leg 3 OK: exclude leaves exactly b,c,nested")

        # ---- Leg 4: exclude every top-level key -> payload == {} ----
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": [1],
                                               "with_payload": {"exclude": ["a", "b", "c", "nested"]}},
                                         timeout=60)
        print(f"leg 4 exclude-all -> status={s}")
        if s == -1:
            transport_dead("leg 4 exclude-all")
            return
        if handle_5xx(s, raw, "4 exclude-all"):
            return
        result = body_resp.get("result") if isinstance(body_resp, dict) else None
        if s != 200 or not isinstance(result, list):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [4 exclude-all]: "
                  f"valid exclude-all get rejected/malformed with {s}: {raw[:300]}")
            return
        r1 = rec_by_id(result, 1)
        pl = r1.get("payload") if r1 is not None else "NO_RECORD"
        if pl != {}:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [4 exclude-"
                  f"all]: excluding every top-level key must yield payload == {{}}, got "
                  f"{json.dumps(pl)[:200]}: {raw[:200]}")
            return
        print("leg 4 OK: exclude-all yields empty payload object")

        # ---- Leg 5: include on the empty-payload point; nothing may leak ----
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": [2], "with_payload": {"include": ["a", "b", "c"]}},
                                         timeout=60)
        print(f"leg 5 include-on-empty -> status={s}")
        if s == -1:
            transport_dead("leg 5 include-on-empty")
            return
        if handle_5xx(s, raw, "5 include-on-empty"):
            return
        result = body_resp.get("result") if isinstance(body_resp, dict) else None
        if s != 200 or not isinstance(result, list):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [5 include-on-"
                  f"empty]: valid get on empty-payload point rejected/malformed with "
                  f"{s}: {raw[:300]}")
            return
        r2 = rec_by_id(result, 2)
        if r2 is None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [5 include-"
                  f"on-empty]: seeded point 2 missing from result: {raw[:200]}")
            return
        pl = r2.get("payload")
        if not isinstance(pl, dict) or len(pl) != 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [5 include-"
                  f"on-empty]: empty-payload point under include must project to {{}} "
                  f"(no keys may leak), got {json.dumps(pl)[:200]}: {raw[:200]}")
            return
        if r2.get("vector") is not None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [5 include-on-"
                  f"empty]: vector content returned with no with_vector opt-in: "
                  f"{raw[:200]}")
            return
        print("leg 5 OK: empty payload stays empty under include; no vector leak")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
