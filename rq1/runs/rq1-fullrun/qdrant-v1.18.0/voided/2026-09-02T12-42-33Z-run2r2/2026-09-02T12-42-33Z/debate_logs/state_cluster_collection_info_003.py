#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_collection_info_003
# strategy: concurrent
# endpoint: cluster+collection+info
# constraint_ids: qdrant_behavioral_cluster_collection_info_001, qdrant_type_cluster_collection_info_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness — collection lifecycle racing the per-collection cluster-info reader)
"""
Attack: Strategy 7 (lifecycle x access concurrency). Thread L cycles
  create->drop of collection C; thread R continuously reads the per-
  collection cluster-info face GET /collections/{C}/cluster. Mutation-point
  justification (G6): the cluster-info reader is exactly the component that
  must resolve 'collection temporarily absent' mid-lifecycle — the timing
  window between a drop and the next create is the most destructive mutation
  for a per-collection report endpoint (it flips the path parameter between
  the two promised dispositions 200/404, and a report read racing collection
  destruction is the classic source of unwrap-panics -> 500). Judged
  signals: 5xx from the reader during the race (>=2 occurrences per the
  strategy-7 reproduction rule — a single one is an inconclusive
  observation); 404 while C is absent = CORRECT unavailable semantics; 200
  while C exists must still carry the full six-field CollectionClusterInfo
  shape (shape break >=2 = Type4); after quiescence with C verifiably
  dropped (describe control = 404) the reader must return exactly 404 — a
  200 is a ghost row (the R1-confirmed 200-on-unknown family under race);
  after one final recreate the report must be 200 with the full shape
  (churn must not corrupt the report).
  [chunk_cluster+collection+info coverage: concurrent(lifecycle, strategy 7) x
   qdrant_behavioral_cluster_collection_info_001 (+ shape clause of
   qdrant_type_cluster_collection_info_001)]
Oracle: during the race the reader never gets 5xx (>=2 x 5xx =
  Type3_RuntimeFailure after /healthz liveness) and every 200 carries all
  six CollectionClusterInfo fields (>=2 shape breaks = Type4); after the
  final verified drop the reader returns exactly 404 (200 =
  Type4_StateLogicViolation ghost); after recreate it returns 200 with full
  shape
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

REQUIRED_FIELDS = ("peer_id", "shard_count", "local_shards", "remote_shards",
                   "shard_transfers", "resharding_operations")


def alive():
    hs, hraw = rt.request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def reader_probes(name):
    """One reader pass -> ('ok404'|'ok200'|'shape'|'5xx'|'transport'|'other:N', detail)."""
    try:
        s, raw = rt.request("GET", "collection_cluster", path_params={"name": name})
    except Exception as e:
        return "transport", str(e)[:120]
    if s == 0:
        return "transport", str(raw)[:120]
    if s == 404:
        return "ok404", str(raw)[:120]
    if 500 <= s <= 599:
        return "5xx", f"{s} raw={str(raw)[:150]}"
    if s == 200:
        try:
            b = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError, TypeError):
            return "shape", f"200 unparseable body raw={str(raw)[:150]}"
        node = b.get("result") if isinstance(b, dict) else None
        if not isinstance(node, dict):
            return "shape", f"200 result not object raw={str(raw)[:150]}"
        missing = [f for f in REQUIRED_FIELDS if f not in node]
        if missing:
            return "shape", f"200 missing fields {missing}"
        return "ok200", ""
    return f"other:{s}", str(raw)[:120]


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scci3_" + TS + "_"
    C = PFX + "col"
    N_CYCLES = max(3, int(os.environ.get("TESTVDB_CLUSTER_INFO_CYCLES", "8")))
    DEFECTS = []
    lock = threading.Lock()
    stop_evt = threading.Event()
    bucket = {"5xx": [], "shape": [], "transport": [], "other": []}

    def lifecycle_thread():
        for i in range(N_CYCLES):
            if stop_evt.is_set():
                return
            try:
                ok, err = rt.setup_default(C, 4, "Cosine")
                if not ok:
                    print(f"[L#{i}] create not ok: {err[:120]}")
            except Exception as e:
                print(f"[L#{i}] create exception: {e}")
            time.sleep(0.08)
            try:
                rt.request("DELETE", "drop_collection", path_params={"name": C})
            except Exception as e:
                print(f"[L#{i}] drop exception: {e}")
            time.sleep(0.08)
        print("[L] lifecycle loop finished")

    def reader_thread():
        for i in range(N_CYCLES * 8):
            if stop_evt.is_set():
                return
            kind, detail = reader_probes(C)
            if kind.startswith("other:"):
                with lock:
                    bucket["other"].append(f"R#{i}: {kind} {detail}")
            elif kind in ("5xx", "shape", "transport"):
                with lock:
                    bucket[kind].append(f"R#{i}: {detail}")
            time.sleep(0.02)
        print("[R] reader loop finished")

    try:
        # seed: C exists once so the first reader probes have a legal 200 window
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"

        threads = [
            threading.Thread(target=lifecycle_thread, daemon=True),
            threading.Thread(target=reader_thread, daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        stop_evt.set()

        # ---- quiescence: C must be verifiably gone before judging residue ----
        gone = False
        for _ in range(20):
            try:
                s, _raw = rt.request("GET", "describe_collection",
                                     path_params={"name": C})
            except Exception:
                s = -1
            if s == 404:
                gone = True
                break
            time.sleep(0.5)
        print(f"[quiescence] describe({C}) -> 404? {gone}")
        if not gone:
            try:
                rt.request("DELETE", "drop_collection", path_params={"name": C})
            except Exception:
                pass
            time.sleep(1.0)
        time.sleep(0.8)  # settle async cleanup

        # ---- post-race disposition: verifiably-absent C must read exactly 404 ----
        if gone:
            s, raw = rt.request("GET", "collection_cluster", path_params={"name": C})
            print(f"[post-race absent] status={s} raw={raw[:300]}")
            if s == 200:
                DEFECTS.append(
                    f"cluster info returns 200 for '{C}' after the race although "
                    f"describe verifiably 404s — ghost per-collection report row — "
                    f"Type4_StateLogicViolation — raw={raw[:200]}"
                )
            elif 500 <= s <= 599:
                if alive():
                    DEFECTS.append(
                        f"cluster info after quiescence returned {s} (404 expected, "
                        f"service alive) — Type3_RuntimeFailure — raw={raw[:200]}"
                    )
                else:
                    return "SCRIPT_ERROR"
            elif s == 0:
                if not alive():
                    return "SCRIPT_ERROR"
            elif s != 404:
                print(f"OBSERVATION: post-race absent returned {s} — not judged")

        # ---- recreate: report must be 200 with the full shape after churn ----
        ok2, err2 = rt.setup_default(C, 4, "Cosine")
        if not ok2:
            print(f"ENV_ISSUE: recreate after race not ok: {err2[:120]}")
        else:
            s, raw = rt.request("GET", "collection_cluster", path_params={"name": C})
            print(f"[post-recreate] status={s} raw={raw[:300]}")
            if s == 200:
                try:
                    b = json.loads(raw)
                    node = b.get("result") if isinstance(b, dict) else None
                    missing = ([f for f in REQUIRED_FIELDS
                                if f not in node] if isinstance(node, dict)
                               else ["result-not-object"])
                    if missing:
                        DEFECTS.append(
                            f"cluster info 200 after recreate but shape broken: "
                            f"{missing} — Type4_StateLogicViolation"
                        )
                except (json.JSONDecodeError, ValueError, TypeError):
                    DEFECTS.append(
                        f"cluster info 200 after recreate but body unparseable — "
                        f"raw={raw[:200]} — Type4_StateLogicViolation"
                    )
            elif 500 <= s <= 599:
                if alive():
                    DEFECTS.append(
                        f"cluster info after recreate returned {s} (200 expected, "
                        f"service alive) — Type3_RuntimeFailure"
                    )
                else:
                    return "SCRIPT_ERROR"

        # ---- race-window signals (strategy-7 reproduction rule: >=2) ----
        for tag in ("5xx", "shape"):
            hits = bucket[tag]
            if len(hits) >= 2:
                dtype = ("Type3_RuntimeFailure" if tag == "5xx"
                         else "Type4_StateLogicViolation")
                DEFECTS.append(
                    f"race window: {len(hits)} x {tag} on cluster-info reads while the "
                    f"collection lifecycle interleaved (graceful 404/200-with-shape "
                    f"expected) — {dtype} — samples: {hits[:3]}"
                )
            elif hits:
                print(f"OBSERVATION (inconclusive, <2 occurrences): {tag}: {hits}")
        if bucket["other"]:
            print(f"OBSERVATION: non-404 4xx dispositions during race "
                  f"(correct-absent is 404; recorded, not judged): "
                  f"{bucket['other'][:3]}")
        if bucket["transport"] and not DEFECTS:
            print(f"ENV_ISSUES: {bucket['transport'][:3]}")
            if not alive():
                return "SCRIPT_ERROR"

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        stop_evt.set()
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
