#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_delete_005
# strategy: strategy1_query_param_boundary
# endpoint: index+delete
# constraint_ids: qdrant_behavioral_index_delete_001, qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — wait: boolean, ordering:
#            string enum, timeout: integer are assumed validated/coerced sanely;
#            BS-04 Boundary Default Optimism — extreme timeout magnitudes are
#            assumed not to hang or crash the request path)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy-1 boundary / strategy-2 coercion attack on the QUERY parameters of
  index+delete (placement check: wait/ordering/timeout are query parameters per the
  contract parameter table — they go into the URL query string via query_params,
  NEVER into the body; stuffing them into the body makes the probe ineffective per
  the v34 R1 lesson) x qdrant_behavioral_index_delete_001 (disposition promise:
  "index deletion (existing or not) returns HTTP 200") +
  qdrant_state_index_delete_001 (idempotent success). Every leg is a
  non-existent-index delete (the unconditional-200 face) on a live bidl5_*
  collection, varying only the query string:
  valid legs (promise-200 adjudication): wait=true; wait=false; ordering=strong;
  combined wait=true+ordering=strong+timeout=30 — each must return exactly 200.
  boundary/coercion legs (measured-only disposition; only 5xx or hang claimed):
  wait=yes (invalid boolean literal), wait=1 (numeric-bool coercion),
  timeout=0, timeout=-1 (negative), timeout=2147483647 (i32 max),
  timeout=99999999999999999999 (i64/u64 overflow), timeout=abc (string for
  integer). These legs are sent WITHOUT wait so the server has no documented
  reason to block; a client-side read-timeout with /healthz alive is therefore a
  server-side hang = Type3_RuntimeFailure (resource-limit face of strategy 6).
  200 envelopes are checked against the response_shape grid (result: object,
  result.status: string); non-conforming results printed SHAPE_CONFLICT
  measured-only.
  [chunk_index+delete coverage: strategy1_query_param_boundary x
  qdrant_behavioral_index_delete_001 (200-disposition face under query-param
  boundary values) x qdrant_state_index_delete_001 (idempotent-success face)]
Oracle: valid legs (wait=true / wait=false / ordering=strong / combined) each
  return exactly HTTP 200 (non-200 = legal input rejected, Type1_IllegalSuccess
  signal); coercion/boundary legs accept 200 or any clean 4xx disposition
  (measured-only print); ANY 5xx = Type3_RuntimeFailure with /healthz re-check;
  a read-timeout (status 0, timeout-class error, /healthz alive) on a no-wait leg
  = server-side hang = Type3_RuntimeFailure; connection loss with /healthz down =
  SCRIPT_ERROR (no defect conclusion).
Constraint: qdrant_behavioral_index_delete_001 (bare id) — "index deletion
  (existing or not) returns HTTP 200; missing collection returns 404"
  (evidence_tier: explicit; level: endpoint); qdrant_state_index_delete_001 (bare
  id) — "delete of a non-existent payload index is an idempotent success"
  (evidence_tier: explicit; level: system)

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

print(f"[PATHS] keys present="
      f"{[k for k in ('delete_index', 'describe_collection', 'drop_collection') if k in rt.PATHS]}")

# (tag, query_params dict, class) — class "valid" = promise-200 adjudication,
# "measured" = disposition printed, only 5xx/hang claimed. Strings only (bool
# values would be serialized as "True"/"False" by the HTTP layer).
LEGS = [
    ("wait=true",          {"wait": "true"},                      "valid"),
    ("wait=false",         {"wait": "false"},                     "valid"),
    ("ordering=strong",    {"ordering": "strong"},                "valid"),
    ("combined-valid",     {"wait": "true", "ordering": "strong",
                            "timeout": "30"},                     "valid"),
    ("wait=yes",           {"wait": "yes"},                       "measured"),
    ("wait=1",             {"wait": "1"},                         "measured"),
    ("timeout=0",          {"timeout": "0"},                      "measured"),
    ("timeout=-1",         {"timeout": "-1"},                     "measured"),
    ("timeout=i32max",     {"timeout": "2147483647"},             "measured"),
    ("timeout=overflow20", {"timeout": "99999999999999999999"},   "measured"),
    ("timeout=abc",        {"timeout": "abc"},                    "measured"),
    ("ordering=bogus",     {"ordering": "not_an_ordering"},       "measured"),
]


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


def check_200_envelope(tag, status, raw):
    """200 leg vs response_shape grid: result must be an object with a string
    status. Non-conforming = SHAPE_CONFLICT measured-only print."""
    if status not in (200, 201):
        return
    b = parse_json(raw)
    res = (b or {}).get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        print(f"[{tag}] SHAPE_CONFLICT(measured-only): result is "
              f"{type(res).__name__}, response_shape declares object — "
              f"raw={str(raw)[:160]}")
        return
    if not isinstance(res.get("status"), str):
        print(f"[{tag}] SHAPE_CONFLICT(measured-only): result.status is "
              f"{type(res.get('status')).__name__}, declared string — "
              f"raw={str(raw)[:160]}")
    else:
        print(f"[{tag}] envelope ok: result.status={res.get('status')!r} "
              f"operation_id={res.get('operation_id')!r}")


def classify_transport(tag, raw, defects):
    """status-0 branch for query-param legs: a read-timeout with /healthz alive
    on a no-wait leg is a server-side hang (Type3); a dead service is
    SCRIPT_ERROR. Returns False on script-error."""
    txt = str(raw).lower()
    timeout_class = ("timed out" in txt) or ("timeout" in txt)
    alive = liveness(tag)
    if timeout_class and alive:
        defects.append(f"({tag}) read-timeout on a no-wait idempotent delete leg "
                       f"while /healthz alive - server-side hang - "
                       f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
        return True
    if not alive:
        return False
    defects.append(f"({tag}) transport failure while /healthz alive - "
                   f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
    return True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "bidl5_" + TS + "_"
    C = PFX + "col"
    FLD = "f_kw"  # never indexed on this collection -> every leg is promise-face
    DEFECTS = []

    try:
        # ---- setup: live collection, NO index ever created ----
        ok, err = rt.setup_default(C, 4)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"

        # ---- act: same delete, only the query string varies ----
        dispositions = {}
        for tag, qp, cls in LEGS:
            s, raw = safe_request("DELETE", "delete_index",
                                  path_params={"name": C, "field_name": FLD},
                                  query_params=qp, timeout=20)
            dispositions[tag] = s
            print(f"[leg {tag} qp={qp}] status={s} raw={str(raw)[:250]}")
            if s == 0:
                if not classify_transport(tag, raw, DEFECTS):
                    return "SCRIPT_ERROR"
                continue
            if 500 <= s <= 599:
                if not liveness(tag):
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"({tag}) qp={qp} got HTTP {s} while /healthz "
                               f"alive - Type3_RuntimeFailure - "
                               f"raw={str(raw)[:160]}")
                continue
            if s in (200, 201):
                check_200_envelope(tag, s, raw)
                continue
            if cls == "valid":
                DEFECTS.append(f"({tag}) valid query parameters qp={qp} got HTTP "
                               f"{s}; the promise 'index deletion (existing or "
                               f"not) returns HTTP 200' is unconditional - legal "
                               f"input rejected - Type1_IllegalSuccess signal - "
                               f"raw={str(raw)[:160]} "
                               f"(qdrant_behavioral_index_delete_001)")
            else:
                print(f"[leg {tag}] disposition measured-only: {s} "
                      f"(coercion/boundary value; 200 or clean 4xx both "
                      f"defensible; only 5xx/hang claimed)")

        # ---- summary ----
        print(f"[summary] legs={len(LEGS)} dispositions={dispositions} "
              f"defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("query-param boundary grid on the idempotent delete face: all valid "
              "legs (wait/ordering/combined) returned exactly 200 with conforming "
              "envelopes; coercion and boundary values (wait=yes/1, timeout "
              "0/-1/i32max/overflow/abc, ordering=bogus) produced no 5xx and no "
              "server-side hang - NO_DEFECT")
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
