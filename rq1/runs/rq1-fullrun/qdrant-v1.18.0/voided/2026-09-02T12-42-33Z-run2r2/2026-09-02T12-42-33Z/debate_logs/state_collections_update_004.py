#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_update_004
# strategy: count_consistency
# endpoint: collections+update
# constraint_ids: qdrant_range_collections_update_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: boundary closure + rejection of the update-time
  OptimizersConfigDiff bounds on PATCH collections+update (runtime
  PATHS update_collection + create_collection + describe_collection,
  verbatim raw_knowledge api_endpoints[].url).
  qdrant_range_collections_update_002 pins: deleted_threshold within
  [0, 1]; vacuum_min_vector_number >= 100; max_segment_size >= 1
  (KB); memmap_threshold >= 0; indexing_threshold >= 0 (KB).
  G4 closure: the inclusive bounds themselves must be accepted AND
  persisted (describe optimizer_config echo — create_010 measured
  the same echo face on collections+create for the create-time
  schema; this script runs the update-time diff schema). Legs (each
  on a fresh empty collection so no leg's residue contaminates
  another):
  (A1) minima closure: PATCH optimizers_config {vacuum_min_vector_
       number: 100, max_segment_size: 1, memmap_threshold: 0,
       indexing_threshold: 0} -> 200; describe echo == each value.
  (A2) deleted_threshold lower bound: 0.0 -> 200, echo 0.0.
  (A3) deleted_threshold upper bound: 1.0 -> 200, echo 1.0.
  (B1..B5) out-of-bound negatives, one per value: deleted_threshold
       -0.01 / 1.01, vacuum_min_vector_number: 99, max_segment_size:
       0, memmap_threshold: -1, indexing_threshold: -1 -> 400/422
       expected AND describe readback unchanged (no ghost residue).
       A 2xx on any = Type1_IllegalSuccess (out-of-bound diff
       accepted; an echo of the illegal value = applied); a rejection
       that leaves changed state = Type4_StateLogicViolation.
  [chunk_collections+update coverage: count_consistency (boundary
   closure readback) x qdrant_range_collections_update_002]
Oracle: PATCH with the inclusive OptimizersConfigDiff bounds returns HTTP 200 with echo,
  (deleted_threshold 0.0 and 1.0, vacuum_min_vector_number 100,
  max_segment_size 1, memmap_threshold 0, indexing_threshold 0) ->
  200 with describe optimizer_config echoing each requested value
  (float compare 1e-9); each out-of-bound PATCH (deleted_threshold
  -0.01/1.01, vacuum_min_vector_number 99, max_segment_size 0,
  memmap_threshold -1, indexing_threshold -1) -> 400/422 with the
  readback unchanged — 2xx = Type1_IllegalSuccess,
  200-without-echo on a closure value or changed state after a
  rejection = Type4_StateLogicViolation; 5xx = Type3 only with
  /healthz liveness.
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

DIM = 4


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def get_opt(raw):
    b = parse_json(raw)
    res = b.get("result") if isinstance(b, dict) else None
    cfg = res.get("config") if isinstance(res, dict) else None
    op = cfg.get("optimizer_config") if isinstance(cfg, dict) else None
    return op if isinstance(op, dict) else None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scup4_" + TS + "_"
    DEFECTS = []
    names = []

    CLOSURE_LEGS = [
        ("A1_minima",
         {"vacuum_min_vector_number": 100, "max_segment_size": 1,
          "memmap_threshold": 0, "indexing_threshold": 0}),
        ("A2_dt_lo", {"deleted_threshold": 0.0}),
        ("A3_dt_hi", {"deleted_threshold": 1.0}),
    ]
    NEG_LEGS = [
        ("B1_dt_under", {"deleted_threshold": -0.01}),
        ("B2_dt_over", {"deleted_threshold": 1.01}),
        ("B3_vac_99", {"vacuum_min_vector_number": 99}),
        ("B4_mss_0", {"max_segment_size": 0}),
        ("B5_mmt_neg", {"memmap_threshold": -1}),
        ("B6_it_neg", {"indexing_threshold": -1}),
    ]
    FLOAT_KEYS = {"deleted_threshold"}

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def describe_opt(tag, name):
        s, raw = safe_request("GET", "describe_collection",
                              path_params={"name": name})
        print(f"[describe {tag}] status={s} raw={str(raw)[:240]}")
        if s == 0:
            if not alive():
                return None, "TRANSPORT"
            DEFECTS.append(f"describe({tag}) transport failure with /healthz "
                           f"alive — Type3_RuntimeFailure")
            return None, "ERR"
        if 500 <= s <= 599:
            if not alive():
                return None, "TRANSPORT"
            DEFECTS.append(f"describe({tag}) returned {s} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            return None, "ERR"
        if s != 200:
            DEFECTS.append(f"describe({tag}) on the existing collection "
                           f"returned {s} — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")
            return None, "ERR"
        return get_opt(raw), "OK"

    def eq_val(k, got, want):
        if k in FLOAT_KEYS:
            try:
                return abs(float(got) - float(want)) <= 1e-9
            except (TypeError, ValueError):
                return False
        return got == want

    try:
        for tag, want in CLOSURE_LEGS:
            name = PFX + tag
            names.append(name)
            s, raw = safe_request("PUT", "create_collection",
                                  {"vectors": {"size": DIM, "distance": "Cosine"}},
                                  path_params={"name": name})
            print(f"[{tag} create] status={s} raw={str(raw)[:160]}")
            if s != 200:
                print(f"SETUP_FAIL: create {tag} {s} {str(raw)[:200]}")
                return "SCRIPT_ERROR"
            op0, st0 = describe_opt(tag + "_base", name)
            if st0 == "TRANSPORT":
                return "SCRIPT_ERROR"
            s, raw = safe_request("PATCH", "update_collection",
                                  {"optimizers_config": dict(want)},
                                  path_params={"name": name})
            print(f"[{tag} patch {json.dumps(want)}] status={s} "
                  f"raw={str(raw)[:200]}")
            if s == 0:
                if not alive():
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"{tag} transport failure with /healthz alive — "
                               f"Type3_RuntimeFailure")
                continue
            if 500 <= s <= 599:
                if not alive():
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"{tag} returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
                continue
            if s != 200:
                DEFECTS.append(f"{tag} in-bound optimizers diff "
                               f"{json.dumps(want)} rejected with {s} — "
                               f"boundary closure violated — "
                               f"Type1_IllegalSuccess — raw={str(raw)[:150]}")
                continue
            op1, st1 = describe_opt(tag + "_post", name)
            if st1 == "TRANSPORT":
                return "SCRIPT_ERROR"
            if op1 is not None:
                for k, wv in want.items():
                    got = op1.get(k)
                    if got is None:
                        DEFECTS.append(f"{tag} 200 but describe dropped "
                                       f"optimizer_config.{k} — "
                                       f"Type4_StateLogicViolation")
                    elif not eq_val(k, got, wv):
                        DEFECTS.append(f"{tag} 200 but describe "
                                       f"optimizer_config.{k}={got!r} "
                                       f"(wanted {wv}) — 200-without-echo "
                                       f"silent ignore — "
                                       f"Type4_StateLogicViolation")

        for tag, over in NEG_LEGS:
            name = PFX + tag
            names.append(name)
            s, raw = safe_request("PUT", "create_collection",
                                  {"vectors": {"size": DIM, "distance": "Cosine"}},
                                  path_params={"name": name})
            print(f"[{tag} create] status={s} raw={str(raw)[:160]}")
            if s != 200:
                print(f"SETUP_FAIL: create {tag} {s} {str(raw)[:200]}")
                return "SCRIPT_ERROR"
            op0, st0 = describe_opt(tag + "_base", name)
            if st0 == "TRANSPORT":
                return "SCRIPT_ERROR"
            s, raw = safe_request("PATCH", "update_collection",
                                  {"optimizers_config": dict(over)},
                                  path_params={"name": name})
            print(f"[{tag} patch {json.dumps(over)}] status={s} "
                  f"raw={str(raw)[:200]}")
            if s == 0:
                if not alive():
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"{tag} transport failure with /healthz alive — "
                               f"Type3_RuntimeFailure")
                continue
            if 500 <= s <= 599:
                if not alive():
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"{tag} returned {s} (400/422 expected) with "
                               f"service alive — Type3_RuntimeFailure — "
                               f"raw={str(raw)[:150]}")
                continue
            if 200 <= s < 300:
                detail = f"raw={str(raw)[:150]}"
                op1, st1 = describe_opt(tag + "_post", name)
                if st1 == "TRANSPORT":
                    return "SCRIPT_ERROR"
                if op1 is not None:
                    k = list(over)[0]
                    got = op1.get(k)
                    if got is not None and eq_val(k, got, over[k]):
                        detail = (f"AND describe echoes the illegal value "
                                  f"{k}={got!r} (applied out-of-bound config)")
                DEFECTS.append(f"{tag} out-of-bound optimizers diff "
                               f"{json.dumps(over)} ACCEPTED with {s} — "
                               f"Type1_IllegalSuccess — {detail}")
            elif s not in (400, 422):
                DEFECTS.append(f"{tag} rejection status {s} outside 400/422 — "
                               f"Type4_StateLogicViolation — "
                               f"raw={str(raw)[:150]}")
            else:
                op1, st1 = describe_opt(tag + "_post", name)
                if st1 == "TRANSPORT":
                    return "SCRIPT_ERROR"
                if op1 is not None and op0 is not None:
                    for k in op0:
                        if k in ("default_segment_number", "flush_interval_sec",
                                 "max_optimization_threads", "prevent_unoptimized"):
                            continue
                        if not eq_val(k, op1.get(k), op0[k]):
                            DEFECTS.append(f"{tag} rejected diff left state "
                                           f"change: optimizer_config.{k} "
                                           f"{op0[k]!r} -> {op1.get(k)!r} — "
                                           f"ghost residue — "
                                           f"Type4_StateLogicViolation")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for n in names:
            try:
                rt.drop_collection(n)
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
