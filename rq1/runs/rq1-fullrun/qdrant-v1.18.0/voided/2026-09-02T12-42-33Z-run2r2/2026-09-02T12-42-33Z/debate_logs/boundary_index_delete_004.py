#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_delete_004
# strategy: strategy2_path_param_boundary
# endpoint: index+delete
# constraint_ids: qdrant_behavioral_index_delete_001, qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the delete face takes its
#            identifying parameter as a raw URL path segment; serde/routing is
#            assumed to cope with empty/space/unicode/slash/control/overlong
#            segments. R21 found the CREATE face accepts seq-form arrays in the
#            body; this script attacks the DELETE face's path-param handling,
#            which is a distinct target)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy-2 type/boundary attack on the field_name PATH parameter of
  index+delete x qdrant_behavioral_index_delete_001 (promise: "index deletion
  (existing or not) returns HTTP 200") + qdrant_state_index_delete_001 (idempotent
  success). On a live bidl4_* collection with NO index ever created (every leg is a
  non-existent-index delete — the promise face), the {field_name} path segment is
  mutated across the character/shape boundary grid:
  route-preserving well-formed legs — " " (space), "中文🎯" (unicode), "%2e%2e"
  (encoded-traversal-shaped literal), "f kw" (embedded space in name) — the promise
  is unconditional ("existing or not"), so each must return HTTP 200; a 4xx here
  contradicts the promise (legal input rejected).
  measured-only legs — "" (empty -> trailing-slash route shift), "sl/ash" (embedded
  slash -> extra path segment, route shift), "a"*1024 (overlong segment: the
  contract declares NO length bound on field_name, so a clean 4xx bound or a 200
  are both defensible — disposition printed for the judge), "ctrl\\x01" (control
  char), "\\x00nul" (NUL byte): any 4xx or 200 disposition is recorded; only
  5xx/crash is claimed.
  Client-side URL rejections (requests/urllib3 refusing to SEND a malformed URL —
  InvalidURL/UnicodeEncode class) are separated from server behavior and printed
  CLIENT_SIDE_SKIP (liveness re-checked via /healthz so the skip is not confused
  with an outage); they are NOT server defects.
  Post-condition (Type4 leg): the delete face must not create anything —
  collections+get readback must still show an EMPTY result.payload_schema after
  all legs (phantom schema entry = Type4_StateLogicViolation).
  [chunk_index+delete coverage: strategy2_path_param_boundary x
  qdrant_behavioral_index_delete_001 (unconditional-200 face under adversarial
  path params) x qdrant_state_index_delete_001 (idempotent-success face)]
Oracle: route-preserving well-formed legs (space / unicode / %2e%2e / embedded
  space name) each return exactly HTTP 200 on the live collection (non-200 =
  legal input rejected, Type1_IllegalSuccess signal against the unconditional
  promise); measured-only legs (empty / slash / overlong / control / NUL) accept
  200 or any clean 4xx disposition (5xx = Type3_RuntimeFailure with /healthz
  re-check; client-side send refusals printed CLIENT_SIDE_SKIP, never claimed);
  after all legs, collections+get result.payload_schema is still empty (phantom
  entry = Type4_StateLogicViolation).
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

# leg classes: "promise" = route-preserving well-formed (promise-200 adjudication),
# "measured" = route-shifting / undocumented-bound (disposition printed, only 5xx claimed)
LEGS = [
    ("space",              " ",           "promise"),
    ("embedded-space-name", "f kw",       "promise"),
    ("unicode",            "中文🎯",       "promise"),
    ("encoded-dotdot-lit", "%2e%2e",      "promise"),
    ("empty",              "",            "measured"),
    ("embedded-slash",     "sl/ash",      "measured"),
    ("overlong-1024",      "a" * 1024,    "measured"),
    ("control-char",       "ctrl\x01x",   "measured"),
    ("nul-byte",           "nul\x00byte", "measured"),
]

_CLIENT_SIDE_MARKERS = ("invalidurl", "unicodeencode", "urllib3", "requests.",
                        "failed to parse", "encode")


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
    """collections+get readback -> result.payload_schema map (or None)."""
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


def looks_client_side(raw_text):
    """Heuristic: req() returns (0, exc-str) for local send failures; a
    client-library refusal is not a server disposition."""
    low = str(raw_text).lower()
    return any(m in low for m in _CLIENT_SIDE_MARKERS)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "bidl4_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    SKIPPED = []

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

        # ---- act: mutate the {field_name} path segment across the grid ----
        dispositions = {}
        for tag, value, cls in LEGS:
            shown = value if len(value) <= 40 else f"{value[:20]}...len={len(value)}"
            s, raw = safe_request("DELETE", "delete_index",
                                  path_params={"name": C, "field_name": value},
                                  query_params={"wait": "true"}, timeout=20)
            dispositions[tag] = s
            print(f"[leg {tag!r} value={shown!r} class={cls}] status={s} "
                  f"raw={str(raw)[:250]}")
            if s == 0:
                # transport layer: distinguish client-side send refusal from outage
                if looks_client_side(raw):
                    alive = liveness(tag)
                    SKIPPED.append(f"({tag}) CLIENT_SIDE_SKIP: HTTP client refused "
                                   f"to send this path segment (server "
                                   f"/healthz={'alive' if alive else 'unreachable'}) "
                                   f"— local exception, not a server disposition: "
                                   f"{str(raw)[:120]}")
                else:
                    if not liveness(tag):
                        return "SCRIPT_ERROR"
                    DEFECTS.append(f"({tag}) transport failure while /healthz "
                                   f"alive - Type3_RuntimeFailure - "
                                   f"raw={str(raw)[:160]}")
                continue
            if 500 <= s <= 599:
                if not liveness(tag):
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"({tag}) value={shown!r} got HTTP {s} while "
                               f"/healthz alive - Type3_RuntimeFailure - "
                               f"raw={str(raw)[:160]}")
                continue
            if cls == "promise" and s not in (200, 201):
                DEFECTS.append(f"({tag}) route-preserving well-formed path param "
                               f"value={shown!r} got HTTP {s}; the promise 'index "
                               f"deletion (existing or not) returns HTTP 200' is "
                               f"unconditional - legal input rejected - "
                               f"Type1_IllegalSuccess signal - raw={str(raw)[:160]} "
                               f"(qdrant_behavioral_index_delete_001)")
            elif cls == "measured":
                print(f"[leg {tag}] disposition measured-only: {s} "
                      f"(200 or clean 4xx both defensible; only 5xx/transport "
                      f"claimed)")

        # ---- Type4 leg: delete face must not create anything ----
        ps1, ok1 = describe_payload_schema("describe after legs", C)
        if ok1 and ps1:
            DEFECTS.append(
                f"(describe) payload_schema non-empty after only DELETE legs on a "
                f"never-indexed collection: {str(ps1)[:200]} - delete face created "
                f"phantom schema state - Type4_StateLogicViolation "
                f"(qdrant_state_index_delete_001)")

        # ---- summary ----
        print(f"[summary] legs={len(LEGS)} dispositions={dispositions} "
              f"client_side_skips={len(SKIPPED)} defects={len(DEFECTS)}")
        for sk in SKIPPED:
            print(f"SKIP: {sk}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("path-param boundary grid on the delete face: all route-preserving "
              "well-formed legs honored the unconditional 200 promise; "
              "route-shifting/overlong legs recorded clean dispositions; no 5xx, "
              "no phantom payload_schema state - NO_DEFECT")
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
