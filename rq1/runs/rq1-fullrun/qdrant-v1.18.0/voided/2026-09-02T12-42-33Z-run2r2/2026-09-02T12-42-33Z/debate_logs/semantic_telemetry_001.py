#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_telemetry_001
# strategy: behavioral_contract
# endpoint: telemetry
# constraint_ids: qdrant_type_telemetry_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/telemetry
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the documented TelemetryData shape vs
#   the sections actually served; note: /telemetry is in the doc_coverage
#   exclude list for accounting, but it IS contract-anchored and IS attacked
#   per this round's dispatch note)
"""
Attack: behavioral_contract (shape oracle) x
  constraints::qdrant_type_telemetry_001 (chunk_cluster+telemetry round; GET
  /telemetry, URL from raw_knowledge api_endpoints[telemetry].url, registered
  into runtime PATHS per the session PATHS-gap convention). The constraint
  (evidence_tier=explicit) asserts "response contains id, app, collections,
  cluster, requests, memory, hardware, search_pool, quota sections".
  R8-lesson cross-check BEFORE writing this oracle: every one of the 9
  sections exists as a result.<section> key in this endpoint's own
  response_shape grid (result.id:string, result.app with version-specific
  runtime_features like append_only_mutations/write_segment_manifest,
  result.collections.number_of_collections, result.cluster.status.role,
  result.requests.rest/grpc, result.memory.active_bytes,
  result.hardware.collection_data, result.search_pool.mode,
  result.quota.config.enabled) - i.e. the field list reconciles with the
  versioned OpenAPI response schema, so the oracle is spec-derived, not a
  synthesized flat grid.
  Legs:
    (a) default read GET /telemetry -> 200 + envelope {time:number,
        status:string, result:object} (behavioral floor);
    (b) max-verbosity read GET /telemetry?details_level=10 -> 200 + all 9
        sections present in result + result.id is a string (the primary
        falsifiable shape oracle; max verbosity removes the level-
        conditionality objection to section completeness);
    (c) repeat default read -> face stability across adjacent reads.
  [coverage: behavioral_contract x qdrant_type_telemetry_001
   (9-section TelemetryData shape + envelope + face stability)]
Oracle: GET /telemetry answers 200 with envelope status:string, time:number,
  result:object; at details_level=10 result contains ALL 9 documented
  sections id/app/collections/cluster/requests/memory/hardware/search_pool/
  quota and result.id is a string (a missing section or non-string id =
  Type4_StateLogicViolation; 4xx on the default read = Type1_IllegalRejection
  of the documented service face; 5xx with /healthz alive =
  Type3_RuntimeFailure; envelope violation = Type4) (constraint
  qdrant_type_telemetry_001).

Rationale (G4/G7/D3b): the shape oracle's accessed paths (result.<section>,
  result.id) and assertion types (object sections, string id) are taken
  verbatim from the endpoint's response_shape grid, so the success-path
  assertion is compatible with the spec-declared shape; the default leg
  carries the weaker envelope-only judgment to avoid inventing a
  level-conditional promise the constraint never states.
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

# ---- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p)
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

if os.environ.get("TESTVDB_TARGET", "").lower() != "qdrant":
    print(f"VERDICT: SCRIPT_ERROR - contract target mismatch (expected qdrant, got {os.environ.get('TESTVDB_TARGET')!r})")
    sys.exit(2)

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

if not os.environ.get("TESTVDB_DB_URL"):
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

# ---- runtime PATHS gap: register the contract-derived URL (raw_knowledge only) ----
TELEMETRY_KEY = "telemetry"
if TELEMETRY_KEY not in rt.PATHS:
    rt.PATHS[TELEMETRY_KEY] = "/telemetry"
print(f"[path derivation] telemetry = {rt.PATHS[TELEMETRY_KEY]} "
      f"(raw_knowledge api_endpoints[telemetry].url)")

# The 9 documented TelemetryData sections (constraint assertion text; each
# also present as result.<section> in this endpoint's response_shape grid)
SECTIONS = ["id", "app", "collections", "cluster", "requests", "memory",
            "hardware", "search_pool", "quota"]


def safe_request(method, path_key, body=None, path_params=None, query_params=None,
                timeout=30):
    """All HTTP through the runtime; forwards method/path_key/body/path_params/
    query_params/timeout exactly (standing lesson). Returns (status, raw_text)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def jload(raw):
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz")
    print(f"[{tag}] /healthz probe status={hs} raw={str(hraw)[:120]}")
    return hs


def read_face(query_params, tag):
    """GET /telemetry with liveness-typed failure handling; returns (st, raw)."""
    st, raw = safe_request("GET", TELEMETRY_KEY, query_params=query_params, timeout=35)
    print(f"[{tag}] status={st} raw={str(raw)[:400]}")
    if st == 0:
        liveness(f"{tag} transport")
        script_error(f"transport failure on {tag}; no defect conclusion")
    if 500 <= st <= 599:
        if liveness(f"{tag} 5xx") != 200:
            script_error(f"{tag} 5xx ({st}) and /healthz not 200; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"{tag} raised server error {st} while /healthz is alive; constraint "
               f"qdrant_type_telemetry_001 documents a 200 TelemetryData response, "
               f"never a crash; raw={str(raw)[:200]}")
    return st, raw


def check_envelope(st, raw, tag):
    """Envelope per this endpoint's response_shape: {time: number,
    status: string, result: object}. Returns result node."""
    b = jload(raw)
    if not isinstance(b, dict):
        defect("Type4_StateLogicViolation",
               f"[{tag}] body is not a JSON object: raw={str(raw)[:200]}; the documented "
               f"TelemetryData response requires the qdrant envelope object")
    env_status = b.get("status")
    if not isinstance(env_status, str):
        defect("Type4_StateLogicViolation",
               f"[{tag}] envelope field 'status' missing or not a string (got "
               f"{env_status!r}); response_shape declares status:string; "
               f"raw={str(raw)[:250]}")
    env_time = b.get("time")
    if env_time is not None and not (isinstance(env_time, (int, float))
                                     and not isinstance(env_time, bool)):
        defect("Type4_StateLogicViolation",
               f"[{tag}] envelope field 'time' present but not numeric (got {env_time!r}); "
               f"response_shape declares time:number; raw={str(raw)[:250]}")
    res = b.get("result")
    if not isinstance(res, dict):
        defect("Type4_StateLogicViolation",
               f"[{tag}] envelope field 'result' missing or not an object (got "
               f"{type(res).__name__}); response_shape declares result:object; "
               f"raw={str(raw)[:250]}")
    return res


def check_sections(res, tag):
    """Primary shape oracle: all 9 documented sections present + id string."""
    missing = [s for s in SECTIONS if s not in res]
    if missing:
        defect("Type4_StateLogicViolation",
               f"[{tag}] result is missing documented TelemetryData section(s) "
               f"{missing}; present keys={sorted(res.keys())}; constraint "
               f"qdrant_type_telemetry_001 asserts the response contains id, app, "
               f"collections, cluster, requests, memory, hardware, search_pool, quota "
               f"sections (each section is a result.<section> key in this endpoint's "
               f"OpenAPI response_shape); raw keys={sorted(res.keys())}")
    tid = res.get("id")
    if not isinstance(tid, str):
        defect("Type4_StateLogicViolation",
               f"[{tag}] result.id is not a string (got {tid!r}); response_shape "
               f"declares result.id:string; raw sections={sorted(res.keys())}")


def main():
    hs, hraw = safe_request("GET", "healthz")
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")

    # ---- (a) default read: the documented service face must answer 200 ----
    st, raw = read_face(None, "default GET /telemetry")
    if 400 <= st < 500:
        defect("Type1_IllegalRejection",
               f"the documented service telemetry face GET /telemetry refused with {st} "
               f"on its plain no-param read; constraint qdrant_type_telemetry_001 and "
               f"assertion qdrant_behavioral_telemetry_001 promise a 200 TelemetryData "
               f"response (this face is not distributed-mode-dependent, unlike the "
               f"R6-R8 mutating cluster faces); raw={str(raw)[:250]}")
    if not (200 <= st < 300):
        script_error(f"unexpected default GET /telemetry status {st}; no defect conclusion")
    check_envelope(st, raw, "default")
    print("[ok] default read: 200 + envelope {status, time, result} holds")

    # ---- (b) max-verbosity read: the primary 9-section shape oracle ----
    st, raw = read_face({"details_level": 10}, "GET /telemetry?details_level=10")
    if 400 <= st < 500:
        defect("Type1_IllegalRejection",
               f"GET /telemetry?details_level=10 refused with {st} although details_level "
               f"is the documented 0..10 verbosity parameter and 10 is its documented "
               f"maximum (boundary closure); raw={str(raw)[:250]}")
    if not (200 <= st < 300):
        script_error(f"unexpected GET /telemetry?details_level=10 status {st}; no defect conclusion")
    res = check_envelope(st, raw, "details_level=10")
    check_sections(res, "details_level=10")
    print(f"[ok] details_level=10: all 9 sections present "
          f"(sections={sorted(res.keys())}); result.id is a string")

    # ---- (c) repeat default read: the documented face must stay served ----
    st2, raw2 = read_face(None, "repeat GET /telemetry")
    if st2 != st:
        defect("Type4_StateLogicViolation",
               f"the documented 200 face flipped status {st} -> {st2} between two "
               f"adjacent default reads on an idle deployment; raw={str(raw2)[:250]}")
    check_envelope(st2, raw2, "repeat")

    print(f"[summary] /telemetry served the documented 200 TelemetryData face: "
          f"envelope OK, all 9 documented sections present at max verbosity, "
          f"face stable across adjacent reads")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
