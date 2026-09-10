#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_get_type_001
# strategy: strategy2 type-boundary attack (with_payload/with_vector typed
#           boolean|selector — non-boolean non-selector forms must be
#           rejected, never silently coerced) + strategy5 error-diagnostics
#           assessment on the nameable leg
# endpoint: points+get
# constraint_ids: qdrant_behavioral_points_get_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde must reject
#            string "true"/integer 1/array/unknown-key objects for a
#            boolean|selector field; silent coercion produces undefined
#            opt-in semantics)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-confusion x qdrant_behavioral_points_get_001 — the
  contract types with_payload/with_vector as boolean|selector. Probes on a
  seeded point (each illegal form in its OWN request so legs are isolated):
  with_payload="true" (string), =1 (int), =[] (array), ={"include":"k"}
  (include as string, not array), ={"unknown_key":["k"]} (no selector
  branch), with_vector="true", =1, =[]; plus a NULL soft leg
  (with_payload=null) where acceptance is only legal if it behaves as
  NOT-opted-in (null -> default false, mirroring the documented null-means-
  absent convention). Includes a strategy5 diagnostics leg: the 4xx for
  with_payload="true" must name the parameter family.
  [chunk_points+get coverage: strategy1 defaults-matrix x _001
  (defaults_001); strategy1 selector-projection x _001 (defaults_002);
  strategy2 flag-type x _001 (this script); strategy1 missing-arithmetic x
  _002 (missing_001); strategy1 multiplicity+duality x _002 (dupes_001);
  strategy1+2 PointId domain x _002 (idtype_001); strategy2 ids-container
  x _002 (idtype_002); strategy6 resource x _002 (ids_size_001)]
Oracle: every illegal typed form -> HTTP 400/422 (clean serde rejection);
  HTTP 200 for an illegal form = Type1_IllegalSuccess (BS-01 silent
  coercion); 5xx with /healthz alive = Type3_RuntimeFailure; the null leg
  accepts 4xx OR 200-with-payload-omitted (defect only if 200 returns
  payload content — null must not enable opt-in — or 5xx); the 4xx answer
  for with_payload="true" that mentions neither "with_payload" nor
  "payload" = Type2_PoorDiagnostics; all legs clean -> NO_DEFECT;
  transport failure -> /healthz re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_get_001).
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
PAYLOAD = {"k": "v", "n": 8}


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
    coll = "bpgT3" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": [{"id": 301, "vector": V, "payload": PAYLOAD}]},
                                 params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        def defect(kind, leg, detail):
            print(f"VERDICT: DEFECT_FOUND ({kind}) — leg [{leg}]: {detail}")

        # illegal typed forms for boolean|selector fields; each in its own request
        illegal_legs = [
            ("wp='true'(string)", {"ids": [301], "with_payload": "true"}),
            ("wp=1(int)",         {"ids": [301], "with_payload": 1}),
            ("wp=[](array)",      {"ids": [301], "with_payload": []}),
            ("wp.include=string", {"ids": [301], "with_payload": {"include": "k"}}),
            ("wp=unknown-key",    {"ids": [301], "with_payload": {"unknown_key": ["k"]}}),
            ("wv='true'(string)", {"ids": [301], "with_vector": "true"}),
            ("wv=1(int)",         {"ids": [301], "with_vector": 1}),
            ("wv=[](array)",      {"ids": [301], "with_vector": []}),
        ]
        for leg_name, body in illegal_legs:
            s, _, raw = safe_request("POST", f"/collections/{coll}/points",
                                     json=body, timeout=60)
            print(f"leg {leg_name} -> status={s}")
            print(f"raw: {raw[:300]}")
            if s == -1 and not transport_dead(f"leg {leg_name}"):
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    defect("Type3_RuntimeFailure", leg_name,
                           f"illegal typed form got 5xx ({s}) instead of clean 4xx: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if 200 <= s <= 299:
                defect("Type1_IllegalSuccess", leg_name,
                       f"illegal typed form for boolean|selector field silently accepted "
                       f"(BS-01 type coercion): {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on {leg_name}; no defect conclusion")
                return
            # strategy5 diagnostics check on the nameable leg
            if leg_name == "wp='true'(string)":
                low = raw.lower()
                if "with_payload" not in low and "payload" not in low:
                    defect("Type2_PoorDiagnostics", leg_name,
                           f"4xx rejects the illegal form but names neither 'with_payload' "
                           f"nor 'payload': {raw[:300]}")
                    return
                print("diagnostics OK: 4xx names the with_payload parameter family")
            print(f"leg {leg_name} OK: clean 4xx rejection")

        # ---- NULL soft leg: accepted only if it behaves as NOT opted in ----
        s, body_resp, raw = safe_request("POST", f"/collections/{coll}/points",
                                         json={"ids": [301], "with_payload": None}, timeout=60)
        print(f"leg wp=null(soft) -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1 and not transport_dead("leg wp=null"):
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                defect("Type3_RuntimeFailure", "wp=null", f"null flag got 5xx ({s}): {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        if 200 <= s <= 299:
            result = body_resp.get("result") if isinstance(body_resp, dict) else None
            rec = result[0] if isinstance(result, list) and result else None
            if isinstance(rec, dict) and rec.get("payload") is not None:
                defect("Type1_IllegalSuccess", "wp=null",
                       f"200 accepted AND payload content returned — null must behave as "
                       f"not-opted-in (default false): {raw[:300]}")
                return
            print("leg wp=null OK: accepted with payload omitted (null == not opted in)")
        elif s in (400, 422):
            print("leg wp=null OK: clean 4xx rejection of null")
        else:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on wp=null; no defect conclusion")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
