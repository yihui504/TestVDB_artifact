#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_update_002
# strategy: upsert_idempotence
# endpoint: collections+update
# constraint_ids: qdrant_state_collections_update_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
"""
Attack: negative half of the update-time mutability promise — the
  vector-space-defining properties (size / distance) of an existing
  vector must NOT be changeable through PATCH collections+update
  (qdrant_state_collections_update_001; runtime PATHS
  update_collection + create_collection + describe_collection +
  upsert_points, verbatim raw_knowledge api_endpoints[].url).
  Mutation attempts carry the illegal property inside the
  VectorsConfigDiff accepted by the update endpoint; the correct
  server faces per the docs are a 4xx rejection OR a 200 with the
  diff silently not applied (200-without-echo). Either face must
  leave the vector-space state (describe config.params.vectors
  size/distance) untouched. Any leg where describe afterwards shows
  the requested size/distance actually APPLIED (2xx + echo of the
  new value) violates the immutability promise = defect. Legs:
  (A) unnamed vector, EMPTY collection: PATCH {"vectors":
      {"size": 16}} -> size must remain 4 (rejection or no-echo OK).
  (B) unnamed vector, data-bearing (3 wait=true points): PATCH
      {"vectors": {"distance": "Euclidean"}} -> distance must remain
      Cosine AND points_count must stay 3 (no data disturbance).
  (C) named vector "main", data-bearing: PATCH {"vectors":
      {"main": {"size": 32}}} -> size must remain 4.
  (D) named vector "main", EMPTY collection (the face where an
      implementation-side distance swap would be cheapest): PATCH
      {"vectors": {"main": {"distance": "Dot"}}} -> distance must
      remain Cosine; an applied change here is the strongest
      doc-contradiction signal (G9 face consistency: an empty
      collection is where any hidden capability would surface).
  Each leg repeats its mutation twice (idempotence probe: a second
  attempt must not drift the state either).
  [chunk_collections+update coverage: upsert_idempotence (repeated
   illegal-mutation no-apply) x qdrant_state_collections_update_001
   (negative: size/distance immutability across unnamed/named and
   empty/data faces)]
Oracle: 4xx rejection or 200-no-echo are the only legal faces — after
  each illegal PATCH pair on a live collection the
  describe readback keeps size==4 / distance==Cosine (and
  points_count==3 on data-bearing legs) — a readback showing the
  requested size/distance applied (e.g. size 16/32 or distance
  Euclidean/Dot) = Type1_IllegalSuccess (vector-space property
  altered through update, contradicting the docs); 5xx on any leg =
  Type3 only with /healthz liveness; 4xx rejections and 200-no-echo
  are both NO_DEFECT faces.
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


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def vector_state(raw):
    """(size, distance, points_count_or_None) from a describe raw text."""
    b = parse_json(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        return None, None, None
    cfg = res.get("config")
    if not isinstance(cfg, dict):
        return None, None, None
    par = cfg.get("params")
    vec = par.get("vectors") if isinstance(par, dict) else None
    pc = res.get("points_count")
    if not _is_int(pc):
        pc = None
    if isinstance(vec, dict):
        if "size" in vec and "distance" in vec:
            # unnamed single-vector collection
            return vec.get("size"), vec.get("distance"), pc
        # named-vector collection: at least one named entry exists
        for _name, vp in vec.items():
            if isinstance(vp, dict) and "size" in vp and "distance" in vp:
                return vp.get("size"), vp.get("distance"), pc
    return None, None, pc


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scup2_" + TS + "_"
    DEFECTS = []
    names = []
    # leg spec: (tag, named(bool), seed_points(int), vectors_body, patch_body,
    #            expect_size, expect_distance)
    LEGS = [
        ("A_unnamed_empty_size", False, 0,
         {"vectors": {"size": DIM, "distance": "Cosine"}},
         {"vectors": {"size": 16}}, DIM, "Cosine"),
        ("B_unnamed_data_dist", False, 3,
         {"vectors": {"size": DIM, "distance": "Cosine"}},
         {"vectors": {"distance": "Euclidean"}}, DIM, "Cosine"),
        ("C_named_data_size", True, 3,
         {"vectors": {"main": {"size": DIM, "distance": "Cosine"}}},
         {"vectors": {"main": {"size": 32}}}, DIM, "Cosine"),
        ("D_named_empty_dist", True, 0,
         {"vectors": {"main": {"size": DIM, "distance": "Cosine"}}},
         {"vectors": {"main": {"distance": "Dot"}}}, DIM, "Cosine"),
    ]

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    try:
        for tag, named, seed_n, create_body, patch_body, esize, edist in LEGS:
            name = PFX + tag
            names.append(name)
            s, raw = safe_request("PUT", "create_collection", create_body,
                                  path_params={"name": name})
            print(f"[{tag} create] status={s} raw={str(raw)[:160]}")
            if s != 200:
                print(f"SETUP_FAIL: create {tag} {s} {str(raw)[:200]}")
                return "SCRIPT_ERROR"
            if seed_n:
                pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM}
                       for i in range(seed_n)]
                s, raw = safe_request("PUT", "upsert_points", {"points": pts},
                                      path_params={"name": name},
                                      query_params={"wait": "true"})
                print(f"[{tag} seed x{seed_n}] status={s} raw={str(raw)[:160]}")
                if s != 200:
                    print(f"SETUP_FAIL: seed {tag} {s} {str(raw)[:200]}")
                    return "SCRIPT_ERROR"

            # twice: repeat-attempt idempotence (state must not drift)
            for attempt in (1, 2):
                s, raw = safe_request("PATCH", "update_collection", patch_body,
                                      path_params={"name": name})
                print(f"[{tag} attempt{attempt}] status={s} raw={str(raw)[:200]}")
                if s == 0:
                    if not alive():
                        return "SCRIPT_ERROR"
                    DEFECTS.append(f"{tag} attempt{attempt} transport failure "
                                   f"with /healthz alive — "
                                   f"Type3_RuntimeFailure")
                    continue
                if 500 <= s <= 599:
                    if not alive():
                        return "SCRIPT_ERROR"
                    DEFECTS.append(f"{tag} attempt{attempt} returned {s} with "
                                   f"service alive — Type3_RuntimeFailure — "
                                   f"raw={str(raw)[:150]}")
                    continue
                if s not in (200, 400, 422):
                    # e.g. 404 on our own created name would be a state anomaly
                    DEFECTS.append(f"{tag} attempt{attempt} returned {s} on an "
                                   f"existing collection (expected 200 or "
                                   f"400/422) — Type4_StateLogicViolation — "
                                   f"raw={str(raw)[:150]}")
                s2, raw2 = safe_request("GET", "describe_collection",
                                        path_params={"name": name})
                print(f"[{tag} describe#a{attempt}] status={s2} "
                      f"raw={str(raw2)[:240]}")
                if s2 == 0:
                    alive()
                    return "SCRIPT_ERROR"
                if 500 <= s2 <= 599:
                    if alive():
                        DEFECTS.append(f"{tag} describe returned {s2} with "
                                       f"service alive — Type3_RuntimeFailure — "
                                       f"raw={str(raw2)[:150]}")
                    else:
                        return "SCRIPT_ERROR"
                    continue
                if s2 != 200:
                    DEFECTS.append(f"{tag} describe returned {s2} on the "
                                   f"existing collection — "
                                   f"Type4_StateLogicViolation — "
                                   f"raw={str(raw2)[:150]}")
                    continue
                sz, dist, pc = vector_state(raw2)
                if sz != esize:
                    DEFECTS.append(f"{tag} attempt{attempt}: PATCH requested "
                                   f"size change but describe reports size="
                                   f"{sz!r} (wanted immutable {esize}) — "
                                   f"vector-space property ALTERED through "
                                   f"update — Type1_IllegalSuccess — "
                                   f"raw={str(raw2)[:200]}")
                if dist != edist:
                    DEFECTS.append(f"{tag} attempt{attempt}: PATCH requested "
                                   f"distance change but describe reports "
                                   f"distance={dist!r} (wanted immutable "
                                   f"{edist}) — vector-space property ALTERED "
                                   f"through update — Type1_IllegalSuccess — "
                                   f"raw={str(raw2)[:200]}")
                if seed_n and pc is not None and pc != seed_n:
                    DEFECTS.append(f"{tag} attempt{attempt}: after the illegal "
                                   f"PATCH points_count={pc} != seeded "
                                   f"{seed_n} — data disturbed — "
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
