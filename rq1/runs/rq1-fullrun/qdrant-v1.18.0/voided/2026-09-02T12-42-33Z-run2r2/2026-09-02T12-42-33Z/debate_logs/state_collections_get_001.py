#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_get_001
# strategy: count_consistency
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 (CRUD-then-COUNT) executed through the DESCRIBE face
  (collections+get; runtime PATHS describe_collection =
   /collections/{name}, verbatim raw_knowledge api_endpoints[].url).
  The assertion pins the 200 face of an existing collection: full
  config (params, hnsw_config, optimizer_config, wal_config,
  quantization_config), status (green|yellow|red), points_count,
  indexed_vectors_count -- resolved config INCLUDING defaults.
  (A positive shape) create with a minimal config -> describe must be
      200 with the resolved full config: typed per the materialized
      response_shape (result.status string, result.segments_count
      integer, result.config.params/hnsw_config/optimizer_config
      objects, params.vectors echoing the created size/distance,
      wal_config resolved as an object per the assertion's full-config
      list). grey is accepted for result.status because
      qdrant_bc_create_visibility_001 documents yellow/grey during
      indexing.
  (B count consistency) upsert 7 distinct points with wait=true ->
      describe points_count == 7; 3 more distinct -> == 10. The
      describe readout must track stored state.
  points_count / indexed_vectors_count are integer|null in the shape:
  a null is logged as an observation (shape-legal), an int mismatch is
  a Type4 defect.
  [chunk_collections+get coverage: count_consistency x
   qdrant_behavioral_collections_get_001 (resolved full-config shape +
   points_count tracking through the describe face)]
Oracle: describe on the created collection returns exactly 200 whose
  result carries config.params / config.hnsw_config /
  config.optimizer_config as objects with params.vectors.size == 4,
  params.vectors.distance == Cosine, result.status in
  {green,yellow,red,grey}, result.segments_count integer and
  config.wal_config resolved as an object; after wait=true upserts of N
  distinct points result.points_count is an integer equal to N
  (integer mismatch = Type4_StateLogicViolation; null = logged
  observation, not judged; non-200 on the existing collection with
  /healthz alive = Type4; 5xx = Type3 only with /healthz liveness).
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
N1 = 7
N2 = 3
STATUS_OK = ("green", "yellow", "red", "grey")  # grey per qdrant_bc_create_visibility_001


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


def get_points_count(raw):
    b = parse_json(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        return None
    pc = res.get("points_count")
    return pc if _is_int(pc) else None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scg1_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    def alive():
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    def describe():
        try:
            return safe_request("GET", "describe_collection", path_params={"name": C})
        except Exception as e:
            return -1, str(e)

    try:
        # ---- setup: create with a MINIMAL config (only vectors) ----
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_FAIL: create {err}")
            return "SCRIPT_ERROR"

        # ---- (A) positive shape oracle: resolved full config ----
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
            b = parse_json(raw)
            res = b.get("result") if b else None
            problems = []
            if not isinstance(res, dict):
                problems.append("result missing or not an object")
            else:
                st = res.get("status")
                if not isinstance(st, str) or st not in STATUS_OK:
                    problems.append(f"result.status={st!r} not a green|yellow|red"
                                    f" string (grey allowed while indexing)")
                seg = res.get("segments_count")
                if not _is_int(seg):
                    problems.append(f"result.segments_count={seg!r} not an integer")
                pc = res.get("points_count")
                if pc is not None and not _is_int(pc):
                    problems.append(f"result.points_count={pc!r} not integer|null")
                elif _is_int(pc) and pc != 0:
                    problems.append(f"freshly created collection reports "
                                    f"points_count={pc} (expected 0)")
                ivc = res.get("indexed_vectors_count")
                if ivc is not None and not _is_int(ivc):
                    problems.append(f"result.indexed_vectors_count={ivc!r} "
                                    f"not integer|null")
                cfg = res.get("config")
                if not isinstance(cfg, dict):
                    problems.append("result.config missing or not an object")
                else:
                    for sub in ("params", "hnsw_config", "optimizer_config"):
                        if not isinstance(cfg.get(sub), dict):
                            problems.append(f"config.{sub} missing or not an "
                                            f"object (unresolved default)")
                    if not isinstance(cfg.get("wal_config"), dict):
                        problems.append("config.wal_config not resolved as an "
                                        "object (assertion full-config list)")
                    par = cfg.get("params")
                    if isinstance(par, dict):
                        vec = par.get("vectors")
                        if not isinstance(vec, dict):
                            problems.append("config.params.vectors not an object")
                        else:
                            if vec.get("size") != DIM:
                                problems.append(f"params.vectors.size="
                                                f"{vec.get('size')!r} != created {DIM}")
                            if vec.get("distance") != "Cosine":
                                problems.append(f"params.vectors.distance="
                                                f"{vec.get('distance')!r} != created Cosine")
                        if not _is_int(par.get("shard_number")):
                            problems.append("params.shard_number not resolved "
                                            "as an integer")
                    hn = cfg.get("hnsw_config")
                    if isinstance(hn, dict):
                        for k in ("m", "ef_construct", "full_scan_threshold"):
                            if not _is_int(hn.get(k)):
                                problems.append(f"hnsw_config.{k} not resolved "
                                                f"as an integer")
                    op = cfg.get("optimizer_config")
                    if isinstance(op, dict):
                        for k in ("deleted_threshold", "default_segment_number",
                                  "flush_interval_sec"):
                            if not _is_num(op.get(k)):
                                problems.append(f"optimizer_config.{k} not "
                                                f"resolved as a number")
            if problems:
                DEFECTS.append("200 describe body violates the pinned full-config "
                               f"shape: {'; '.join(problems)} — "
                               f"Type4_StateLogicViolation — raw={str(raw)[:200]} "
                               f"(qdrant_behavioral_collections_get_001)")

        # ---- (B) count consistency through the describe readout ----
        def count_leg(tag, expected):
            s2, raw2 = describe()
            print(f"[describe#{tag}] status={s2} raw={str(raw2)[:240]}")
            if s2 == 0:
                alive()
                return "ERR"
            if 500 <= s2 <= 599:
                if alive():
                    DEFECTS.append(f"describe#{tag} returned {s2} with service "
                                   f"alive — Type3_RuntimeFailure — "
                                   f"raw={str(raw2)[:150]}")
                    return "OK"
                return "ERR"
            if s2 != 200:
                if alive():
                    DEFECTS.append(f"describe#{tag} returned {s2} on an existing "
                                   f"collection (pinned 200 full config) — "
                                   f"Type4_StateLogicViolation — "
                                   f"raw={str(raw2)[:150]}")
                else:
                    return "ERR"
                return "OK"
            pc = get_points_count(raw2)
            if pc is None:
                print(f"OBSERVATION: describe#{tag} points_count is null/non-int "
                      f"(shape permits null) raw={str(raw2)[:200]}")
                return "OK"
            if pc != expected:
                DEFECTS.append(f"describe#{tag} points_count={pc} but {expected} "
                               f"points were upserted with wait=true — readout "
                               f"disagrees with stored state — "
                               f"Type4_StateLogicViolation "
                               f"(qdrant_behavioral_collections_get_001)")
            return "OK"

        pts1 = [{"id": i, "vector": [0.05 * (i + 1)] * DIM} for i in range(N1)]
        s, raw = safe_request("PUT", "upsert_points", {"points": pts1},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[upsert#1 x{N1}] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print(f"SETUP_FAIL: upsert#1 {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        if count_leg("B1", N1) == "ERR":
            return "SCRIPT_ERROR"

        pts2 = [{"id": N1 + i, "vector": [0.02 * (i + 2)] * DIM} for i in range(N2)]
        s, raw = safe_request("PUT", "upsert_points", {"points": pts2},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[upsert#2 x{N2}] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print(f"SETUP_FAIL: upsert#2 {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        if count_leg("B2", N1 + N2) == "ERR":
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
