#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_get_006
# strategy: count_consistency
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: resolved-config fidelity of the DESCRIBE face
  (collections+get; runtime PATHS describe_collection +
  create_collection + update_collection, verbatim raw_knowledge
  api_endpoints[].url). The assertion pins the 200 face as the
  RESOLVED config "including defaults" — i.e. describe must report
  the collection's ACTUAL stored configuration:
  (A explicit-echo) create with EXPLICIT non-default values —
      vectors {size 4, distance Dot}, hnsw_config {m 32,
      ef_construct 200}, optimizer_config {indexing_threshold
      30000} — describe must echo those exact values. A describe that
      answers with the DEFAULTS (m 16 / ef_construct 100 /
      indexing_threshold 20000) for explicitly-set fields misreports
      stored state (Type4); an omitted/unresolved field is a
      full-config shape violation (Type4).
  (B resolved-defaults side) fields NOT set at create must come back
      as concrete resolved values, not omitted: hnsw_config.
      full_scan_threshold (integer), params.shard_number (integer),
      wal_config resolved as an object with wal_capacity_mb
      (integer), optimizer_config.flush_interval_sec (number).
  (C update reflection) PATCH collections+update with hnsw_config
      {m 24} (an index-side knob, changeable post-create per
      qdrant_state_collections_update_001) -> describe must now
      report m == 24. A stale 32 or a re-defaulted 16 means the
      describe readout does not track the persisted configuration
      (Type4). A 4xx on the PATCH itself is an ENV note (the judged
      face is describe), not a defect here.
  [chunk_collections+get coverage: count_consistency(config readout)
   x qdrant_behavioral_collections_get_001 (explicit-echo /
   resolved-defaults / post-update reflection)]
Oracle: describe after the explicit create is 200 with
  result.config.params.vectors.size == 4 and .distance == Dot,
  config.hnsw_config.m == 32, .ef_construct == 200,
  config.optimizer_config.indexing_threshold == 30000, and the unset
  fields resolved (full_scan_threshold int, shard_number int,
  wal_config object with wal_capacity_mb int, flush_interval_sec
  number); after a 200 PATCH {hnsw_config:{m:24}}, describe reports
  config.hnsw_config.m == 24 — any of m==16 / ef_construct==100 /
  indexing_threshold==20000 at stage A, a missing/unresolved field,
  or a stale m at stage C = Type4_StateLogicViolation; 5xx = Type3
  only with /healthz liveness.
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
EXPLICIT = {"m": 32, "ef_construct": 200, "indexing_threshold": 30000}
NEW_M = 24


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


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def get_config(raw):
    b = parse_json(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if isinstance(res, dict) and isinstance(res.get("config"), dict):
        return res["config"]
    return None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scg6_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    def alive():
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    def describe():
        try:
            return safe_request("GET", "describe_collection",
                                path_params={"name": C})
        except Exception as e:
            return -1, str(e)

    try:
        # ---- setup: create with EXPLICIT non-default config ----
        s, raw = safe_request("PUT", "create_collection", {
            "vectors": {"size": DIM, "distance": "Dot"},
            "hnsw_config": {"m": EXPLICIT["m"],
                            "ef_construct": EXPLICIT["ef_construct"]},
            "optimizer_config": {"indexing_threshold":
                                 EXPLICIT["indexing_threshold"]},
        }, path_params={"name": C})
        print(f"[create explicit] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: create {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"

        # ---- (A)+(B): describe must echo explicit values and resolve the rest ----
        s, raw = describe()
        print(f"[describe#A] status={s} raw={str(raw)[:400]}")
        if s == 0:
            alive()
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"describe on an existing collection returned {s} "
                               f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif s != 200:
            if alive():
                DEFECTS.append(f"describe on an existing collection returned {s} "
                               f"(assertion pins 200 with full config) — "
                               f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        else:
            cfg = get_config(raw)
            problems = []
            if cfg is None:
                problems.append("result.config missing or not an object")
            else:
                par = cfg.get("params")
                if not isinstance(par, dict):
                    problems.append("config.params missing or not an object")
                else:
                    vec = par.get("vectors")
                    if not isinstance(vec, dict):
                        problems.append("config.params.vectors not an object")
                    else:
                        if vec.get("size") != DIM:
                            problems.append(f"params.vectors.size={vec.get('size')!r}"
                                            f" != created {DIM}")
                        if vec.get("distance") != "Dot":
                            problems.append(f"params.vectors.distance="
                                            f"{vec.get('distance')!r} != created Dot")
                hn = cfg.get("hnsw_config")
                if not isinstance(hn, dict):
                    problems.append("config.hnsw_config missing or not an object")
                else:
                    if hn.get("m") != EXPLICIT["m"]:
                        problems.append(f"hnsw_config.m={hn.get('m')!r} != explicit "
                                        f"{EXPLICIT['m']} (re-defaulted or dropped)")
                    if hn.get("ef_construct") != EXPLICIT["ef_construct"]:
                        problems.append(f"hnsw_config.ef_construct="
                                        f"{hn.get('ef_construct')!r} != explicit "
                                        f"{EXPLICIT['ef_construct']}")
                    if not _is_int(hn.get("full_scan_threshold")):
                        problems.append("hnsw_config.full_scan_threshold not "
                                        "resolved as an integer")
                op = cfg.get("optimizer_config")
                if not isinstance(op, dict):
                    problems.append("config.optimizer_config missing or not an "
                                    "object")
                else:
                    if op.get("indexing_threshold") != EXPLICIT["indexing_threshold"]:
                        problems.append(f"optimizer_config.indexing_threshold="
                                        f"{op.get('indexing_threshold')!r} != "
                                        f"explicit {EXPLICIT['indexing_threshold']}")
                    if not _is_num(op.get("flush_interval_sec")):
                        problems.append("optimizer_config.flush_interval_sec "
                                        "not resolved as a number")
                wal = cfg.get("wal_config")
                if not isinstance(wal, dict) or not _is_int(wal.get("wal_capacity_mb")):
                    problems.append("config.wal_config not resolved as an object "
                                    "with integer wal_capacity_mb")
                if isinstance(par, dict) and not _is_int(par.get("shard_number")):
                    problems.append("params.shard_number not resolved as an "
                                    "integer")
            if problems:
                DEFECTS.append("200 describe body violates the resolved-config "
                               f"fidelity: {'; '.join(problems)} — "
                               f"Type4_StateLogicViolation — raw={str(raw)[:200]} "
                               f"(qdrant_behavioral_collections_get_001)")

        # ---- (C) update reflection: PATCH hnsw_config.m, describe must follow ----
        s, raw = safe_request("PATCH", "update_collection",
                              {"hnsw_config": {"m": NEW_M}},
                              path_params={"name": C})
        print(f"[patch m={NEW_M}] status={s} raw={str(raw)[:200]}")
        if s == 0:
            alive()
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"PATCH update returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif s != 200:
            print(f"ENV_ISSUE (not judged here; judged face is describe): PATCH "
                  f"update returned {s} — reflection leg skipped — "
                  f"raw={str(raw)[:200]}")
        else:
            s2, raw2 = describe()
            print(f"[describe#C] status={s2} raw={str(raw2)[:400]}")
            if s2 == 0:
                alive()
                return "SCRIPT_ERROR"
            if 500 <= s2 <= 599:
                if alive():
                    DEFECTS.append(f"describe#C returned {s2} with service alive — "
                                   f"Type3_RuntimeFailure — raw={str(raw2)[:150]}")
                else:
                    return "SCRIPT_ERROR"
            elif s2 != 200:
                if alive():
                    DEFECTS.append(f"describe#C returned {s2} on an existing "
                                   f"collection (pinned 200 full config) — "
                                   f"Type4_StateLogicViolation — "
                                   f"raw={str(raw2)[:150]}")
                else:
                    return "SCRIPT_ERROR"
            else:
                cfg2 = get_config(raw2)
                hn2 = cfg2.get("hnsw_config") if isinstance(cfg2, dict) else None
                m2 = hn2.get("m") if isinstance(hn2, dict) else None
                if m2 != NEW_M:
                    DEFECTS.append(f"after a 200-confirmed PATCH "
                                   f"hnsw_config.m={NEW_M}, describe reports "
                                   f"m={m2!r} (stale {EXPLICIT['m']} or "
                                   f"re-defaulted) — readout does not track the "
                                   f"persisted configuration — "
                                   f"Type4_StateLogicViolation — "
                                   f"raw={str(raw2)[:200]} "
                                   f"(qdrant_behavioral_collections_get_001)")

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
