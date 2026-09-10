#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_concurrent_007
# strategy: concurrent
# endpoint: points+query
# constraint_ids: qdrant_state_points_query_001, qdrant_behavioral_points_query_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
"""
Attack: concurrent overwrite x by-id query race (Strategy 4: concurrent
  operations; Blindspot: BS-03 Concurrency State Blindness) x
  qdrant_state_points_query_001 (by-id lookup must fetch the point's
  CURRENT stored vector) + qdrant_behavioral_points_query_001 (valid
  query on an existing collection must 200). 8 point ids; each id has two
  well-formed variants: A_i near +x ([1, .05i, 0, 0]) and B_i near +y
  ([.05i, 1, 0, 0]). W writer threads (default 4) each iterate 12 times:
  full 8-id upsert (wait=true) alternating variant by iteration parity —
  every intermediate state is legal, dims always match, no id is ever
  absent. R reader threads (default TESTVDB_CONCURRENT_THREADS-derived,
  4..8) each iterate 20 times: by-id query on a rotating id (limit 4)
  plus plain nearest queries — collection exists for the whole run, so
  every read must be 200. Post-join quiesced checks:
  (Q1) exact count == 8 (no duplicate-id leak, no loss).
  (Q2) for each id: stored vector readback (batch-get with_vector) must
  be cosine-close (>=0.999) to exactly one of {A_i, B_i} — the final
  state is one of the written variants, never a blend.
  (Q3) differential oracle (readback-vs-baseline, R27-compliant): by-id
  query {"query": id, params.exact} top-3 (self excluded) must EQUAL the
  top-3 of a direct exact query using the readback stored vector as the
  query — the by-id path and the explicit-vector path must agree on the
  same stored state; disagreement = the by-id lookup served a stale or
  corrupt vector. Distinct jitter removes tie ambiguity.
  [chunk_points+query coverage: concurrent x qdrant_state_points_query_001
  (by-id reads during concurrent overwrites + quiesced differential
  equivalence) + concurrent x qdrant_behavioral_points_query_001 (200
  promise on a live collection under concurrent writes)]
Oracle: during the race every reader query returns 200 — any 500 with
  /healthz alive = Type3_RuntimeFailure (5xx tallies printed per reader);
  (Q1) exact count == 8 — mismatch = Type4_StateLogicViolation; (Q2)
  each id's stored vector matches exactly one variant (blend/mismatch =
  Type4); (Q3) by-id top-3 == direct-vector top-3 for every id —
  divergence = stale/corrupt by-id lookup (Type4_StateLogicViolation);
  transport failure -> liveness re-check before any verdict (dead
  service aborts as SCRIPT_ERROR, never a defect).
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

# URLs used VERBATIM from raw_knowledge api_endpoints[]:
#   {"method": "POST", "url": "/collections/{collection_name}/points"} -> POST batch-get face
rt.PATHS["get_points_by_ids"] = "/collections/{collection_name}/points"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('query', 'get_points_by_ids', 'upsert_points', 'count')]}")

DEFECTS = []
ABORT = [False]

IDS = [100, 101, 102, 103, 104, 105, 106, 107]


def var_a(i):
    return [1.0, 0.05 * (i % 10), 0.0, 0.0]


def var_b(i):
    return [0.05 * (i % 10), 1.0, 0.0, 0.0]


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def handle_transport(tag, status, raw):
    if status == 0:
        if not liveness(tag):
            ABORT[0] = True
        return True
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {status} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return True
    return False


def writer_thread(coll, tid, iterations, err_box):
    for it in range(iterations):
        variant = var_a if it % 2 == 0 else var_b
        pts = [{"id": pid, "vector": variant(pid % 10)} for pid in IDS]
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": coll},
                              body={"points": pts},
                              query_params={"wait": "true"})
        if s != 200:
            err_box.append(f"writer{tid} it{it} upsert status={s} "
                           f"raw={str(raw)[:100]}")
            if handle_transport(f"writer{tid}-it{it}", s, raw):
                return


def reader_thread(coll, tid, iterations, err_box):
    for it in range(iterations):
        pid = IDS[(tid + it) % len(IDS)]
        s, raw = safe_request("POST", "query", path_params={"name": coll},
                              body={"query": pid, "limit": 4})
        if s != 200:
            err_box.append(f"reader{tid} it{it} byid({pid}) status={s} "
                           f"raw={str(raw)[:100]}")
            if handle_transport(f"reader{tid}-byid-it{it}", s, raw):
                return
        if it % 4 == 0:
            s2, raw2 = safe_request("POST", "query",
                                    path_params={"name": coll},
                                    body={"query": [1.0, 0.0, 0.0, 0.0],
                                          "limit": 3})
            if s2 != 200:
                err_box.append(f"reader{tid} it{it} nearest status={s2} "
                               f"raw={str(raw2)[:100]}")
                if handle_transport(f"reader{tid}-nn-it{it}", s2, raw2):
                    return


def query_ids(coll, body):
    s, raw = safe_request("POST", "query", path_params={"name": coll}, body=body)
    if s != 200:
        return s, None
    try:
        res = json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return s, None
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        return s, None
    return s, [p.get("id") for p in pts if isinstance(p, dict)]


def cosine(a, b):
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spq7_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    threads_cfg = os.environ.get("TESTVDB_CONCURRENT_THREADS", "10")
    try:
        n_total = int(threads_cfg)
    except ValueError:
        n_total = 10
    n_writers = max(2, min(4, n_total // 3))
    n_readers = max(2, min(8, n_total - n_writers))
    print(f"[cfg] TESTVDB_CONCURRENT_THREADS={n_total} -> writers={n_writers} "
          f"readers={n_readers}")

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        s_up, raw_up = safe_request("PUT", "upsert_points",
                                    path_params={"name": C},
                                    body={"points": [{"id": pid,
                                                      "vector": var_a(pid % 10)}
                                                     for pid in IDS]},
                                    query_params={"wait": "true"})
        print(f"[seed upsert {len(IDS)}] status={s_up} raw={str(raw_up)[:160]}")
        if handle_transport("seed upsert", s_up, raw_up) or s_up != 200:
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        err_box = []
        threads = []
        t0 = time.time()
        for w in range(n_writers):
            threads.append(threading.Thread(target=writer_thread,
                                            args=(C, w, 12, err_box)))
        for r in range(n_readers):
            threads.append(threading.Thread(target=reader_thread,
                                            args=(C, r, 20, err_box)))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        print(f"[race] finished in {time.time() - t0:.1f}s; "
              f"non-200 events: {len(err_box)}")
        for e in err_box[:12]:
            print(f"[race non-200] {e}")

        time.sleep(1.0)  # quiesce before state adjudication

        # ---- Q1: count arithmetic (8 ids, only overwrites happened) ----
        s_ct, raw_ct = safe_request("POST", "count", path_params={"name": C},
                                    body={"exact": True})
        print(f"[Q1 count] status={s_ct} raw={str(raw_ct)[:160]}")
        if handle_transport("Q1 count", s_ct, raw_ct):
            print("SETUP_ERROR: post-race count failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        try:
            cnt = json.loads(raw_ct).get("result", {}).get("count")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            cnt = None
        if isinstance(cnt, int) and cnt != len(IDS):
            DEFECTS.append(f"(Q1) exact count {cnt} != {len(IDS)} after "
                           f"concurrent same-id overwrites — loss/dup — "
                           f"Type4_StateLogicViolation")
        elif isinstance(cnt, int):
            print(f"[Q1] OK: count == {len(IDS)}")

        # ---- Q2 + Q3: per-id readback and differential equivalence ----
        s_bg, raw_bg = safe_request("POST", "get_points_by_ids",
                                    path_params={"collection_name": C},
                                    body={"ids": IDS, "with_vector": True})
        print(f"[Q2 batch-get] status={s_bg} raw={str(raw_bg)[:200]}")
        if handle_transport("Q2 batch-get", s_bg, raw_bg) or s_bg != 200:
            print("SETUP_ERROR: batch-get readback failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        try:
            recs = json.loads(raw_bg).get("result")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            recs = None
        stored = {}
        if isinstance(recs, list):
            for rec in recs:
                if isinstance(rec, dict) and "id" in rec:
                    stored[rec["id"]] = rec.get("vector")

        for pid in IDS:
            v_st = stored.get(pid)
            if not isinstance(v_st, list):
                DEFECTS.append(f"(Q2) id {pid}: stored vector unreadable — "
                               f"Type4_StateLogicViolation")
                continue
            j = pid % 10
            ca = cosine(v_st, var_a(j))
            cb = cosine(v_st, var_b(j))
            matches_a = ca is not None and ca >= 0.999
            matches_b = cb is not None and cb >= 0.999
            if matches_a == matches_b:  # both (impossible blend) or neither
                DEFECTS.append(f"(Q2) id {pid}: stored vector matches "
                               f"{ 'both' if matches_a else 'neither' } variant "
                               f"(cosA={ca} cosB={cb}) — corrupt post-race "
                               f"state — Type4_StateLogicViolation")
                continue
            print(f"[Q2] id {pid}: stored == variant "
                  f"{'A' if matches_a else 'B'} (cosA={ca:.6f} cosB={cb:.6f})")

            # Q3 differential: by-id path vs explicit-vector path (exact)
            s_by, ids_by = query_ids(C, {"query": pid, "limit": 5,
                                         "params": {"exact": True}})
            s_dir, ids_dir = query_ids(C, {"query": v_st, "limit": 6,
                                           "params": {"exact": True}})
            if s_by != 200 or s_dir != 200:
                print(f"[Q3] id {pid}: query statuses by={s_by} dir={s_dir}")
                continue
            top_by = [i for i in (ids_by or []) if i != pid][:3]
            top_dir = [i for i in (ids_dir or []) if i != pid][:3]
            print(f"[Q3] id {pid}: by-id top3={top_by} direct top3={top_dir}")
            if top_by != top_dir:
                DEFECTS.append(f"(Q3) id {pid}: by-id lookup ranking "
                               f"{top_by} != explicit readback-vector ranking "
                               f"{top_dir} — by-id path served stale/corrupt "
                               f"vector after concurrent writes — "
                               f"Type4_StateLogicViolation")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        if ABORT[0]:
            print("ABORT: environment/transport unavailable mid-run")
            return "SCRIPT_ERROR"
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
