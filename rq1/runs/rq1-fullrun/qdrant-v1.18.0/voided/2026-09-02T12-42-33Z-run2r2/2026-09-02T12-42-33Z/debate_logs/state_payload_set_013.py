#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_set_013
# strategy: concurrent
# endpoint: payload+set
# constraint_ids: qdrant_state_payload_set_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/set-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 4 (concurrent operations) against
  qdrant_state_payload_set_001 (payload+set = MERGE keys). Two races on
  a 2-point collection (ids 1,2, payload {"base":"orig","keep":7}):
  (A setup) baseline scroll snapshots BASEVEC (R27 lesson: on Cosine
      collections the stored vector is L2-normalized by-design — later
      vector comparisons are readback-vs-baseline-readback only).
  (Race A — disjoint-key concurrent merge) T threads fire ONE
      wait=true set-payload each, thread j setting its OWN disjoint key
      {"tk<j>": j} on points [1,2]. If set-payload merge is atomic per
      operation (WAL-serialized), the final payload must contain "base"
      + "keep" + ALL T disjoint keys with exact values. A MISSING
      thread key = a concurrent merge write was LOST (whole-payload
      last-writer-wins would produce exactly this loss — the merge
      contract violated under concurrency); a corrupted/torn value =
      interleaved partial write. This is the concurrency face the
      sibling overwrite cannot cover: overwrite RACES legitimately lose
      keys, merge MUST NOT.
  (Race B — same-key concurrent set) 4 threads each set the SAME key
      {"shared": j}, j in 0..3. Any final value is legal iff it is
      EXACTLY one of the sent integers (last-writer-wins convergence);
      a torn value (not in {0,1,2,3}), a lost key, or a payload that is
      no longer an object = torn/interleaved write corruption.
  Post-race invariants: both points survive (id set {1,2}), both
      vectors equal BASEVEC (payload races are payload-scoped), exact
      count == 2. Plainly valid concurrent sets must not fail: 4xx on a
      valid op = Type4_StateLogicViolation; 5xx counts only after a
      /healthz liveness probe confirms the service is alive
      (Type3_RuntimeFailure); transport failure = abort, never a
      defect conclusion (G8).
  Thread count via TESTVDB_CONCURRENT_THREADS (default 10, clamped to
  4..10; 20 recommended for Qdrant per spec).
  [chunk_payload+set coverage: concurrent x qdrant_state_payload_set_001
   (disjoint-key merge no-loss race + same-key convergence race)]
Oracle: after Race A all T disjoint "tk<j>" keys plus "base"/"keep"
  are present with exact values on BOTH points (a missing thread key =
  lost concurrent merge write — Type4_StateLogicViolation); after Race
  B "shared" is exactly one of {0,1,2,3} on both points (a torn value
  = Type4_StateLogicViolation); every op returns 200 (4xx on plainly
  valid concurrent set = Type4; 5xx with /healthz alive =
  Type3_RuntimeFailure); id set {1,2}, vectors equal baseline readback
  (<=1e-6), exact count 2 at the end.
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

# payload+set is not in the runtime PATHS whitelist — register VERBATIM
# from raw_knowledge api_endpoints[].url:
#   {"path": "payload+set", "method": "POST",
#    "url": "/collections/{collection_name}/points/payload"}
rt.PATHS["payload_set"] = "/collections/{collection_name}/points/payload"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'payload' in k]}")
if rt.PATHS.get("payload_set") != "/collections/{collection_name}/points/payload":
    print("VERDICT: SCRIPT_ERROR - payload_set URL registration failed")
    sys.exit(2)

try:
    _env_thr = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10") or 10)
except ValueError:
    _env_thr = 10
T = max(4, min(10, _env_thr))   # disjoint-key lanes
B_LANES = 4                      # same-key lanes (fixed, value set {0..3})
IDS = [1, 2]
ORIG = {"base": "orig", "keep": 7}

DEFECTS = []
OP_ERRORS = []  # (tag, status, raw)


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=60):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def drain_op_errors():
    """Adjudicate collected op-level errors. Returns 'abort' on transport."""
    for tag, s, raw in OP_ERRORS:
        if s == 0:
            liveness(tag)
            return "abort"
        if 500 <= s <= 599:
            if liveness(tag):
                DEFECTS.append(f"({tag}) op returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
                return "defect"
            return "abort"
        DEFECTS.append(f"({tag}) plainly valid concurrent set returned {s} — "
                       f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
    del OP_ERRORS[:]
    return "ok"


def pay_dict(p):
    pl = p.get("payload")
    if pl is None:
        return {}, True
    if isinstance(pl, dict):
        return pl, True
    return {}, False


def vec_of(p):
    v = p.get("vector")
    return v if isinstance(v, list) else None


def vec_eq(a, b, tol=1e-6):
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
        return False
    return all(isinstance(x, (int, float)) and isinstance(y, (int, float))
               and abs(x - y) <= tol for x, y in zip(a, b))


def scroll_map(tag, coll):
    s, raw = safe_request("POST", "scroll", path_params={"name": coll},
                          body={"limit": 10, "with_payload": True,
                                "with_vector": True})
    print(f"[{tag} scroll] status={s} raw={str(raw)[:160]}")
    if s == 0:
        liveness(tag)
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) scroll returned {s} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        return None
    if s != 200:
        print(f"SETUP_ERROR: scroll returned {s}")
        return None
    try:
        res = json.loads(raw).get("result")
        pts = res.get("points") if isinstance(res, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        pts = None
    if not isinstance(pts, list):
        print(f"SETUP_ERROR: scroll result.points missing — raw={str(raw)[:200]}")
        return None
    return {p.get("id"): p for p in pts if isinstance(p, dict)}


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if s == 0:
        liveness(tag)
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) count returned {s} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        return None
    if s != 200:
        print(f"SETUP_ERROR: count returned {s}")
        return None
    try:
        cnt = json.loads(raw).get("result", {}).get("count")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        cnt = None
    if isinstance(cnt, bool) or not isinstance(cnt, int):
        print(f"SETUP_ERROR: count result.count missing — raw={str(raw)[:200]}")
        return None
    return cnt


def do_set(coll, payload, tag):
    s, raw = safe_request("POST", "payload_set",
                          path_params={"collection_name": coll},
                          body={"payload": payload, "points": IDS},
                          query_params={"wait": "true"})
    print(f"[{tag} POST set {payload!r}] status={s} raw={str(raw)[:160]}")
    if s != 200:
        OP_ERRORS.append((tag, s, raw))


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sps13_" + TS + "_"
    C = PFX + "col"

    try:
        # ---- (A setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [float(i) + 1.0, 1.0, 2.0, 3.0],
                "payload": dict(ORIG)} for i in IDS]
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[A upsert 2] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"
        base = scroll_map("A baseline", C)
        if base is None or set(base.keys()) != set(IDS):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        BASEVEC = {i: vec_of(base[i]) for i in IDS}
        if any(v is None for v in BASEVEC.values()):
            print("SETUP_ERROR: baseline readback missing vectors")
            return "SCRIPT_ERROR"

        # ---- (Race A) T threads x one disjoint key each ----
        print(f"[Race A] {T} threads, one disjoint key each, both points")
        barrier = threading.Barrier(T)

        def lane_a(j):
            try:
                barrier.wait(timeout=30)
            except threading.BrokenBarrierError:
                pass
            do_set(C, {f"tk{j}": j}, f"raceA-j{j}")

        threads = [threading.Thread(target=lane_a, args=(j,)) for j in range(T)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        verdict = drain_op_errors()
        if verdict == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if verdict == "defect":
            return "DEFECT_FOUND"
        time.sleep(0.5)

        m = scroll_map("RaceA readback", C)
        if m is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if set(m.keys()) != set(IDS):
            DEFECTS.append(f"(RaceA) point id set {sorted(m.keys())} != "
                           f"{IDS} — payload races must not delete points — "
                           f"Type4_StateLogicViolation")
        expect_a = dict(ORIG)
        for j in range(T):
            expect_a[f"tk{j}"] = j
        for i in IDS:
            if i not in m:
                continue
            pl, okp = pay_dict(m[i])
            if not okp:
                DEFECTS.append(f"(RaceA) point {i} payload is not an object — "
                               f"Type4_StateLogicViolation")
                continue
            missing = [k for k in expect_a if k not in pl]
            if missing:
                DEFECTS.append(f"(RaceA) point {i} LOST concurrent merge "
                               f"keys {missing} — payload={pl!r} — merge must "
                               f"not lose disjoint concurrent writes "
                               f"(qdrant_state_payload_set_001: set = merge) "
                               f"— Type4_StateLogicViolation")
            wrong = [k for k in expect_a if k in pl and pl[k] != expect_a[k]]
            if wrong:
                DEFECTS.append(f"(RaceA) point {i} torn values on {wrong} — "
                               f"payload={pl!r} — interleaved partial write — "
                               f"Type4_StateLogicViolation")
            if not missing and not wrong:
                print(f"[RaceA] OK: point {i} carries all {len(expect_a)} "
                      f"keys with exact values")

        # ---- (Race B) 4 threads x the SAME key ----
        print(f"[Race B] {B_LANES} threads, same key 'shared', values 0..3")
        barrier_b = threading.Barrier(B_LANES)

        def lane_b(j):
            try:
                barrier_b.wait(timeout=30)
            except threading.BrokenBarrierError:
                pass
            do_set(C, {"shared": j}, f"raceB-j{j}")

        threads = [threading.Thread(target=lane_b, args=(j,))
                   for j in range(B_LANES)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        verdict = drain_op_errors()
        if verdict == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if verdict == "defect":
            return "DEFECT_FOUND"
        time.sleep(0.5)

        m2 = scroll_map("RaceB readback", C)
        if m2 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        for i in IDS:
            if i not in m2:
                continue
            pl, okp = pay_dict(m2[i])
            if not okp:
                DEFECTS.append(f"(RaceB) point {i} payload is not an object — "
                               f"torn write — Type4_StateLogicViolation")
                continue
            shared = pl.get("shared")
            if shared not in (0, 1, 2, 3) or isinstance(shared, bool):
                DEFECTS.append(f"(RaceB) point {i} 'shared' value {shared!r} "
                               f"is NONE of the concurrently sent integers "
                               f"0..3 (torn/interleaved write) — "
                               f"payload={pl!r} — Type4_StateLogicViolation")
            else:
                print(f"[RaceB] OK: point {i} 'shared' converged to sent "
                      f"value {shared}")
            for k, v in expect_a.items():
                if k not in pl:
                    DEFECTS.append(f"(RaceB) point {i} LOST key {k!r} that "
                                   f"Race A had already merged — "
                                   f"payload={pl!r} — a same-key race must "
                                   f"not regress other keys — "
                                   f"Type4_StateLogicViolation")

        # ---- post-race invariants ----
        for i in IDS:
            if i in m2 and not vec_eq(vec_of(m2[i]), BASEVEC[i]):
                DEFECTS.append(f"(post-race) point {i} vector changed during "
                               f"payload races — Type4_StateLogicViolation")
        print("[post-race] vector preservation checked")
        cnt = exact_count("post-race count", C)
        if cnt is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if cnt != 2:
            DEFECTS.append(f"(post-race) exact count {cnt} != 2 — payload "
                           f"races must not delete points — "
                           f"Type4_StateLogicViolation")

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
