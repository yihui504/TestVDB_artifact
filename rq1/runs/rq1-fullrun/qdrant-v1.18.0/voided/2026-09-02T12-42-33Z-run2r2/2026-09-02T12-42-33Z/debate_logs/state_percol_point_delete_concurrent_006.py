#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_percol_point_delete_concurrent_006
# strategy: concurrent
# endpoint: per_collection
# constraint_ids: qdrant_inv_point_delete_gone_001, qdrant_inv_count_consistency_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
"""
Attack: concurrent (Strategy 4: same-resource conflicting-mutation race;
  Blindspot: BS-03 Concurrency State Blindness — WAL/lock interleavings
  between delete and write) x qdrant_inv_point_delete_gone_001 (a deleted
  point must be gone from EVERY retrieval face) + qdrant_inv_count_consistency_001
  (the exact count reflects N). 20 points ids 0..19 seeded with payload
  {"n": i, "src": "seed"}. All threads start on one threading.Barrier:
  W writer threads each upsert ALL 20 ids wait=true with the IDENTICAL
  writer payload {"n": i, "src": "writer"}; D deleter threads each delete
  the EVEN ids [0..18] wait=true. Even ids are genuinely raced (delete vs
  overwrite); odd ids are unraced by deleters and must survive. Because
  every writer writes the same per-id payload, the oracle is
  INTERLEAVING-INDEPENDENT: after all threads join, each id is either
  (a) absent everywhere — count, scroll, batch-get, single GET 404 — or
  (b) present with EXACTLY {"n": <id>, "src": "writer"}; the seed payload
  surviving on ANY id means a writer's acknowledged wait=true write was
  silently lost; a torn payload (mix of seed/writer keys) means a
  partial application. Concretely adjudicated: (1) all racing requests
  return 200 (5xx + /healthz alive = Type3); (2) odd ids all present
  with writer payload (a lost unraced write = Type4); (3) absent ids
  return 404 on single GET (200 = zombie = Type4); (4) present ids
  absent from NO face and count == |present set| on two consecutive
  exact reads (flapping or mismatch = Type4); (5) payload is never
  seed, never torn.
  [chunk_per_collection coverage: concurrent x
  qdrant_inv_point_delete_gone_001 + qdrant_inv_count_consistency_001
  (delete-vs-overwrite race, interleaving-independent self-consistency)]
Oracle: every barrier-started racing request -> 200 (5xx with /healthz
  alive = Type3_RuntimeFailure; transport failure -> liveness re-check,
  alive = Type3, dead = SCRIPT_ERROR); post-join: every odd id present
  with payload deep-equal {"n": id, "src": "writer"} type-strict; every
  absent id single-GETs 404; every present id appears in scroll AND
  batch-get; exact count == number of present ids on both reads; no id
  reads back seed payload or a torn mix — each violation =
  Type4_StateLogicViolation.
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

# points+get (batch) is not in the runtime PATHS whitelist — register
# VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "points+get", "method": "POST",
#    "url": "/collections/{collection_name}/points/get"}
rt.PATHS["get_points"] = "/collections/{collection_name}/points/get"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k == 'get_points']}")

TOTAL = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))
DELETERS = TOTAL // 2
WRITERS = TOTAL - DELETERS
N_IDS = 20
EVEN_IDS = [i for i in range(N_IDS) if i % 2 == 0]

DEFECTS = []
ABORT = [False]
RACE_ERRORS = []  # (role, idx, status, raw_snippet)


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=60):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def type_strict_eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return type(a) is type(b) and a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return (set(a.keys()) == set(b.keys())
                and all(type_strict_eq(a[k], b[k]) for k in a))
    if isinstance(a, list):
        return (len(a) == len(b)
                and all(type_strict_eq(x, y) for x, y in zip(a, b)))
    return a == b


def vec(i):
    return [float(i) + 0.125, 0.25, 0.5, 0.75]


def writer_payload(i):
    return {"n": i, "src": "writer"}


def racer(barrier, role, idx, coll):
    try:
        barrier.wait(timeout=30)
    except threading.BrokenBarrierError:
        return
    if role == "writer":
        pts = [{"id": i, "vector": vec(i), "payload": writer_payload(i)}
               for i in range(N_IDS)]
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": coll},
                              body={"points": pts},
                              query_params={"wait": "true"})
    else:
        s, raw = safe_request("POST", "delete_points",
                              path_params={"name": coll},
                              body={"points": EVEN_IDS},
                              query_params={"wait": "true"})
    print(f"[{role} {idx}] status={s} raw={str(raw)[:100]}")
    if s != 200:
        RACE_ERRORS.append((role, idx, s, str(raw)[:120]))


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag}] status={s} raw={str(raw)[:160]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        else:
            DEFECTS.append(f"({tag}) count transport failure with service "
                           f"alive — Type3_RuntimeFailure")
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) count returned {s} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} count returned {s}")
        return None
    try:
        res = json.loads(raw).get("result")
        cnt = res.get("count") if isinstance(res, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        cnt = None
    if isinstance(cnt, bool) or not isinstance(cnt, int):
        return None
    return cnt


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spdr6_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    try:
        # ---- (seed: 20 points, seed payloads) ----
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        seed = [{"id": i, "vector": vec(i),
                 "payload": {"n": i, "src": "seed"}} for i in range(N_IDS)]
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C}, body={"points": seed},
                              query_params={"wait": "true"})
        print(f"[seed upsert {N_IDS}] status={s} raw={raw[:150]}")
        if s != 200 or exact_count("seed", C) != N_IDS:
            print("SETUP_ERROR: seed stage failed")
            return "SCRIPT_ERROR"

        # ---- (race: barrier-started writers x deleters) ----
        print(f"[race] {WRITERS} writers (all ids) x {DELETERS} deleters "
              f"(even ids), barrier start")
        barrier = threading.Barrier(TOTAL)
        threads = []
        wi = 0
        di = 0
        for _ in range(TOTAL):
            if wi < WRITERS:
                threads.append(threading.Thread(
                    target=racer, args=(barrier, "writer", wi, C)))
                wi += 1
            else:
                threads.append(threading.Thread(
                    target=racer, args=(barrier, "deleter", di, C)))
                di += 1
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=180)

        for (role, idx, s, raw) in RACE_ERRORS:
            tag = f"{role} {idx}"
            if s == 0:
                if not liveness(tag):
                    ABORT[0] = True
                else:
                    DEFECTS.append(f"({tag}) transport failure with service "
                                   f"alive — Type3_RuntimeFailure — raw={raw}")
            elif 500 <= s <= 599:
                if liveness(tag):
                    DEFECTS.append(f"({tag}) returned {s} with service alive "
                                   f"— Type3_RuntimeFailure — raw={raw}")
                else:
                    ABORT[0] = True
            else:
                DEFECTS.append(f"({tag}) racing {role} returned {s} — "
                               f"Type3_RuntimeFailure — raw={raw}")
        print(f"[race] {TOTAL - len(RACE_ERRORS)}/{TOTAL} racing requests "
              f"returned 200")

        # ---- (post-join self-consistency) ----
        time.sleep(2)
        s, raw = safe_request("POST", "scroll", path_params={"name": C},
                              body={"limit": 100, "with_payload": True})
        print(f"[scroll] status={s} raw={str(raw)[:200]}")
        if s == 0:
            liveness("scroll")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if 500 <= s <= 599 or s != 200:
            if 500 <= s <= 599 and liveness("scroll"):
                DEFECTS.append("(scroll) returned 5xx with service alive — "
                               f"Type3_RuntimeFailure")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        try:
            res = json.loads(raw).get("result")
            spts = res.get("points") if isinstance(res, dict) else None
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            spts = None
        if not isinstance(spts, list):
            print(f"SETUP_ERROR: scroll result.points missing — raw={raw[:200]}")
            return "SCRIPT_ERROR"
        present = {}
        for p in spts:
            if isinstance(p, dict):
                present[p.get("id")] = p
        present_ids = set(present.keys())
        print(f"[scroll] present ids: {sorted(i for i in present_ids if i is not None)}")

        # (2) odd ids must all be present with writer payload
        for i in range(N_IDS):
            if i % 2 == 1 and i not in present_ids:
                DEFECTS.append(f"(odd id {i}) unraced by any deleter but "
                               f"absent after the race — a writer's "
                               f"acknowledged wait=true write was lost — "
                               f"Type4_StateLogicViolation")
        # (5) payload face: present ids carry EXACTLY the writer payload
        for i in sorted(x for x in present_ids if x is not None):
            pl = present[i].get("payload")
            pl = pl if isinstance(pl, dict) else {}
            if not type_strict_eq(pl, writer_payload(i)):
                DEFECTS.append(f"(id {i}) present with payload {pl!r} != "
                               f"writer payload {writer_payload(i)!r} — "
                               f"seed residue or torn write — "
                               f"Type4_StateLogicViolation")
        if not [d for d in DEFECTS if "payload" in d or "torn" in d]:
            print("[payload] OK: every present id carries exactly the "
                  "writer payload")

        # (3) absent ids must 404 on single GET
        absent_ids = [i for i in range(N_IDS) if i not in present_ids]
        for i in absent_ids:
            s, raw = safe_request("GET", "get_point",
                                  path_params={"name": C, "point_id": i})
            print(f"[get absent {i}] status={s} raw={str(raw)[:120]}")
            if s == 200:
                DEFECTS.append(f"(absent id {i}) not in scroll/count but "
                               f"single GET returns 200 — zombie point — "
                               f"Type4_StateLogicViolation")
            elif s == 0:
                if not liveness(f"get absent {i}"):
                    ABORT[0] = True
            elif 500 <= s <= 599:
                if liveness(f"get absent {i}"):
                    DEFECTS.append(f"(absent id {i}) single GET returned "
                                   f"{s} with service alive — "
                                   f"Type3_RuntimeFailure")

        # (4) batch-get agreement + count == |present| twice
        s, raw = safe_request("POST", "get_points",
                              path_params={"collection_name": C},
                              body={"ids": list(range(N_IDS)),
                                    "with_payload": True})
        print(f"[batch get all] status={s} raw={str(raw)[:200]}")
        if s == 200:
            res = None
            try:
                res = json.loads(raw).get("result")
            except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
                pass
            got_list = res if isinstance(res, list) else []
            got_ids = set(p.get("id") for p in got_list
                          if isinstance(p, dict))
            if got_ids != present_ids:
                DEFECTS.append(f"(batch-get face) ids {sorted(got_ids)} != "
                               f"scroll-present ids {sorted(i for i in present_ids if i is not None)} — "
                               f"retrieval faces disagree — "
                               f"Type4_StateLogicViolation")
            else:
                print("[batch-get face] OK: agrees with scroll")
        c1 = exact_count("count read1", C)
        c2 = exact_count("count read2", C)
        for tag, c in (("count read1", c1), ("count read2", c2)):
            if c is not None and c != len(present_ids):
                DEFECTS.append(f"({tag}) exact count {c} != |present set| "
                               f"{len(present_ids)} — count/retrieval "
                               f"disagreement — Type4_StateLogicViolation")
        if c1 is not None and c2 is not None and c1 != c2:
            DEFECTS.append(f"(count stability) consecutive exact reads "
                           f"disagree: {c1} vs {c2} — "
                           f"Type4_StateLogicViolation")
        if c1 == len(present_ids):
            print(f"[count] OK: {c1} == |present set|")

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
