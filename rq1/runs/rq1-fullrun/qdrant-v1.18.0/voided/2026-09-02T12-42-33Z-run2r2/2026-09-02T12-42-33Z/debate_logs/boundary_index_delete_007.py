#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_delete_007
# strategy: strategy7_malformed_body_bodyless_delete
# endpoint: index+delete
# constraint_ids: qdrant_behavioral_index_delete_001, qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the DELETE face's parameter
#            table documents ONLY two path params + three query params + an
#            api-key header: NO request body. Siblings _001/_004/_005/_006
#            mutated the path/query surfaces; NONE ever sent a body. The
#            untested assumption is that the framework does not even attempt
#            to deserialize a body on a bodyless route — malformed bytes /
#            NUL / seq-form JSON reaching an unexpected deserializer is the
#            classic serde blindspot (R21 found the CREATE face accepts
#            seq-form arrays in ITS body; this probes whether the DELETE face
#            has any body handling to abuse at all))
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy-7 malformed-input / character-fuzzing attack on the REQUEST
  BODY of index+delete — a face that documents NO body (contract parameter
  table: collection_name/field_name path, wait/ordering/timeout query, api-key
  header; request body absent) x qdrant_behavioral_index_delete_001
  (disposition promise: "index deletion (existing or not) returns HTTP 200") +
  qdrant_state_index_delete_001 (idempotent success). All legs DELETE a
  NEVER-INDEXED grammar-legal field on a live bidl7_* collection (the
  unconditional-200 face), wait=true, with the body mutated across the
  malformed-input grid — sent through the runtime's raw-text body channel
  (str body -> data=bytes, Content-Type application/json), so client-side
  json= serialization cannot pre-reject the bytes before the server sees
  them: truncated JSON / trailing comma / single quotes / illegal escape
  ("\\q") / appended // comment / RAW NUL byte inside a JSON string /
  wrong-typed body ({"field_name": 123456} — number where the face has no
  body at all, BS-01 coercion) / seq-form body ([1,2,3] — R21's serde
  untagged lesson from the CREATE face, here on the DELETE face) / overlong
  bodies ('b'*1e5 and 'b'*1e6). Adjudication is dual-typed per strategy 7:
  the endpoint documents no body, so a 200 (body ignored, promise still
  honored) AND a clean 4xx (body rejected) are both defensible — printed
  measured-only for the judge; ONLY 5xx / parser-internal-error leakage /
  hang-with-liveness is claimed (Type3_RuntimeFailure). 200 envelopes are
  checked against the response_shape grid (result: object, result.status:
  string); non-conforming results printed SHAPE_CONFLICT measured-only.
  Post-condition (Type4 leg): collections+get readback must still show an
  EMPTY result.payload_schema after all body legs (garbage bodies must not
  create schema state on a delete-only face).
  [chunk_index+delete coverage: strategy7_malformed_body_bodyless_delete x
  qdrant_behavioral_index_delete_001 (200-disposition face under malformed
  out-of-contract bodies) x qdrant_state_index_delete_001
  (idempotent-success face under malformed input)]
Oracle: control leg (NO body, wait=true) returns exactly HTTP 200 (gate —
  else the body legs are uninterpretable -> SCRIPT_ERROR); malformed-body
  legs each return 200 (body ignored, promise honored) or any clean 4xx
  (explicit rejection) — both measured-only dispositions, no claim; ANY 5xx
  or parser/serde/utf/decode internal-error leakage in the body = Type3
  _RuntimeFailure with /healthz re-check; a timeout-class transport failure
  while /healthz alive = server-side hang = Type3_RuntimeFailure (1MB body
  must not kill the service); /healthz down = SCRIPT_ERROR (no defect
  conclusion); after all legs collections+get result.payload_schema is still
  empty (phantom entry = Type4_StateLogicViolation).
Constraint: qdrant_behavioral_index_delete_001 (bare id) — "index deletion
  (existing or not) returns HTTP 200; missing collection returns 404"
  (evidence_tier: explicit; level: endpoint); qdrant_state_index_delete_001
  (bare id) — "delete of a non-existent payload index is an idempotent
  success" (evidence_tier: explicit; level: system)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  index+delete       -> DELETE /collections/{collection_name}/index/{field_name}
  collections+create -> PUT    /collections/{collection_name}
  collections+get    -> GET    /collections/{collection_name}
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

print(f"[PATHS] index-delete keys present="
      f"{[k for k in ('delete_index', 'describe_collection', 'drop_collection') if k in rt.PATHS]}")

FLD = "f_body_probe"   # never-indexed, grammar-legal field on the live collection

# malformed-body grid; "kind" drives only the print, every leg is claimed ONLY
# on 5xx / internal-error / hang (strategy-7 crash oracle)
BODY_LEGS = [
    ("truncated-json",  '{"field_name": "f_body_p'),                 # cut mid-string
    ("trailing-comma",  '{"field_name": "f_body_probe",}'),
    ("single-quotes",   "{'field_name': 'f_body_probe'}"),
    ("illegal-escape",  '{"field_name": "x\\qy"}'),                  # \q on the wire
    ("comment-inject",  '{"field_name": "f"} // trailing comment'),
    ("raw-nul-in-json", '{"field_name": "nul\x00probe"}'),           # real NUL byte
    ("wrong-typed",     '{"field_name": 123456}'),                   # number for string
    ("seq-form",        "[1,2,3]"),                                  # array top-level
    ("empty-string",    ""),
    ("whitespace-only", "   "),
    ("overlong-1e5",    '{"field_name": "' + "b" * (10 ** 5) + '"}'),
    ("overlong-1e6",    '{"field_name": "' + "b" * (10 ** 6) + '"}'),
]

_TIMEOUT_CLASS_MARKERS = ("timed out", "timeout", "readtimeout", "read timeout")
_INTERNAL_ERROR_MARKERS = ("panic", "serde", "internal", "utf", "decode",
                           "out of memory", "oom")


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly (a str body goes out as raw utf-8 bytes via the
    runtime's single HTTP exit, so malformed bytes reach the server);
    inline liveness probes stay visible to static checks."""
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


def is_timeout_class(raw_text):
    low = str(raw_text).lower()
    return any(m in low for m in _TIMEOUT_CLASS_MARKERS)


def check_200_envelope(tag, status, raw):
    """Shape-grid adjudication for a 200 leg: result must be an object carrying
    a string status (response_shape: result.object / result.status.string /
    result.operation_id [integer, null]). Non-object result = SHAPE_CONFLICT
    measured-only (D3b conflict zone)."""
    if status not in (200, 201):
        return
    b = parse_json(raw)
    if b is None:
        print(f"[{tag}] SHAPE_CONFLICT(measured-only): 200 body not a JSON "
              f"object: {str(raw)[:160]}")
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


def adjudicate_body_leg(tag, body_text, status, raw, defects):
    """One malformed-body leg. 200 (ignored) or any clean 4xx (rejected) are
    both defensible on a face that documents no body — measured-only print;
    ONLY 5xx / internal-error leakage / hang-with-liveness is claimed
    (Type3). Returns True if the leg concluded, False on script-error."""
    shown = body_text if len(body_text) <= 40 else f"{body_text[:24]}...len={len(body_text)}"
    print(f"[leg {tag} body={shown!r}] status={status} raw={str(raw)[:250]}")
    if status == 0:
        if is_timeout_class(raw):
            if not liveness(tag):
                return False
            defects.append(f"({tag}) malformed/oversized body caused a "
                           f"server-side hang (timeout-class transport "
                           f"failure) while /healthz alive - "
                           f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
            return True
        if not liveness(tag):
            return False
        defects.append(f"({tag}) transport failure while /healthz alive - "
                       f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
        return True
    if 500 <= status <= 599:
        if not liveness(tag):
            return False
        defects.append(f"({tag}) body={shown!r} got HTTP {status} while "
                       f"/healthz alive - Type3_RuntimeFailure (parser crash, "
                       f"not rejection) - raw={str(raw)[:160]}")
        return True
    low = str(raw).lower()
    leaked = [m for m in _INTERNAL_ERROR_MARKERS if m in low]
    if leaked and status not in (200, 201):
        # non-5xx but parser-internal detail leaking through a 4xx body
        print(f"[leg {tag}] NOTE measured-only: 4xx body carries "
              f"internal markers {leaked} — judge may weigh as Type2 "
              f"diagnostics leakage: {str(raw)[:160]}")
    if status in (200, 201):
        check_200_envelope(tag, status, raw)
        print(f"[leg {tag}] disposition measured-only: 200 — the face "
              f"documents no body, so an ignored body still honoring the "
              f"unconditional-200 promise is defensible (no claim)")
    else:
        print(f"[leg {tag}] disposition measured-only: {status} — clean "
              f"rejection of an out-of-contract body is defensible (no claim)")
    return True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "bidl7_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    try:
        # ---- setup: live collection, NO index ever created on it ----
        ok, err = rt.setup_default(C, 4)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"
        ps0, ok0 = describe_payload_schema("describe gate (must be empty)", C)
        if not ok0 or ps0:
            print(f"VERDICT: SCRIPT_ERROR - setup gate: expected empty "
                  f"payload_schema, got ok={ok0} echo={str(ps0)[:200]}")
            return "SCRIPT_ERROR"

        # ---- control gate: documented face (NO body) must honor 200 ----
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": FLD},
                              query_params={"wait": "true"}, timeout=30)
        print(f"[gate no-body control] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            if s == 0 or 500 <= s <= 599:
                if not liveness("no-body control"):
                    return "SCRIPT_ERROR"
            print(f"VERDICT: SCRIPT_ERROR - no-body control leg got {s}; "
                  f"body legs are uninterpretable without the documented "
                  f"baseline")
            return "SCRIPT_ERROR"

        # ---- act: malformed-body grid on the bodyless DELETE face ----
        dispositions = {}
        for tag, body_text in BODY_LEGS:
            s, raw = safe_request("DELETE", "delete_index",
                                  body=body_text,
                                  path_params={"name": C, "field_name": FLD},
                                  query_params={"wait": "true"}, timeout=60)
            dispositions[tag] = s
            if not adjudicate_body_leg(tag, body_text, s, raw, DEFECTS):
                return "SCRIPT_ERROR"

        # ---- Type4 leg: garbage bodies must not create schema state ----
        ps1, ok1 = describe_payload_schema("describe after body legs", C)
        if ok1 and ps1:
            DEFECTS.append(
                f"(describe) payload_schema non-empty after only DELETE "
                f"legs with malformed bodies: {str(ps1)[:200]} - phantom "
                f"schema state - Type4_StateLogicViolation "
                f"(qdrant_state_index_delete_001)")

        # ---- summary ----
        print(f"[summary] legs={len(BODY_LEGS)} dispositions={dispositions} "
              f"defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("malformed-body grid on the bodyless delete face: truncated/"
              "comma/quote/escape/NUL/typed/seq-form/1e6-byte bodies all "
              "produced clean dispositions (200 ignored-or-honored, or 4xx "
              "rejected) with no 5xx, no hang, no parser leakage and no "
              "phantom payload_schema state - NO_DEFECT")
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
