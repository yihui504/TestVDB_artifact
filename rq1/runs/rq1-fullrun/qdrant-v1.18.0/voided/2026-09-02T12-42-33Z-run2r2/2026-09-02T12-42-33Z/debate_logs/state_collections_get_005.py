#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_get_005
# strategy: upsert_idempotence
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 3 (upsert idempotence) read out through the DESCRIBE
  face (collections+get; runtime PATHS describe_collection =
  /collections/{name} + upsert_points, verbatim raw_knowledge
  api_endpoints[].url). The assertion lists points_count among the
  fields the 200 describe face must report — so the describe readout
  must track the number of DISTINCT stored points:
  (A baseline) create -> describe points_count == 0.
  (B first write) upsert M=6 distinct ids with wait=true -> describe
      points_count == 6.
  (C duplicate replay) upsert the SAME 6 ids (same vectors) with
      wait=true -> describe points_count must STILL be 6. A 12 means
      either the upsert duplicated ids or the describe readout
      miscounts — either way the state-consistency readout is violated
      (Type4, judged on the describe face per this chunk).
  (D update-in-place) upsert the SAME ids with DIFFERENT vectors
      wait=true -> describe points_count must still be 6 (update by
      id, not insert).
  points_count is integer|null in the materialized response_shape: a
  null is logged as an observation (shape-legal), an int mismatch is
  a Type4 defect. Reuses the same setup as 001 but mutates with
  duplicate-id batches — a different destructive axis (G6: duplicate
  replay is the mutation that most easily turns a buggy counter into
  a doubled readout).
  [chunk_collections+get coverage: upsert_idempotence x
   qdrant_behavioral_collections_get_001 (points_count readout under
   duplicate-id replay and in-place update)]
Oracle: after each wait=true upsert stage, describe returns 200 with
  result.points_count an integer equal to the number of DISTINCT ids
  ever upserted (0 -> 6 -> 6 -> 6); an integer 12 at stage C/D =
  Type4_StateLogicViolation; null = logged observation, not judged;
  non-200 on the existing collection with /healthz alive = Type4;
  5xx = Type3 only with /healthz liveness.
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
M = 6


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


def get_points_count(raw):
    b = parse_json(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        return None
    pc = res.get("points_count")
    if isinstance(pc, int) and not isinstance(pc, bool):
        return pc
    return None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scg5_" + TS + "_"
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

    def upsert(pts):
        return safe_request("PUT", "upsert_points", {"points": pts},
                            path_params={"name": C},
                            query_params={"wait": "true"})

    def count_leg(tag, expected_distinct):
        s, raw = describe()
        print(f"[describe#{tag}] status={s} raw={str(raw)[:240]}")
        if s == 0:
            alive()
            return "ERR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"describe#{tag} returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "ERR"
            return "OK"
        if s != 200:
            if alive():
                DEFECTS.append(f"describe#{tag} returned {s} on an existing "
                               f"collection (pinned 200 full config) — "
                               f"Type4_StateLogicViolation — "
                               f"raw={str(raw)[:150]}")
            else:
                return "ERR"
            return "OK"
        pc = get_points_count(raw)
        if pc is None:
            print(f"OBSERVATION: describe#{tag} points_count is null/non-int "
                  f"(shape permits null) raw={str(raw)[:200]}")
            return "OK"
        if pc != expected_distinct:
            DEFECTS.append(f"describe#{tag} points_count={pc} but "
                           f"{expected_distinct} DISTINCT ids were upserted with "
                           f"wait=true — readout disagrees with stored state — "
                           f"Type4_StateLogicViolation "
                           f"(qdrant_behavioral_collections_get_001)")
        return "OK"

    try:
        # ---- (A) baseline ----
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_FAIL: create {err}")
            return "SCRIPT_ERROR"
        if count_leg("A-baseline", 0) == "ERR":
            return "SCRIPT_ERROR"

        # ---- (B) first write of M distinct ids ----
        ids = list(range(M))
        v1 = [[0.05 * (i + 1)] * DIM for i in ids]
        pts = [{"id": i, "vector": v1[i]} for i in ids]
        s, raw = upsert(pts)
        print(f"[upsert#B x{M}] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print(f"SETUP_FAIL: upsert#B {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        if count_leg("B-first-write", M) == "ERR":
            return "SCRIPT_ERROR"

        # ---- (C) duplicate replay of the SAME ids + vectors ----
        s, raw = upsert(pts)
        print(f"[upsert#C replay x{M}] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print(f"SETUP_FAIL: upsert#C {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        if count_leg("C-replay", M) == "ERR":
            return "SCRIPT_ERROR"

        # ---- (D) same ids, DIFFERENT vectors (update in place) ----
        pts2 = [{"id": i, "vector": [0.02 * (i + 2)] * DIM} for i in ids]
        s, raw = upsert(pts2)
        print(f"[upsert#D update-in-place x{M}] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print(f"SETUP_FAIL: upsert#D {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        if count_leg("D-update-in-place", M) == "ERR":
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
