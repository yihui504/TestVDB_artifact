#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_update_007
# strategy: concurrent
# endpoint: collections+update
# constraint_ids: qdrant_behavioral_collections_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 Concurrency Blindness
"""
Attack: concurrent PATCH collections+update churn against the data
  plane on ONE live collection — config-writer threads racing
  point-writer and reader threads (runtime PATHS update_collection +
  create_collection + describe_collection + upsert_points + search,
  verbatim raw_knowledge api_endpoints[].url). qdrant_behavioral_
  collections_update_001 pins the 200 face of a valid update on an
  existing collection; under concurrency the state agent checks the
  readout channel integrity (BS-03): while PATCHERS flip
  hnsw_config.m (8/24/48) and optimizers_config.memmap_threshold
  (256/512) and UPPERS insert unique wait=true points, READERS keep
  searching and describing. Invariants:
  (I1 Type3) no business call (PATCH / upsert / search / describe)
      returns 5xx or a transport failure while /healthz is alive —
      a config mutation racing point traffic must never crash the
      update path (a bare 409/503-class transient is recorded but
      only 5xx-with-liveness counts as Type3).
  (I2 Type4) after all threads join, describe points_count == the
      number of upserts that returned 200 (durable writes must all
      be readable: no lost/resurrected points across the churn).
  (I3 Type4) final describe config is coherent: hnsw_config.m is an
      integer from the churned set {8, 24, 48},
      optimizer_config.memmap_threshold from {256, 512} (last-writer
      wins must yield ONE of the written values, never a torn
      config), and a final search returns exactly the expected point
      count (data plane consistent after the races).
  [chunk_collections+update coverage: concurrent (update-channel
   integrity under config churn x point traffic) x
   qdrant_behavioral_collections_update_001]
Oracle: HTTP 200 face stability under churn — with /healthz alive, zero 5xx/transport failures across all
  PATCH/upsert/search/describe calls during the churn; after the
  join, describe points_count == #200-upserts (Type4 on mismatch),
  hnsw_config.m in {8,24,48} and memmap_threshold in {256,512} with
  a final search returning exactly the expected count — any 5xx with
  /healthz alive = Type3_RuntimeFailure; torn/absent config or count
  mismatch = Type4_StateLogicViolation.
"""

import os
import sys
import json
import time
import threading
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
N_BASE = 5
M_SET = (8, 24, 48)
MMT_SET = (256, 512)
N_THREADS = max(4, int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10")))
N_PATCHERS = 2
N_UPPERS = max(2, N_THREADS // 2)
N_READERS = max(1, N_THREADS - N_PATCHERS - N_UPPERS)
PATCH_ITERS = 10
UPPER_ITERS = 8
READER_ITERS = 40


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


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scup7_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    lock = threading.Lock()
    stop_evt = threading.Event()
    stats = {"patch_ok": 0, "upsert_ok": 0, "anomalies": []}
    next_id = [N_BASE]

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def record(op, s, raw, tag=""):
        if s == 200:
            return
        with lock:
            if s == 0:
                stats["anomalies"].append(f"{op}{tag} transport failure: "
                                          f"{str(raw)[:120]}")
            elif 500 <= s <= 599:
                stats["anomalies"].append(f"{op}{tag} returned {s}: "
                                          f"{str(raw)[:120]}")
            elif s not in (200, 201, 202, 204, 400, 404, 409, 422, 503):
                stats["anomalies"].append(f"{op}{tag} unexpected status "
                                          f"{s}: {str(raw)[:120]}")

    def patcher_thread(tid):
        """Config churn: flip hnsw m and memmap_threshold."""
        for i in range(PATCH_ITERS):
            if stop_evt.is_set():
                break
            m = M_SET[(tid + i) % len(M_SET)]
            mmt = MMT_SET[(tid + i) % len(MMT_SET)]
            body = ({"hnsw_config": {"m": m}}
                    if i % 2 == 0 else
                    {"optimizers_config": {"memmap_threshold": mmt}})
            s, raw = safe_request("PATCH", "update_collection", body,
                                  path_params={"name": C})
            if s == 200:
                with lock:
                    stats["patch_ok"] += 1
            else:
                record("patch", s, raw, f"(m={m} or mmt={mmt})")
            time.sleep(0.01)

    def upper_thread(tid):
        """Insert unique wait=true points."""
        for i in range(UPPER_ITERS):
            if stop_evt.is_set():
                break
            with lock:
                pid = next_id[0]
                next_id[0] += 1
            s, raw = safe_request("PUT", "upsert_points",
                                  {"points": [{"id": pid,
                                               "vector": [0.01 * pid] * DIM}]},
                                  path_params={"name": C},
                                  query_params={"wait": "true"})
            if s == 200:
                with lock:
                    stats["upsert_ok"] += 1
            else:
                record("upsert", s, raw, f"(id={pid})")
            time.sleep(0.005)

    def reader_thread(tid):
        """Search + describe while the churn runs."""
        for i in range(READER_ITERS):
            if stop_evt.is_set():
                break
            s, raw = safe_request("POST", "search",
                                  {"vector": [0.05] * DIM, "limit": 10},
                                  path_params={"name": C})
            if s != 200:
                record("search", s, raw)
            s2, raw2 = safe_request("GET", "describe_collection",
                                    path_params={"name": C})
            if s2 != 200:
                record("describe", s2, raw2)
            time.sleep(0.005)

    names = [C]
    try:
        s, raw = safe_request("PUT", "create_collection",
                              {"vectors": {"size": DIM, "distance": "Cosine"}},
                              path_params={"name": C})
        print(f"[create] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: create {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        base_pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM}
                    for i in range(N_BASE)]
        s, raw = safe_request("PUT", "upsert_points", {"points": base_pts},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[base upsert x{N_BASE}] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: base upsert {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"

        threads = []
        for t in range(N_PATCHERS):
            threads.append(threading.Thread(target=patcher_thread,
                                            args=(t,), daemon=True))
        for t in range(N_UPPERS):
            threads.append(threading.Thread(target=upper_thread,
                                            args=(t,), daemon=True))
        for t in range(N_READERS):
            threads.append(threading.Thread(target=reader_thread,
                                            args=(t,), daemon=True))
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=120)

        stop_evt.set()
        time.sleep(1.5)  # settle

        with lock:
            patched = stats["patch_ok"]
            upserted = stats["upsert_ok"]
            anomalies = list(stats["anomalies"])
        expected = N_BASE + upserted
        print(f"[stats] patch_ok={patched} upsert_ok={upserted} "
              f"expected_points={expected} anomalies={len(anomalies)}")

        # ---- I1: 5xx / transport anomalies with liveness ----
        if anomalies:
            hs, hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[anomaly liveness] healthz status={hs} "
                  f"raw={str(hraw)[:120]}")
            if hs == 200:
                for a in anomalies:
                    if "transport failure" in a or "returned 5" in a:
                        DEFECTS.append(f"Type3_RuntimeFailure — {a}")
                    else:
                        DEFECTS.append(f"OBSERVED anomaly (recorded, non-5xx): "
                                       f"{a}")
            else:
                print("ENV_ISSUE: anomalies present but /healthz NOT alive — "
                      "service-down branch, script error not a defect")

        # ---- I2/I3: final state coherence ----
        s, raw = safe_request("GET", "describe_collection",
                              path_params={"name": C})
        print(f"[final describe] status={s} raw={str(raw)[:260]}")
        if s != 200:
            if s == 0:
                alive()
                return "SCRIPT_ERROR"
            if 500 <= s <= 599 and not alive():
                return "SCRIPT_ERROR"
            DEFECTS.append(f"final describe returned {s} on the live "
                           f"collection — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")
        else:
            b = parse_json(raw)
            res = b.get("result") if isinstance(b, dict) else None
            cfg = res.get("config") if isinstance(res, dict) else None
            pc = res.get("points_count")
            pc = pc if _is_int(pc) else None
            hn = cfg.get("hnsw_config") if isinstance(cfg, dict) else None
            op = cfg.get("optimizer_config") if isinstance(cfg, dict) else None
            m = hn.get("m") if isinstance(hn, dict) else None
            mmt = op.get("memmap_threshold") if isinstance(op, dict) else None
            if pc != expected:
                DEFECTS.append(f"final describe points_count={pc!r} != "
                               f"{expected} ({N_BASE} base + {upserted} "
                               f"200-upserts) — lost/resurrected points "
                               f"across config churn — "
                               f"Type4_StateLogicViolation")
            if m not in M_SET:
                DEFECTS.append(f"final hnsw_config.m={m!r} not in churned "
                               f"set {M_SET} — torn config — "
                               f"Type4_StateLogicViolation")
            if mmt not in MMT_SET:
                DEFECTS.append(f"final optimizer_config.memmap_threshold="
                               f"{mmt!r} not in churned set {MMT_SET} — torn "
                               f"config — Type4_StateLogicViolation")
            sS, rawS = safe_request("POST", "search",
                                    {"vector": [0.05] * DIM, "limit": 200},
                                    path_params={"name": C})
            print(f"[final search] status={sS} raw={str(rawS)[:200]}")
            if sS != 200:
                DEFECTS.append(f"final search returned {sS} — data plane "
                               f"broken after churn — "
                               f"Type4_StateLogicViolation — "
                               f"raw={str(rawS)[:150]}")
            else:
                bS = parse_json(rawS)
                lst = bS.get("result") if bS else None
                if not isinstance(lst, list):
                    DEFECTS.append(f"final search 200 body lacks result list — "
                                   f"Type4_StateLogicViolation — "
                                   f"raw={str(rawS)[:150]}")
                elif len(lst) != expected and pc == expected:
                    DEFECTS.append(f"final search returned {len(lst)} points "
                                   f"but {expected} exist — read path "
                                   f"inconsistent — "
                                   f"Type4_StateLogicViolation")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        stop_evt.set()
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
