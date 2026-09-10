#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_016
# strategy: count_consistency
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 success-envelope + created-state readback on
  PUT /collections/{name} (collections+create; URL from raw_knowledge
  api_endpoints[].url). The behavioral assertion promises: a valid create
  returns HTTP 200 with CollectionOperationResponse — per the contract's
  response_shape that envelope is {result: boolean, status: string,
  time: number} — and 200 means the collection was created. Legs:
  (A) valid dense create {size:8, distance:"Euclid"} (Euclid is the
  official enum name per the threat model's by-design list) -> 200;
  envelope: result must be the boolean true, status a string, time a
  number; (B) the created state must be real: describe returns 200 with
  result.config present and vectors.size==8; (C) queryability: upsert 2
  points wait=true -> count exact == 2 (qdrant_inv_create_queryable_001,
  qdrant_inv_count_consistency_001); (D) drop -> describe 404
  (qdrant_inv_delete_gone_001).
  [chunk_collections+create-2of2 coverage: count_consistency x
   qdrant_behavioral_collections_create_001 (success envelope shape +
   created-state reality)]
Oracle: create -> 200 with result===true (boolean), status (string),
  time (number) per response_shape; describe -> 200 with
  result.config.params.vectors.size==8; count exact == 2 after wait=true
  upsert; after drop -> describe 404. 200 with a malformed envelope
  (result not boolean-true / status not string / time not number) or a
  200 create whose state is absent (describe 404) or count mismatch =
  Type4_StateLogicViolation; 5xx judged Type3 only after /healthz
  confirms liveness.
"""

import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p / "scripts")
            break
if not _sd or not Path(_sd, "runtime", "__init__.py").exists():
    print("VERDICT: SCRIPT_ERROR - runtime scripts dir not found (TESTVDB_SCRIPTS_DIR unset)")
    sys.exit(2)
sys.path.insert(0, _sd)

if not os.environ.get("TESTVDB_TARGET"):
    for _p in Path(__file__).resolve().parents:
        _c = _p / "structured_contract.json"
        if _c.exists():
            try:
                _t = json.loads(_c.read_text(encoding="utf-8")).get("target", "")
                if _t:
                    os.environ["TESTVDB_TARGET"] = str(_t).lower()
            except Exception:
                pass
            break

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
        return b if isinstance(b, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scc2b_" + TS + "_"
    C = PFX + "env"
    DEFECTS = []

    try:
        # ---- (A) valid create -> 200 + CollectionOperationResponse envelope ----
        s, raw = safe_request("PUT", "create_collection", path_params={"name": C},
                              body={"vectors": {"size": 8, "distance": "Euclid"}})
        print(f"[A create] status={s} raw={raw[:300]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[A transport] healthz status={hs} raw={str(hraw)[:120]}")
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[A 5xx liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print(f"DEFECT: (A) valid create returned {s} with service alive — "
                  f"Type3_RuntimeFailure — raw={raw[:200]}")
            return "DEFECT_FOUND"
        if s not in (200, 201):
            print(f"SETUP_ERROR: valid create rejected with {s} — cannot judge success envelope")
            return "SCRIPT_ERROR"

        body = parse_json(raw)
        if body is None:
            DEFECTS.append(f"(A) 200 create body is not a JSON object — envelope "
                           f"promise violated — Type4_StateLogicViolation — raw={raw[:200]}")
        else:
            if body.get("result") is not True:
                DEFECTS.append(f"(A) envelope result={body.get('result')!r}, expected "
                               f"boolean true (response_shape result:boolean) — "
                               f"Type4_StateLogicViolation")
            if not isinstance(body.get("status"), str):
                DEFECTS.append(f"(A) envelope status={body.get('status')!r} is not a "
                               f"string (response_shape status:string) — "
                               f"Type4_StateLogicViolation")
            if not isinstance(body.get("time"), (int, float)):
                DEFECTS.append(f"(A) envelope time={body.get('time')!r} is not a "
                               f"number (response_shape time:number) — "
                               f"Type4_StateLogicViolation")

        # ---- (B) created state must be real: describe 200 + config present ----
        ds, draw = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[B describe] status={ds} raw={draw[:300]}")
        dbody = parse_json(draw)
        cfg = ((dbody or {}).get("result") or {}).get("config") if dbody else None
        if ds != 200 or not isinstance(cfg, dict):
            if ds == 404:
                DEFECTS.append(f"(B) create returned 200 but describe returned 404 — "
                               f"promised created state is absent — "
                               f"Type4_StateLogicViolation")
            else:
                print(f"SETUP_ERROR: describe returned {ds} — cannot verify created state")
                return "SCRIPT_ERROR"
        else:
            vec = (cfg.get("params") or {}).get("vectors")
            size = vec.get("size") if isinstance(vec, dict) else None
            if size != 8:
                DEFECTS.append(f"(B) created config vectors.size={size!r}, "
                               f"requested 8 — Type4_StateLogicViolation")

        # ---- (C) queryability: upsert 2 wait=true -> count exact == 2 ----
        pts = [{"id": i, "vector": [0.1] * 8} for i in range(2)]
        us, uraw = safe_request("PUT", "upsert_points", path_params={"name": C},
                                body={"points": pts}, query_params={"wait": "true"})
        print(f"[C upsert] status={us} raw={uraw[:160]}")
        if us == 0 or 500 <= us <= 599:
            hs, hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[C liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print(f"DEFECT: (C) upsert returned {us} with service alive — "
                  f"Type3_RuntimeFailure — raw={uraw[:200]}")
            return "DEFECT_FOUND"
        if us not in (200, 201):
            print(f"SETUP_ERROR: upsert returned {us} — cannot judge count")
            return "SCRIPT_ERROR"
        cs, craw = safe_request("POST", "count", path_params={"name": C},
                                body={"exact": True})
        print(f"[C count] status={cs} raw={craw[:200]}")
        cbody = parse_json(craw)
        cnt = ((cbody or {}).get("result") or {}).get("count") if cbody else None
        if cs == 0 or 500 <= cs <= 599:
            hs, hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[C count liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print(f"DEFECT: (C) count returned {cs} with service alive — "
                  f"Type3_RuntimeFailure — raw={craw[:200]}")
            return "DEFECT_FOUND"
        if cs != 200 or not isinstance(cnt, int):
            print("SETUP_ERROR: count exact failed — cannot judge invariant")
            return "SCRIPT_ERROR"
        if cnt != 2:
            DEFECTS.append(f"(C) count inconsistency: inserted 2 points wait=true, "
                           f"count exact={cnt} (expected 2) — "
                           f"Type4_StateLogicViolation (qdrant_inv_count_consistency_001)")

        # ---- (D) drop -> describe must 404 ----
        dls, dlraw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[D drop] status={dls} raw={dlraw[:160]}")
        if dls not in (200, 201, 404):
            hs, hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[D liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print(f"DEFECT: (D) drop returned {dls} with service alive — "
                  f"Type3_RuntimeFailure — raw={dlraw[:200]}")
            return "DEFECT_FOUND"
        gs, graw = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[D describe-after-drop] status={gs} raw={graw[:160]}")
        if gs != 404:
            DEFECTS.append(f"(D) describe after verified drop returned {gs} "
                           f"(expected 404) — ghost collection state — "
                           f"Type4_StateLogicViolation (qdrant_inv_delete_gone_001)")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
