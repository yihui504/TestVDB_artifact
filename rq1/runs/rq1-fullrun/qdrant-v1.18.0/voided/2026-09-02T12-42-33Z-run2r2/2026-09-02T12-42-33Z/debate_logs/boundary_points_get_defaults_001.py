#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_get_defaults_001
# strategy: strategy1 boundary-value attack (opt-in matrix closure on the
#           with_payload/with_vector default-false promise — the default
#           itself is the boundary under test)
# endpoint: points+get
# constraint_ids: qdrant_behavioral_points_get_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-04 (Boundary Default Optimism — clients assume the default
#            omits payload/vector; a server that leaks them by default or
#            that cannot honor the opt-in flags breaks the promise silently)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 opt-in matrix closure x qdrant_behavioral_points_get_001 —
  the contract promises with_payload/with_vector DEFAULT FALSE ("retrieval
  omits payload and vector unless opted in"). 2x2 closure on two seeded
  points plus the explicit-false leg: (default | with_payload=true |
  with_vector=true | both=true | with_payload=false). Default legs are
  judged on KEY ABSENCE (records carry id, no non-null payload, no vector
  content); opt-in legs are judged on exact readback of the seeded content.
  [chunk_points+get coverage: strategy1 defaults-matrix x _001 (this
  script); strategy1 selector-projection x _001 (defaults_002); strategy2
  flag-type x _001 (type_001); strategy1 missing-arithmetic x _002
  (missing_001); strategy1 multiplicity+duality x _002 (dupes_001);
  strategy1+2 PointId domain x _002 (idtype_001); strategy2 ids-container
  x _002 (idtype_002); strategy6 resource x _002 (ids_size_001)]
Oracle: default and with_payload=false legs -> HTTP 200 with result records
  carrying id only (no non-null payload, no vector content); with_payload
  =true leg -> record payload == seeded payload exactly; with_vector=true
  leg -> record vector == [0.5,0.25,0.125,0.0625] exactly (Euclid metric +
  binary-exact floats so stored == submitted; readback-vs-baseline per R27
  lesson); both=true leg -> both present. Payload/vector content on a
  default leg = Type1_IllegalSuccess; wrong readback content on an opt-in
  leg = Type4_StateLogicViolation; 4xx on these valid requests =
  Type1_IllegalSuccess (valid documented request rejected); 5xx with
  /healthz alive = Type3_RuntimeFailure; transport failure -> /healthz
  re-check then SCRIPT_ERROR (constraint qdrant_behavioral_points_get_001).
Constraint: qdrant_behavioral_points_get_001 (bare id) — "with_payload/
  with_vector default false: retrieval omits payload and vector unless
  opted in" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+get          -> POST /collections/{collection_name}/points   (body field ids is REQUIRED on this face — R31/R37 lesson; no /points/get suffix exists)
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
# binary-exact floats: stored == submitted under Euclid (no normalization — R27)
V = [0.5, 0.25, 0.125, 0.0625]
PAYLOADS = {
    101: {"city": "tokyo", "score": 7, "tags": ["a", "b"]},
    102: {"city": "osaka", "score": 3},
}


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/consistency) via params= — never stuffed into the body.
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
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{leg}]: valid get "
              f"returned {rs} with service alive: {rraw[:300]}")
    else:
        print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
    return True


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpgD1" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{"id": pid, "vector": V, "payload": pl} for pid, pl in PAYLOADS.items()]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        # ---- Leg A: default (no flags) -> id only, payload/vector omitted ----
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": [101, 102]}, timeout=60)
        print(f"leg A default -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            transport_dead("leg A default")
            return
        if handle_5xx(s, raw, "A default"):
            return
        result = body_resp.get("result") if isinstance(body_resp, dict) else None
        if s in (400, 404, 422):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [A default]: valid "
                  f"documented get (ids only) rejected with {s}: {raw[:300]}")
            return
        if s != 200 or not isinstance(result, list):
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s}; no defect conclusion")
            return
        if len(result) != 2:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [A default]: 2 "
                  f"seeded points requested, {len(result)} records returned: {raw[:300]}")
            return
        for rec in result:
            leaked = []
            if rec.get("payload") is not None:
                leaked.append(f"payload={json.dumps(rec.get('payload'))[:120]}")
            if rec.get("vector") is not None:
                leaked.append("vector content")
            if leaked:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [A default]: "
                      f"record id={rec.get('id')} returned {' and '.join(leaked)} WITHOUT "
                      f"opt-in (default-false promise broken): {raw[:300]}")
                return
        print("leg A OK: default records carry id only (payload/vector omitted)")

        # ---- Leg B: with_payload=true -> exact payload readback, vector still omitted ----
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": [101, 102], "with_payload": True}, timeout=60)
        print(f"leg B with_payload=true -> status={s}")
        if s == -1:
            transport_dead("leg B with_payload=true")
            return
        if handle_5xx(s, raw, "B with_payload=true"):
            return
        result = body_resp.get("result") if isinstance(body_resp, dict) else None
        if s != 200 or not isinstance(result, list):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [B with_payload="
                  f"true]: valid opt-in get rejected/malformed with {s}: {raw[:300]}")
            return
        for rec in result:
            rid = rec.get("id")
            if rec.get("payload") != PAYLOADS.get(rid):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [B "
                      f"with_payload=true]: record id={rid} payload "
                      f"{json.dumps(rec.get('payload'))[:160]} != seeded "
                      f"{json.dumps(PAYLOADS.get(rid))[:160]}: {raw[:200]}")
                return
            if rec.get("vector") is not None:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [B "
                      f"with_payload=true]: record id={rid} leaked vector content with "
                      f"only with_payload opted in: {raw[:200]}")
                return
        print("leg B OK: payload readback exact, vector still omitted")

        # ---- Leg C: with_vector=true -> exact vector readback, payload omitted ----
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": [101, 102], "with_vector": True}, timeout=60)
        print(f"leg C with_vector=true -> status={s}")
        if s == -1:
            transport_dead("leg C with_vector=true")
            return
        if handle_5xx(s, raw, "C with_vector=true"):
            return
        result = body_resp.get("result") if isinstance(body_resp, dict) else None
        if s != 200 or not isinstance(result, list):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [C with_vector="
                  f"true]: valid opt-in get rejected/malformed with {s}: {raw[:300]}")
            return
        for rec in result:
            rid = rec.get("id")
            got_v = rec.get("vector")
            if not isinstance(got_v, list) or len(got_v) != DIM or any(
                    abs(float(a) - float(b)) > 1e-9 for a, b in zip(got_v, V)):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [C "
                      f"with_vector=true]: record id={rid} vector "
                      f"{json.dumps(got_v)[:160]} != baseline {json.dumps(V)} (Euclid, "
                      f"binary-exact floats): {raw[:200]}")
                return
            if rec.get("payload") is not None:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [C "
                      f"with_vector=true]: record id={rid} leaked payload with only "
                      f"with_vector opted in: {raw[:200]}")
                return
        print("leg C OK: vector readback exact (baseline match), payload omitted")

        # ---- Leg D: both flags -> both present ----
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": [101, 102],
                                               "with_payload": True, "with_vector": True}, timeout=60)
        print(f"leg D both=true -> status={s}")
        if s == -1:
            transport_dead("leg D both=true")
            return
        if handle_5xx(s, raw, "D both=true"):
            return
        result = body_resp.get("result") if isinstance(body_resp, dict) else None
        if s != 200 or not isinstance(result, list):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [D both=true]: "
                  f"valid dual opt-in get rejected/malformed with {s}: {raw[:300]}")
            return
        for rec in result:
            rid = rec.get("id")
            if rec.get("payload") != PAYLOADS.get(rid):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [D "
                      f"both=true]: record id={rid} payload wrong under dual opt-in: "
                      f"{raw[:200]}")
                return
            got_v = rec.get("vector")
            if not isinstance(got_v, list) or len(got_v) != DIM:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [D "
                      f"both=true]: record id={rid} vector missing/wrong under dual "
                      f"opt-in: {raw[:200]}")
                return
        print("leg D OK: both payload and vector returned under dual opt-in")

        # ---- Leg E: with_payload=false explicit -> same as default ----
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": [101, 102], "with_payload": False}, timeout=60)
        print(f"leg E with_payload=false -> status={s}")
        if s == -1:
            transport_dead("leg E with_payload=false")
            return
        if handle_5xx(s, raw, "E with_payload=false"):
            return
        result = body_resp.get("result") if isinstance(body_resp, dict) else None
        if s != 200 or not isinstance(result, list):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [E with_payload="
                  f"false]: valid explicit opt-out get rejected with {s}: {raw[:300]}")
            return
        for rec in result:
            if rec.get("payload") is not None or rec.get("vector") is not None:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [E "
                      f"with_payload=false]: record id={rec.get('id')} returned content "
                      f"despite explicit with_payload=false: {raw[:300]}")
                return
        print("leg E OK: explicit false behaves as default (omission)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
