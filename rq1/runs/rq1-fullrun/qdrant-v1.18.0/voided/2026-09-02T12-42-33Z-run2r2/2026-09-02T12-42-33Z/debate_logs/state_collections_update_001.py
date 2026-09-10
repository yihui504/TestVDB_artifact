#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_update_001
# strategy: count_consistency
# endpoint: collections+update
# constraint_ids: qdrant_state_collections_update_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
"""
Attack: positive half of the update-time mutability promise
  (PATCH collections+update; runtime PATHS update_collection +
  create_collection + describe_collection + upsert_points + search,
  verbatim raw_knowledge api_endpoints[].url). qdrant_state_
  collections_update_001 asserts: after creation, index /
  quantization / disk configuration CAN be changed through the
  update endpoint, while vector-space-defining properties (size /
  distance) cannot. This script probes the changeable side with the
  state-equality readback discipline (R16 lesson: accepted PATCH
  must be probed for persistence via describe readback — a
  200-without-echo = silent ignore defect family):
  (A index on a DATA-BEARING collection) create unnamed 4-dim
      Cosine, upsert 5 wait=true points, PATCH hnsw_config {m: 8}
      -> 200 AND describe config.hnsw_config.m == 8 AND
      points_count still == 5 (reconfiguration must not lose or
      reset data) AND a search returns the 5 points (data plane
      intact after the config mutation).
  (B optimizers on the same collection) PATCH optimizers_config
      {memmap_threshold: 512} -> 200 AND describe
      config.optimizer_config.memmap_threshold == 512 (config-level
      diff must persist, not be silently ignored).
  (C quantization on an empty collection) create a second empty
      collection, PATCH quantization_config {scalar: {type: int8}}
      (branch satisfies the endpoint's request_required_paths
      scalar.type) -> 200 AND describe config.quantization_config
      echoes scalar.type == int8 (empty collection -> nothing
      asynchronous can delay the echo).
  Expected server face per assertion: 200 + describe echo on every
  leg; non-200 on a live service = the changeable-promise broken
  (Type4 when state fails to reconcile: rejected legal change or
  accepted-but-not-persisted; Type3 only with /healthz liveness).
  [chunk_collections+update coverage: count_consistency x
   qdrant_state_collections_update_001 (positive: accepted PATCH
   persistence echo + data-plane survival across reconfiguration)]
Oracle: accepted PATCH legs return HTTP 200 (any 200-without-echo = defect):
  hnsw_config {m:8} and optimizers_config
  {memmap_threshold:512} on a data-bearing collection are 200 and
  describe afterwards echoes m==8 / memmap_threshold==512 with
  points_count==5 and search returning 5 points; PATCH
  quantization_config {scalar:{type:int8}} on an empty collection is
  200 and describe echoes quantization_config.scalar.type=="int8" —
  any non-200 with /healthz alive, or a 200 whose describe readback
  lacks the requested value (200-without-echo silent ignore), =
  Type4_StateLogicViolation; 5xx = Type3 only with /healthz liveness.
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
N_PTS = 5
NEW_M = 8
NEW_MMT = 512


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


def get_config(raw):
    b = parse_json(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if isinstance(res, dict) and isinstance(res.get("config"), dict):
        return res["config"]
    return None


def describe_ok(tag, name, DEFECTS):
    """GET describe on an existing collection. Returns config dict on the
    healthy 200 path (appending Type3/Type4 entries otherwise), None on
    transport-class failure (caller returns SCRIPT_ERROR)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    print(f"[describe {tag}] status={s} raw={str(raw)[:220]}")
    if s == 0:
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[{tag} transport] healthz status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            return None, "TRANSPORT"
        DEFECTS.append(f"describe({tag}) transport failure with /healthz alive — "
                       f"Type3_RuntimeFailure")
        return None, "ERR"
    if 500 <= s <= 599:
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[{tag} liveness] healthz status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            return None, "TRANSPORT"
        DEFECTS.append(f"describe({tag}) returned {s} with service alive — "
                       f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        return None, "ERR"
    if s != 200:
        DEFECTS.append(f"describe({tag}) on an existing collection returned {s} "
                       f"(pinned 200) — Type4_StateLogicViolation — "
                       f"raw={str(raw)[:150]}")
        return None, "ERR"
    cfg = get_config(raw)
    if cfg is None:
        DEFECTS.append(f"describe({tag}) 200 body lacks result.config object — "
                       f"Type4_StateLogicViolation — raw={str(raw)[:200]}")
        return None, "ERR"
    return cfg, "OK"


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scup1_" + TS + "_"
    C_DATA = PFX + "data"
    C_EMPTY = PFX + "empty"
    DEFECTS = []
    names = [C_DATA, C_EMPTY]

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    try:
        # ---- setup: data-bearing collection + 5 wait=true points ----
        s, raw = safe_request("PUT", "create_collection",
                              {"vectors": {"size": DIM, "distance": "Cosine"}},
                              path_params={"name": C_DATA})
        print(f"[create data] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: create data {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM} for i in range(N_PTS)]
        s, raw = safe_request("PUT", "upsert_points", {"points": pts},
                              path_params={"name": C_DATA},
                              query_params={"wait": "true"})
        print(f"[upsert x{N_PTS}] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: upsert {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"

        # ---- (A) index-side change on data-bearing collection ----
        s, raw = safe_request("PATCH", "update_collection",
                              {"hnsw_config": {"m": NEW_M}},
                              path_params={"name": C_DATA})
        print(f"[patch A hnsw m={NEW_M}] status={s} raw={str(raw)[:200]}")
        if s == 0:
            alive()
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"PATCH(A) returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif s != 200:
            if alive():
                DEFECTS.append(f"PATCH(A) hnsw m change on a data-bearing "
                               f"collection rejected with {s} (assertion: index "
                               f"config changeable post-create) — "
                               f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        else:
            cfg, st = describe_ok("A1", C_DATA, DEFECTS)
            if st == "TRANSPORT":
                return "SCRIPT_ERROR"
            if cfg is not None:
                hn = cfg.get("hnsw_config")
                m2 = hn.get("m") if isinstance(hn, dict) else None
                if m2 != NEW_M:
                    DEFECTS.append(f"PATCH(A) 200 but describe reports "
                                   f"hnsw_config.m={m2!r} (wanted {NEW_M}) — "
                                   f"200-without-echo silent ignore — "
                                   f"Type4_StateLogicViolation")
                pc = cfg.get("points_count")
                if _is_int(pc) and pc != N_PTS:
                    DEFECTS.append(f"after reconfiguration describe "
                                   f"points_count={pc} != upserted {N_PTS} — "
                                   f"data lost on config change — "
                                   f"Type4_StateLogicViolation")
            s2, raw2 = safe_request("POST", "search",
                                    {"vector": [0.1] * DIM, "limit": N_PTS + 5},
                                    path_params={"name": C_DATA})
            print(f"[search A2] status={s2} raw={str(raw2)[:200]}")
            if s2 == 0:
                alive()
                return "SCRIPT_ERROR"
            if 500 <= s2 <= 599:
                if alive():
                    DEFECTS.append(f"search after reconfig returned {s2} with "
                                   f"service alive — Type3_RuntimeFailure — "
                                   f"raw={str(raw2)[:150]}")
            elif s2 != 200:
                DEFECTS.append(f"search after reconfig returned {s2} on the "
                               f"existing collection — data plane broken after "
                               f"config change — Type4_StateLogicViolation — "
                               f"raw={str(raw2)[:150]}")
            else:
                b2 = parse_json(raw2)
                lst = b2.get("result") if b2 else None
                if not isinstance(lst, list):
                    DEFECTS.append(f"search 200 body lacks result list after "
                                   f"reconfig — Type4_StateLogicViolation — "
                                   f"raw={str(raw2)[:150]}")
                elif len(lst) != N_PTS:
                    DEFECTS.append(f"search after reconfig returned "
                                   f"{len(lst)}/{N_PTS} points — data plane "
                                   f"inconsistent after config change — "
                                   f"Type4_StateLogicViolation")

            # ---- (B) optimizers-side change on the same collection ----
            s, raw = safe_request("PATCH", "update_collection",
                                  {"optimizers_config": {"memmap_threshold":
                                                         NEW_MMT}},
                                  path_params={"name": C_DATA})
            print(f"[patch B memmap_threshold={NEW_MMT}] status={s} "
                  f"raw={str(raw)[:200]}")
            if s == 0:
                alive()
                return "SCRIPT_ERROR"
            if 500 <= s <= 599:
                if alive():
                    DEFECTS.append(f"PATCH(B) returned {s} with service alive — "
                                   f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
                else:
                    return "SCRIPT_ERROR"
            elif s != 200:
                if alive():
                    DEFECTS.append(f"PATCH(B) optimizers memmap_threshold "
                                   f"rejected with {s} (assertion: optimizer "
                                   f"config changeable post-create) — "
                                   f"Type4_StateLogicViolation — "
                                   f"raw={str(raw)[:150]}")
            else:
                cfg, st = describe_ok("B1", C_DATA, DEFECTS)
                if st == "TRANSPORT":
                    return "SCRIPT_ERROR"
                if cfg is not None:
                    op = cfg.get("optimizer_config")
                    mm = op.get("memmap_threshold") if isinstance(op, dict) else None
                    if mm != NEW_MMT:
                        DEFECTS.append(f"PATCH(B) 200 but describe reports "
                                       f"optimizer_config.memmap_threshold="
                                       f"{mm!r} (wanted {NEW_MMT}) — "
                                       f"200-without-echo silent ignore — "
                                       f"Type4_StateLogicViolation")

        # ---- (C) quantization side on an EMPTY collection ----
        s, raw = safe_request("PUT", "create_collection",
                              {"vectors": {"size": DIM, "distance": "Cosine"}},
                              path_params={"name": C_EMPTY})
        print(f"[create empty] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: create empty {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PATCH", "update_collection",
                              {"quantization_config": {"scalar": {"type": "int8"}}},
                              path_params={"name": C_EMPTY})
        print(f"[patch C quantization] status={s} raw={str(raw)[:200]}")
        if s == 0:
            alive()
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"PATCH(C) returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif s != 200:
            if alive():
                DEFECTS.append(f"PATCH(C) quantization_config scalar int8 "
                               f"rejected with {s} (assertion: quantization "
                               f"config changeable post-create) — "
                               f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        else:
            # empty collection: nothing asynchronous may delay the echo;
            # small poll for optimizer-side echo safety
            qc = None
            for _i in range(4):
                cfg, st = describe_ok("C1", C_EMPTY, DEFECTS)
                if st == "TRANSPORT":
                    return "SCRIPT_ERROR"
                if cfg is not None:
                    qc = cfg.get("quantization_config")
                    if isinstance(qc, dict) and isinstance(qc.get("scalar"), dict):
                        break
                time.sleep(1.0)
            sc = qc.get("scalar") if isinstance(qc, dict) else None
            st2 = sc.get("type") if isinstance(sc, dict) else None
            if st2 != "int8":
                DEFECTS.append(f"PATCH(C) 200 but describe "
                               f"quantization_config={json.dumps(qc)[:120]} "
                               f"(wanted scalar.type int8) — 200-without-echo "
                               f"silent ignore — Type4_StateLogicViolation")

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
