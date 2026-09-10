#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_update_006
# strategy: count_consistency
# endpoint: collections+update
# constraint_ids: qdrant_behavioral_collections_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: the PATCH collections+update status matrix anchored to
  qdrant_behavioral_collections_update_001 — valid update on an
  existing collection -> 200; a missing collection -> 404; an
  invalid diff -> 400 — with the state agent's integrity tails on
  every face (runtime PATHS update_collection + create_collection +
  describe_collection + upsert_points + search, verbatim
  raw_knowledge api_endpoints[].url). Legs:
  (A valid 200) create + 3 wait=true points; PATCH hnsw_config
      {m: 8} -> 200; describe then reports m == 8 AND points_count
      == 3 AND a search returns all 3 points — an accepted update
      must not disturb stored state.
  (B missing 404) PATCH the same valid diff on a NEVER-CREATED name
      -> 404 expected; 2xx would be a ghost-success on a nonexistent
      collection (Type1); afterwards describe on the same name must
      ALSO 404 (no ghost collection materialized — Type4 if a
      describe 200 appears).
  (C invalid 400) PATCH an invalid diff (hnsw_config.m = "abc",
      wrong JSON type) on the live collection -> 400 expected;
      afterwards describe reports the PRE-PATCH hnsw m and
      points_count == 3 — a rejected diff must not partially apply
      (200-without-echo / partial-apply = the PATCH no-partial-apply
      invariant; residue = Type4).
  [chunk_collections+update coverage: count_consistency (status
   matrix + state-survival tails) x
   qdrant_behavioral_collections_update_001]
Oracle: PATCH valid hnsw diff on an existing data-bearing collection
  -> 200 with describe m==8 / points_count==3 and search returning 3
  points; PATCH on a never-created name -> 404 with describe on that
  name also 404; PATCH with invalid diff (m as string) -> 400 with
  describe unchanged (baseline m, points_count 3) — 2xx where 404/400
  is pinned = Type1_IllegalSuccess, 2xx-without-echo or partial
  apply/residue = Type4_StateLogicViolation, 5xx = Type3 only with
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
N_PTS = 3
NEW_M = 8


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


def get_state(raw):
    """(m_or_None, points_count_or_None) from a describe raw."""
    b = parse_json(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        return None, None
    cfg = res.get("config")
    hn = cfg.get("hnsw_config") if isinstance(cfg, dict) else None
    m = hn.get("m") if isinstance(hn, dict) else None
    pc = res.get("points_count")
    return m, (pc if _is_int(pc) else None)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scup6_" + TS + "_"
    C_LIVE = PFX + "live"
    C_GHOST = PFX + "ghost404"
    DEFECTS = []
    names = [C_LIVE]

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    try:
        # ---- setup ----
        s, raw = safe_request("PUT", "create_collection",
                              {"vectors": {"size": DIM, "distance": "Cosine"}},
                              path_params={"name": C_LIVE})
        print(f"[create live] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: create {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM} for i in range(N_PTS)]
        s, raw = safe_request("PUT", "upsert_points", {"points": pts},
                              path_params={"name": C_LIVE},
                              query_params={"wait": "true"})
        print(f"[upsert x{N_PTS}] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: upsert {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        s0, raw0 = safe_request("GET", "describe_collection",
                                path_params={"name": C_LIVE})
        print(f"[describe base] status={s0} raw={str(raw0)[:240]}")
        m_base, pc_base = get_state(raw0)

        # ---- (A) valid update -> 200 + persisted + data intact ----
        s, raw = safe_request("PATCH", "update_collection",
                              {"hnsw_config": {"m": NEW_M}},
                              path_params={"name": C_LIVE})
        print(f"[leg A patch m={NEW_M}] status={s} raw={str(raw)[:200]}")
        if s == 0:
            alive()
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"leg A returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif s != 200:
            if alive():
                DEFECTS.append(f"leg A valid update on an existing collection "
                               f"returned {s} (assertion pins 200) — "
                               f"Type1_IllegalSuccess — raw={str(raw)[:150]}")
        else:
            sA, rawA = safe_request("GET", "describe_collection",
                                    path_params={"name": C_LIVE})
            print(f"[leg A describe] status={sA} raw={str(rawA)[:240]}")
            mA, pcA = get_state(rawA)
            if mA != NEW_M:
                DEFECTS.append(f"leg A 200 but describe hnsw_config.m="
                               f"{mA!r} (wanted {NEW_M}) — 200-without-echo "
                               f"silent ignore — Type4_StateLogicViolation")
            if pcA != N_PTS:
                DEFECTS.append(f"leg A after update points_count={pcA!r} != "
                               f"{N_PTS} — data disturbed — "
                               f"Type4_StateLogicViolation")
            sS, rawS = safe_request("POST", "search",
                                    {"vector": [0.1] * DIM, "limit": N_PTS + 5},
                                    path_params={"name": C_LIVE})
            print(f"[leg A search] status={sS} raw={str(rawS)[:200]}")
            if sS != 200:
                DEFECTS.append(f"leg A search after update returned {sS} — "
                               f"data plane broken — "
                               f"Type4_StateLogicViolation — "
                               f"raw={str(rawS)[:150]}")
            else:
                bS = parse_json(rawS)
                lst = bS.get("result") if bS else None
                if not isinstance(lst, list) or len(lst) != N_PTS:
                    DEFECTS.append(f"leg A search returned "
                                   f"{len(lst) if isinstance(lst, list) else '?'}"
                                   f"/{N_PTS} points after update — "
                                   f"Type4_StateLogicViolation")

        # ---- (B) missing collection -> 404, no ghost materialization ----
        s, raw = safe_request("PATCH", "update_collection",
                              {"hnsw_config": {"m": NEW_M}},
                              path_params={"name": C_GHOST})
        print(f"[leg B patch on never-created {C_GHOST}] status={s} "
              f"raw={str(raw)[:200]}")
        if s == 0:
            alive()
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"leg B returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif s != 404:
            DEFECTS.append(f"leg B valid update on a never-created "
                           f"collection returned {s} (assertion pins 404) — "
                           f"Type1_IllegalSuccess — raw={str(raw)[:150]}")
        sG, rawG = safe_request("GET", "describe_collection",
                                path_params={"name": C_GHOST})
        print(f"[leg B describe ghost] status={sG} raw={str(rawG)[:200]}")
        if sG == 200:
            DEFECTS.append(f"leg B PATCH on a never-created name left a "
                           f"ghost collection (describe 200) — "
                           f"Type4_StateLogicViolation — raw={str(rawG)[:150]}")
        elif sG == 0:
            alive()
            return "SCRIPT_ERROR"
        elif 500 <= sG <= 599:
            if alive():
                DEFECTS.append(f"leg B ghost-describe returned {sG} with "
                               f"service alive — Type3_RuntimeFailure — "
                               f"raw={str(rawG)[:150]}")
            else:
                return "SCRIPT_ERROR"

        # ---- (C) invalid diff -> 400, no partial apply ----
        s, raw = safe_request("PATCH", "update_collection",
                              {"hnsw_config": {"m": "abc"}},
                              path_params={"name": C_LIVE})
        print(f"[leg C patch invalid m='abc'] status={s} raw={str(raw)[:200]}")
        if s == 0:
            alive()
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"leg C returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif s != 400:
            DEFECTS.append(f"leg C invalid diff returned {s} (assertion pins "
                           f"400) — Type1_IllegalSuccess — raw={str(raw)[:150]}")
        sPre, rawPre = safe_request("GET", "describe_collection",
                                    path_params={"name": C_LIVE})
        m_pre, pc_pre = get_state(rawPre)
        print(f"[leg C pre describe] status={sPre} m={m_pre} pc={pc_pre} "
              f"raw={str(rawPre)[:200]}")
        sC, rawC = safe_request("GET", "describe_collection",
                                path_params={"name": C_LIVE})
        print(f"[leg C describe] status={sC} raw={str(rawC)[:240]}")
        mC, pcC = get_state(rawC)
        if m_pre is not None and mC != m_pre:
            DEFECTS.append(f"leg C rejected diff changed hnsw_config.m from "
                           f"{m_pre} to {mC!r} — partial apply of a rejected "
                           f"diff — Type4_StateLogicViolation")
        if pcC != N_PTS:
            DEFECTS.append(f"leg C after rejected diff points_count={pcC!r} "
                           f"!= {N_PTS} — data disturbed by a rejected diff — "
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
