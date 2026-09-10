#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_delete_001
# strategy: state_idempotent_delete_lifecycle
# endpoint: index+delete
# constraint_ids: qdrant_state_index_delete_001, qdrant_behavioral_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the "idempotent success" wording is
#            assumed honored on every repeat leg; a 404/409 surfacing on the 2nd/3rd
#            delete, or a describe echo that still lists the deleted index, would mean
#            the idempotent-success promise is not actually closed on this face)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state idempotent-delete lifecycle x qdrant_state_index_delete_001 (promise:
  "delete of a non-existent payload index is an idempotent success") +
  qdrant_behavioral_index_delete_001 (promise: "index deletion (existing or not)
  returns HTTP 200"). G4 both directions on one live bidl1_* collection: (1) create a
  keyword payload index (wait=true query param, per placement check), describe-gate
  that result.payload_schema echoes it; (2) FIRST delete (existing index) must be 200
  and the describe readback must show the field GONE (persistence judged via describe
  echo, not the ack alone — R21 lesson); (3) SECOND delete (now non-existent) must
  again be 200 (the idempotent-success promise itself); (4) THIRD delete still 200
  (closure under repetition); (5) delete of a payload-bearing field that NEVER had an
  index must be 200; (6) delete of a never-existing field name must be 200. Envelope
  shape per response_shape grid (index+delete declares result: object,
  result.status: string, result.operation_id: [integer, null]): every 200 leg is
  checked for result-as-object + result.status-as-string; a non-object result is
  printed SHAPE_CONFLICT measured-only (spec wins on paper; no defect from envelope
  shape alone — D3b conflict-zone discipline).
  [chunk_index+delete coverage: state_idempotent_delete_lifecycle x
  qdrant_state_index_delete_001 (idempotent-success face, repeat legs) x
  qdrant_behavioral_index_delete_001 (existing-index 200 + non-existent 200 faces)]
Oracle: on the live collection, delete #1 (existing index) returns HTTP 200 AND the
  collections+get readback result.payload_schema no longer contains the field (residue
  = Type4_StateLogicViolation); deletes #2/#3 and the never-indexed/never-existing
  field legs each return exactly HTTP 200 (any 404/409/4xx on them contradicts the
  unconditional idempotent-200 promise — legal input rejected, Type1_IllegalSuccess
  signal per session convention); 5xx/transport = Type3_RuntimeFailure with /healthz
  liveness re-check; 200 legs whose result is not an object with a string status are
  printed SHAPE_CONFLICT measured-only (no defect claim).
Constraint: qdrant_state_index_delete_001 (bare id) — "delete of a non-existent
  payload index is an idempotent success; index deletion leaves point data untouched"
  (evidence_tier: explicit; level: system); qdrant_behavioral_index_delete_001 (bare
  id) — "index deletion (existing or not) returns HTTP 200; missing collection
  returns 404" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  index+delete       -> DELETE /collections/{collection_name}/index/{field_name}
  index+create       -> PUT    /collections/{collection_name}/index
  collections+create -> PUT    /collections/{collection_name}
  collections+get    -> GET    /collections/{collection_name}
  points+upsert      -> PUT    /collections/{collection_name}/points
  healthz            -> GET    /healthz  (runtime PATHS key "healthz")
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

# path keys verified against qdrant runtime PATHS: create_index/delete_index/
# describe_collection/upsert_points/create_collection/drop_collection/healthz
print(f"[PATHS] index-delete keys present="
      f"{[k for k in ('delete_index', 'create_index', 'describe_collection', 'drop_collection') if k in rt.PATHS]}")


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    """Transport/5xx branch liveness re-check via the lightweight healthz face."""
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def describe_payload_schema(tag, collection):
    """collections+get readback -> result.payload_schema map (or None).
    Returns (schema_map_or_None, ok)."""
    s, raw = safe_request("GET", "describe_collection",
                          path_params={"name": collection})
    print(f"[{tag}] describe status={s} raw={str(raw)[:300]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict):
        return None, False
    ps = res.get("payload_schema")
    if ps is None:
        return {}, True
    if not isinstance(ps, dict):
        return None, False
    return ps, True


def check_200_envelope(tag, status, raw, defects):
    """Shape-grid adjudication for a 200 leg: result must be an object carrying a
    string status (response_shape: result.object / result.status.string /
    result.operation_id [integer, null]). Non-object result = SHAPE_CONFLICT
    measured-only (D3b conflict zone; live R21 evidence shows the object form)."""
    if status not in (200, 201):
        return
    b = parse_json(raw)
    if b is None:
        print(f"[{tag}] SHAPE_CONFLICT(measured-only): 200 body not a JSON object: "
              f"{str(raw)[:160]}")
        return
    res = b.get("result")
    if not isinstance(res, dict):
        print(f"[{tag}] SHAPE_CONFLICT(measured-only): result is "
              f"{type(res).__name__}, response_shape declares object — "
              f"raw={str(raw)[:160]}")
        return
    rstat = res.get("status")
    if not isinstance(rstat, str):
        print(f"[{tag}] SHAPE_CONFLICT(measured-only): result.status is "
              f"{type(rstat).__name__}, response_shape declares string — "
              f"raw={str(raw)[:160]}")
    else:
        print(f"[{tag}] envelope ok: result.status={rstat!r} "
              f"operation_id={res.get('operation_id')!r}")


def adjudicate_delete(tag, status, raw, collection, defects):
    """One delete leg against the unconditional-200 promise on an existing
    collection. Returns True if the leg concluded (200/defect), False on
    script-error conditions."""
    print(f"[{tag}] DELETE index status={status} raw={str(raw)[:250]}")
    if status in (200, 201):
        check_200_envelope(tag, status, raw, defects)
        return True
    if status == 0 or 500 <= status <= 599:
        if not liveness(tag):
            return False
        defects.append(f"({tag}) status {status} while /healthz alive - "
                       f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
        return True
    defects.append(f"({tag}) HTTP {status} contradicts the unconditional "
                   f"idempotent-200 promise (existing or not) - legal input "
                   f"rejected - Type1_IllegalSuccess signal - "
                   f"raw={str(raw)[:160]} "
                   f"(qdrant_state_index_delete_001/qdrant_behavioral_index_delete_001)")
    return True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "bidl1_" + TS + "_"
    C = PFX + "col"
    FLD = "f_kw"          # field that WILL be indexed then deleted
    FLD_DATA = "f_txt"    # payload-bearing field, never indexed
    FLD_GHOST = "f_ghost"  # field never existing at all
    DEFECTS = []
    N = 6

    pts = [
        {"id": i,
         "vector": [0.1 + 0.01 * i, 0.2, 0.3, 0.4],
         "payload": {FLD: f"kw{i % 3}", FLD_DATA: f"alpha beta {i}"}}
        for i in range(1, N + 1)
    ]

    try:
        # ---- setup: collection + points + one keyword index ----
        ok, err = rt.setup_default(C, 4)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[setup upsert] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": FLD,
                                    "field_schema": {"type": "keyword"}},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[setup create index {FLD}] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"

        ps0, ok0 = describe_payload_schema("describe gate", C)
        if not ok0 or FLD not in ps0:
            print(f"VERDICT: SCRIPT_ERROR - setup gate: {FLD} not echoed in "
                  f"payload_schema (ok={ok0}, echo={str(ps0)[:200]})")
            return "SCRIPT_ERROR"

        # ---- leg 1: delete #1 (EXISTING index) -> 200 + describe residue check ----
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": FLD},
                              query_params={"wait": "true"})
        if not adjudicate_delete("delete#1 existing", s, raw, C, DEFECTS):
            return "SCRIPT_ERROR"
        ps1, ok1 = describe_payload_schema("describe after delete#1", C)
        if ok1 and FLD in ps1:
            DEFECTS.append(
                f"(describe) field {FLD} deleted with 200 but still present in "
                f"result.payload_schema (echo={str(ps1.get(FLD))[:160]}) - ack "
                f"without persistence - Type4_StateLogicViolation "
                f"(qdrant_state_index_delete_001)")

        # ---- legs 2-3: repeat deletes (now NON-EXISTENT) -> still 200 ----
        for leg in ("delete#2 non-existent", "delete#3 non-existent"):
            s, raw = safe_request("DELETE", "delete_index",
                                  path_params={"name": C, "field_name": FLD},
                                  query_params={"wait": "true"})
            if not adjudicate_delete(leg, s, raw, C, DEFECTS):
                return "SCRIPT_ERROR"

        # ---- leg 4: payload-bearing field that NEVER had an index -> 200 ----
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": FLD_DATA},
                              query_params={"wait": "true"})
        if not adjudicate_delete("delete never-indexed payload field", s, raw, C, DEFECTS):
            return "SCRIPT_ERROR"

        # ---- leg 5: field name that never existed at all -> 200 ----
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": FLD_GHOST},
                              query_params={"wait": "true"})
        if not adjudicate_delete("delete never-existing field", s, raw, C, DEFECTS):
            return "SCRIPT_ERROR"

        # ---- summary ----
        print(f"[summary] 5 delete legs on live collection; describe residue="
              f"{'none' if (ok1 and FLD not in ps1) else 'see defects'}; "
              f"defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("idempotent delete lifecycle complete: existing-index delete 200 with "
              "describe-clean readback; 2nd/3rd repeat deletes, never-indexed "
              "payload field and never-existing field all 200 — unconditional "
              "idempotent-200 promise holds on every leg - NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup (own data only; failure must not flip the verdict)
        try:
            rt.drop_collection(C)
            print(f"[cleanup] dropped {C}")
        except Exception as e:
            print(f"[cleanup] drop {C} failed (ignored): {e}")


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
