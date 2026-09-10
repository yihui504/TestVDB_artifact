#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_exists_001
# strategy: count_consistency
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: CRUD-then-EXISTS state tracking (Strategy 1 adapted: the count
  readout is replaced by the existence readout the assertion pins).
  collections+exists promises: HTTP 200 with result being an object of
  shape {exists: bool}; a MISSING collection yields result.exists=false
  with HTTP 200 (existence is never expressed as HTTP 404). The exists
  verdict must therefore track the actual collection state through the
  whole CRUD lifecycle, always over the same channel (200 + body).
  Legs (G4 positive/negative pairing on one unique name namespace):
  (A negative) exists on a never-created unique name -> exactly 200 +
      result.exists=false. A 404/other non-200 violates the pinned
      channel; result.exists=true is an existence lie.
  (B setup) create the collection -> 200 (setup gate).
  (C positive) exists on the live collection -> 200 + result.exists=true.
  (D point-CRUD invariance) upsert 2 points, delete 1 -> exists must
      stay 200+true (point-level CRUD must not flip collection-level
      existence — the readout is invariant under non-lifecycle writes).
  (E post-delete) drop the collection -> exists -> 200 +
      result.exists=false (again never 404).
  (F recreate) recreate the same name -> exists flips back to true.
  Every exists response is also shape-checked per the materialized
  response_shape (result: object, result.exists: boolean;
  description_conflict=false, so the object shape wins over any prose
  paraphrase like "{result: bool}").
  [chunk_collections+exists coverage: count_consistency x
   qdrant_behavioral_collections_exists_001 (never-created / live /
   point-CRUD invariance / post-delete / recreate + response shape)]
Oracle: never-created -> 200 + result.exists=false; live -> 200 +
  result.exists=true (invariant under point CRUD); after confirmed
  delete -> 200 + result.exists=false; after recreate -> 200 +
  result.exists=true. Any non-200 on exists (404 in particular),
  any wrong verdict, or any non-{result:{exists:bool}} 200 body =
  Type4_StateLogicViolation; 5xx = Type3_RuntimeFailure only after
  /healthz confirms liveness.
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

# exists endpoint is not in the runtime PATHS whitelist (verified:
# create/describe/drop/list/search/... are present, exists is not) —
# register it VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "collections+exists", "method": "GET",
#    "url": "/collections/{collection_name}/exists"}
rt.PATHS["collection_exists"] = "/collections/{collection_name}/exists"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'exists' in k or k in ('create_collection', 'drop_collection')]}")
if "/collections/{collection_name}/exists" not in rt.PATHS.values():
    print("VERDICT: SCRIPT_ERROR - exists URL registration failed")
    sys.exit(2)


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_exists(raw):
    """Shape-checked exists readout per materialized response_shape
    (result: object, result.exists: boolean). Returns
    (shape_ok, exists_value_or_None, anomaly_note)."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return False, None, "non-JSON body"
    res = b.get("result") if isinstance(b, dict) else None
    if isinstance(res, bool):
        # prose paraphrase said "{result: bool}"; the OpenAPI-derived
        # materialized field (result.exists, description_conflict=false)
        # wins per D3b — a bare bool here is a response-shape violation.
        return False, res, "result is a bare bool (spec pins result.exists object shape)"
    if not isinstance(res, dict):
        return False, None, "result missing or not an object"
    ev = res.get("exists")
    if not isinstance(ev, bool):
        return False, None, "result.exists missing or not a boolean"
    return True, ev, ""


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sce1_" + TS + "_"
    C = PFX + "col"
    NEVER = PFX + "never_created"
    DEFECTS = []

    def liveness(tag):
        print(f"[liveness {tag}] healthz probe required")
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    def probe_exists(tag, name, expect):
        """One exists probe judged against the pinned channel + verdict.
        Returns True if fine / defect recorded, None when the run must
        abort (transport or 5xx with a dead service)."""
        s, raw = safe_request("GET", "collection_exists",
                              path_params={"collection_name": name})
        print(f"[{tag}] status={s} raw={str(raw)[:200]}")
        if s == 0:
            # transport failure: liveness re-check before any conclusion (D3b r3);
            # env-class either way — not judged as a database defect (R12 convention)
            liveness(tag)
            return None
        if 500 <= s <= 599:
            if liveness(tag):
                DEFECTS.append(f"({tag}) exists returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
                return False
            return None
        shape_ok, ev, note = parse_exists(raw)
        if s != 200:
            chan = "never 404" if s == 404 else "HTTP 200 expected"
            DEFECTS.append(f"({tag}) exists returned {s} (assertion pins {chan}; "
                           f"existence belongs in the body) — Type4_StateLogicViolation "
                           f"— raw={str(raw)[:150]} "
                           f"(qdrant_behavioral_collections_exists_001)")
            return False
        if not shape_ok:
            DEFECTS.append(f"({tag}) exists returned 200 but body violates the pinned "
                           f"shape result.exists:boolean ({note}) — Type4_StateLogicViolation "
                           f"— raw={str(raw)[:150]}")
            return False
        if ev != expect:
            DEFECTS.append(f"({tag}) exists verdict is {ev} but the collection state "
                           f"demands {expect} — existence readout lies about state — "
                           f"Type4_StateLogicViolation "
                           f"(qdrant_behavioral_collections_exists_001)")
            return False
        print(f"[{tag}] OK: 200 + result.exists={ev}")
        return True

    try:
        # ---- (A negative) never-created name -> 200 + exists=false ----
        if probe_exists("A never-created", NEVER, False) is None:
            return "SCRIPT_ERROR"

        # ---- (B setup) create -> 200 ----
        b_s, b_raw = safe_request("PUT", "create_collection", path_params={"name": C},
                                  body={"vectors": {"size": 4, "distance": "Cosine"}})
        print(f"[B create] status={b_s} raw={b_raw[:200]}")
        if b_s == 0 or 500 <= b_s <= 599 or b_s not in (200, 201):
            liveness("B")
            print(f"SETUP_ERROR: create returned {b_s} — cannot judge exists contract")
            return "SCRIPT_ERROR"

        # ---- (C positive) live collection -> 200 + exists=true ----
        if probe_exists("C live", C, True) is None:
            return "SCRIPT_ERROR"

        # ---- (D point-CRUD invariance) ----
        pts = [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]},
               {"id": 2, "vector": [0.4, 0.3, 0.2, 0.1]}]
        d1_s, d1_raw = safe_request("PUT", "upsert_points",
                                    path_params={"name": C}, body={"points": pts})
        print(f"[D1 upsert 2] status={d1_s} raw={d1_raw[:150]}")
        if d1_s not in (200, 201):
            print(f"SETUP_ERROR: upsert returned {d1_s} — point-CRUD leg aborted")
            return "SCRIPT_ERROR"
        if probe_exists("D2 after-upsert", C, True) is None:
            return "SCRIPT_ERROR"
        d3_s, d3_raw = safe_request("POST", "delete_points",
                                    path_params={"name": C}, body={"points": [1]})
        print(f"[D3 delete 1 point] status={d3_s} raw={d3_raw[:150]}")
        if d3_s != 200:
            print(f"SETUP_ERROR: point delete returned {d3_s} — point-CRUD leg aborted")
            return "SCRIPT_ERROR"
        if probe_exists("D4 after-point-delete", C, True) is None:
            return "SCRIPT_ERROR"

        # ---- (E post-delete) drop -> exists -> 200 + exists=false ----
        e_s, e_raw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[E drop] status={e_s} raw={e_raw[:150]}")
        if e_s != 200:
            print(f"SETUP_ERROR: drop returned {e_s} — cannot judge post-delete exists")
            return "SCRIPT_ERROR"
        if probe_exists("E post-delete", C, False) is None:
            return "SCRIPT_ERROR"

        # ---- (F recreate) same name again -> exists flips back to true ----
        f_s, f_raw = safe_request("PUT", "create_collection", path_params={"name": C},
                                  body={"vectors": {"size": 4, "distance": "Cosine"}})
        print(f"[F recreate] status={f_s} raw={f_raw[:150]}")
        if f_s != 200:
            print(f"SETUP_ERROR: recreate returned {f_s} — cannot judge recreate exists")
            return "SCRIPT_ERROR"
        if probe_exists("F recreated", C, True) is None:
            return "SCRIPT_ERROR"

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
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
