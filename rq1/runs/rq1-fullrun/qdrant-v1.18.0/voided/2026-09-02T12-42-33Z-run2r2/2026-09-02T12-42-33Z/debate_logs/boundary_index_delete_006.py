#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_delete_006
# strategy: strategy6_resource_limit_path_length
# endpoint: index+delete
# constraint_ids: qdrant_behavioral_index_delete_001, qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 / BS-07 (resource-boundary optimism — boundary sibling _004
#            probed field_name at 10^3 (a clean disposition zone); this script
#            scales the SAME path-parameter family to 10^4/10^5/10^6, where the
#            defect class flips from contract-violation (Type1) to
#            resource-exhaustion (Type3): the router must allocate/parse a 1MB
#            path segment, and a panic/OOM/500/hang there is a DoS face the
#            10^3 probe could never see. Same-family generalization per G3:
#            collection_name is the sibling path param and gets the same ladder
#            on the missing-collection 404 face)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy-6 resource-limit / DoS attack on the PATH parameters of
  index+delete x qdrant_behavioral_index_delete_001 (disposition promise:
  "index deletion (existing or not) returns HTTP 200; missing collection
  returns 404") + qdrant_state_index_delete_001 (idempotent success). The
  contract declares NO length bound on field_name or collection_name (both
  plain required path strings), so the implementation's true ceiling is
  undiscoverable from the spec — exactly the gap strategy 6 exists for.
  Difference from _004 (10^3, contract-grammar face): here the alphabet stays
  GRAMMAR-LEGAL ('a'*n / 'z'*n — no JsonPath-grammar rejection can fire), so
  the only variable is LENGTH, and the oracle flips to no-crash: 200 (promise
  honored at absurd length) or any CLEAN 4xx (documented-or-not explicit
  length bound, e.g. 413/414/400) are both non-defects; ONLY 5xx / OOM / panic
  / hang-with-liveness is claimed (Type3_RuntimeFailure). Legs on a live
  bidl6_* never-indexed collection: control 'a'*8 (gate: must be 200), then
  'a'*10^4 / 'a'*10^5 / 'a'*10^6 field_name segments. Same-family legs on
  NEVER-CREATED ghost collections (G3 generalization; fresh unique names,
  nothing to clean up): 'z'*10^4 / 'z'*10^5 collection_name — the promise
  face there is 404 (missing collection), with 413/414 length rejections
  equally clean; 5xx = Type3. G6 mutation justification: a 1MB path segment
  is the single cheapest input that forces the router to allocate linearly
  in attacker-controlled size BEFORE any schema lookup — the timing point
  where a length check is most easily forgotten (validation happens on the
  parsed field value, allocation happens on the raw segment).
  Post-condition (Type4 leg): collections+get readback must still show an
  EMPTY result.payload_schema after all legs (the delete face must not create
  phantom schema state regardless of input size).
  [chunk_index+delete coverage: strategy6_resource_limit_path_length x
  qdrant_behavioral_index_delete_001 (200 face + missing-collection 404 face
  under extreme-length path params) x qdrant_state_index_delete_001
  (idempotent-success face under resource-extreme values)]
Oracle: control leg ('a'*8, live collection) returns exactly HTTP 200 (gate —
  if it does not, later length legs are uninterprelatable -> SCRIPT_ERROR);
  resource legs ('a'*10^4/10^5/10^6 on the live collection) accept 200 or any
  clean 4xx (explicit length bound is a defensible disposition — measured-
  only print); ghost-collection legs ('z'*10^4/10^5 never-created) accept 404
  (promise) or 413/414 (clean length rejection) — measured-only; ANY 5xx =
  Type3_RuntimeFailure with /healthz re-check; a timeout-class transport
  failure while /healthz alive = server-side hang = Type3_RuntimeFailure;
  /healthz down = SCRIPT_ERROR (no defect conclusion); after all legs
  collections+get result.payload_schema is still empty (phantom entry =
  Type4_StateLogicViolation).
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

_TIMEOUT_CLASS_MARKERS = ("timed out", "timeout", "readtimeout", "read timeout")


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


def is_timeout_class(raw_text):
    low = str(raw_text).lower()
    return any(m in low for m in _TIMEOUT_CLASS_MARKERS)


def adjudicate_resource_leg(tag, shown, status, raw, expect_face, defects):
    """One resource-extreme leg. expect_face: 'promise-200' (live collection,
    unconditional 200) or 'promise-404' (ghost collection, missing-collection
    404). Clean dispositions (200 or 4xx incl. 413/414) are measured-only for
    BOTH faces — strategy 6 demands no-crash, not rejection; only 5xx /
    hang-with-liveness is claimed (Type3). Returns True if the leg concluded,
    False on script-error conditions."""
    print(f"[leg {tag} value={shown} face={expect_face}] status={status} "
          f"raw={str(raw)[:250]}")
    if status == 0:
        if is_timeout_class(raw):
            # attacker-supplied 1MB URL segment made the server stop responding
            # within the client timeout while the service is still alive
            if not liveness(tag):
                return False
            defects.append(f"({tag}) length={shown} caused a server-side hang "
                           f"(timeout-class transport failure) while /healthz "
                           f"alive - Type3_RuntimeFailure - raw={str(raw)[:160]}")
            return True
        if not liveness(tag):
            return False
        defects.append(f"({tag}) length={shown} transport failure while "
                       f"/healthz alive - Type3_RuntimeFailure - "
                       f"raw={str(raw)[:160]}")
        return True
    if 500 <= status <= 599:
        if not liveness(tag):
            return False
        defects.append(f"({tag}) length={shown} got HTTP {status} while "
                       f"/healthz alive - Type3_RuntimeFailure (resource-"
                       f"exhaustion face, crash not rejection) - "
                       f"raw={str(raw)[:160]}")
        return True
    # clean disposition: 200 or any 4xx (incl. explicit length bounds 413/414)
    verdict_face = {"promise-200": "200 (promise honored at extreme length)",
                    "promise-404": "404 (missing-collection promise)"}[expect_face]
    print(f"[leg {tag}] disposition measured-only: {status} "
          f"(expected face: {verdict_face}; any clean 200/4xx incl. explicit "
          f"length bound 413/414 is a non-defect for the resource class)")
    return True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "bidl6_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    # resource ladder (grammar-legal alphabet so ONLY length varies vs _004)
    LIVE_LEGS = [
        ("control-a8",     "a" * 8),        # gate: documented-zone control
        ("field-a1e4",     "a" * 10 ** 4),
        ("field-a1e5",     "a" * 10 ** 5),
        ("field-a1e6",     "a" * 10 ** 6),
    ]
    # ghost collections: never created, nothing to clean up (fresh unique tails)
    GHOST_LEGS = [
        ("ghost-z1e4", PFX + "g" + "z" * (10 ** 4)),
        ("ghost-z1e5", PFX + "g" + "z" * (10 ** 5)),
    ]

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

        # ---- control gate: documented-zone leg must honor the 200 promise ----
        tag, val = LIVE_LEGS[0]
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": val},
                              query_params={"wait": "true"}, timeout=30)
        print(f"[gate {tag}] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            if s == 0 or 500 <= s <= 599:
                if not liveness(tag):
                    return "SCRIPT_ERROR"
            print(f"VERDICT: SCRIPT_ERROR - control leg {tag} got {s}; "
                  f"length legs are uninterpretable without a working "
                  f"documented-zone baseline")
            return "SCRIPT_ERROR"

        # ---- resource ladder on the live collection (field_name length) ----
        for tag, val in LIVE_LEGS[1:]:
            shown = f"len={len(val)}"
            s, raw = safe_request("DELETE", "delete_index",
                                  path_params={"name": C, "field_name": val},
                                  query_params={"wait": "true"}, timeout=60)
            if not adjudicate_resource_leg(tag, shown, s, raw,
                                           "promise-200", DEFECTS):
                return "SCRIPT_ERROR"

        # ---- same-family ladder on ghost collections (collection_name length) ----
        for tag, ghost in GHOST_LEGS:
            shown = f"len={len(ghost)}"
            s, raw = safe_request("DELETE", "delete_index",
                                  path_params={"name": ghost,
                                               "field_name": "f_short"},
                                  query_params={"wait": "true"}, timeout=60)
            if not adjudicate_resource_leg(tag, shown, s, raw,
                                           "promise-404", DEFECTS):
                return "SCRIPT_ERROR"

        # ---- Type4 leg: delete face must not create anything ----
        ps1, ok1 = describe_payload_schema("describe after legs", C)
        if ok1 and ps1:
            DEFECTS.append(
                f"(describe) payload_schema non-empty after only DELETE legs "
                f"with extreme-length path params: {str(ps1)[:200]} - phantom "
                f"schema state - Type4_StateLogicViolation "
                f"(qdrant_state_index_delete_001)")

        # ---- summary ----
        print(f"[summary] legs={1 + len(LIVE_LEGS) - 1 + len(GHOST_LEGS)} "
              f"(1 control + {len(LIVE_LEGS) - 1} live-length + "
              f"{len(GHOST_LEGS)} ghost-length); defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("resource-limit ladder on the delete face: grammar-legal "
              "extreme-length path params (field_name 1e4/1e5/1e6 on the live "
              "collection; collection_name 1e4/1e5 on never-created ghosts) "
              "all produced clean dispositions (200/404/4xx) with no 5xx, no "
              "hang and no phantom payload_schema state - NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup (own data only; ghost collections were never created;
        # failure must not flip the verdict)
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
