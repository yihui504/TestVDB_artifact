#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_clear_003
# strategy: concurrent
# endpoint: payload+clear
# constraint_ids: qdrant_state_payload_clear_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/clear-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 Concurrency State Blindness
"""
Attack: Strategy 4 (concurrent operations) against
  qdrant_state_payload_clear_001: "after clear, targeted points carry no
  payload keys". Two races on a 20-point collection (all ops wait=true):
  (Race A disjoint clears) PARTS threads concurrently clear DISJOINT
      point slices — the union covers all 20 ids. After the join, EVERY
      point must be payload-empty: a point that keeps its payload means
      one concurrent clear was silently lost (lost update — Type4);
      exact count must stay 20 (clear is not delete).
  (Race B clear vs full-overwrite, ROUNDS rounds) one thread issues a
      single clear-all while another concurrently restores every point's
      EXACT original payload via payload+overwrite. Legal serial
      outcomes per point are only: {} (clear applied last) or exactly
      the original 2-key dict (overwrite applied last). ANY other key
      set (partial merge, extra keys, only-one-key survivor) = a torn
      write the storage layer must never expose (Type4).
  (Convergence close) one final deterministic clear -> all 20 empty:
      the state machine must still converge after the races.
  Op-level errors: 0 = transport (liveness re-check via /healthz);
  5xx with service alive = Type3_RuntimeFailure; 4xx on these plainly
  valid ops = Type4 (valid op rejected under concurrency).
  Thread scale from TESTVDB_CONCURRENT_THREADS (default 10, clamped to
  2..4 partitions for the disjoint leg).
  [chunk_payload+clear coverage: concurrent x qdrant_state_payload_clear_001
   (disjoint concurrent clears + clear-vs-overwrite torn-state oracle)]
Oracle: after Race A all 20 payloads are exactly empty and count == 20;
  after every Race B round each payload is in {{}, original_dict} —
  anything else = Type4_StateLogicViolation torn state; no op returns
  0/4xx/5xx (5xx judged Type3 only when /healthz is alive); after the
  final clear all 20 payloads empty and count == 20; vectors unchanged
  throughout (<=1e-6).
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

# payload+clear / payload+overwrite are not in the runtime PATHS whitelist —
# register VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "payload+clear", "method": "POST",
#    "url": "/collections/{collection_name}/points/payload/clear"}
#   {"path": "payload+overwrite", "method": "PUT",
#    "url": "/collections/{collection_name}/points/payload"}
rt.PATHS["payload_clear"] = "/collections/{collection_name}/points/payload/clear"
rt.PATHS["payload_overwrite"] = "/collections/{collection_name}/points/payload"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'payload' in k]}")
if (rt.PATHS.get("payload_clear") != "/collections/{collection_name}/points/payload/clear"
        or rt.PATHS.get("payload_overwrite") != "/collections/{collection_name}/points/payload"):
    print("VERDICT: SCRIPT_ERROR - payload endpoint URL registration failed")
    sys.exit(2)

N = 20
ROUNDS = 4
try:
    _env_thr = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10") or 10)
except ValueError:
    _env_thr = 10
PARTS = max(2, min(4, _env_thr))
IDS = list(range(N))
ORIG = {i: {"k": f"v{i}", "grp": "even" if i % 2 == 0 else "odd"}
        for i in IDS}
VECTORS = {i: [float(i) + 1.0, 1.0, 2.0, 3.0] for i in IDS}

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
        DEFECTS.append(f"({tag}) plainly valid concurrent op returned {s} — "
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


def vec_ok(p, expected, tol=1e-6):
    v = p.get("vector")
    if not isinstance(v, list) or len(v) != len(expected):
        return False
    return all(isinstance(a, (int, float)) and abs(a - b) <= tol
               for a, b in zip(v, expected))


def scroll_map(tag, coll):
    s, raw = safe_request("POST", "scroll", path_params={"name": coll},
                          body={"limit": N + 10, "with_payload": True,
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


def check_ids_vectors(tag, m):
    if set(m.keys()) != set(IDS):
        DEFECTS.append(f"({tag}) point id set {sorted(m.keys())} != 0..{N-1} "
                       f"— clear races must not delete points — "
                       f"Type4_StateLogicViolation")
    for i in IDS:
        if i not in m:
            continue
        _, okp = pay_dict(m[i])
        if not okp:
            DEFECTS.append(f"({tag}) point {i} payload is not an object — "
                           f"Type4_StateLogicViolation")
        if not vec_ok(m[i], VECTORS[i]):
            DEFECTS.append(f"({tag}) point {i} vector changed during payload "
                           f"races — Type4_StateLogicViolation")


def do_clear(coll, ids, tag):
    s, raw = safe_request("POST", "payload_clear",
                          path_params={"collection_name": coll},
                          body={"points": ids},
                          query_params={"wait": "true"})
    print(f"[{tag}] status={s} raw={str(raw)[:120]}")
    if s not in (200,):
        OP_ERRORS.append((tag, s, raw))


def do_overwrite(coll, i, tag):
    s, raw = safe_request("PUT", "payload_overwrite",
                          path_params={"collection_name": coll},
                          body={"payload": ORIG[i], "points": [i]},
                          query_params={"wait": "true"})
    if s != 200:
        print(f"[{tag} pt{i}] status={s} raw={str(raw)[:120]}")
        OP_ERRORS.append((f"{tag} pt{i}", s, raw))


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spc3_" + TS + "_"
    C = PFX + "col"
    print(f"[config] N={N} PARTS={PARTS} ROUNDS={ROUNDS} "
          f"(TESTVDB_CONCURRENT_THREADS={_env_thr})")

    try:
        # ---- (A setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": VECTORS[i], "payload": ORIG[i]}
               for i in IDS]
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[A upsert {N}] status={u_s} raw={u_raw[:150]}")
        if u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"
        base = scroll_map("A baseline", C)
        if base is None:
            return "SCRIPT_ERROR"
        for i in IDS:
            pl, okp = pay_dict(base.get(i, {}))
            if not okp or pl != ORIG[i]:
                print(f"SETUP_ERROR: baseline point {i} payload {pl!r} != {ORIG[i]!r}")
                return "SCRIPT_ERROR"

        # ---- (Race A disjoint concurrent clears) ----
        slices = [IDS[k::PARTS] for k in range(PARTS)]
        threads = []
        for k, sl in enumerate(slices):
            t = threading.Thread(target=do_clear,
                                 args=(C, sl, f"raceA-part{k}"))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(120)
        st = drain_op_errors()
        if st == "abort":
            return "SCRIPT_ERROR"
        if st == "defect":
            return "DEFECT_FOUND"
        time.sleep(0.5)
        after_a = scroll_map("raceA readback", C)
        if after_a is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        for i in IDS:
            if i not in after_a:
                continue
            pl, okp = pay_dict(after_a[i])
            if not okp:
                DEFECTS.append(f"(raceA) point {i} payload is not an object "
                               f"— Type4_StateLogicViolation")
            elif len(pl) != 0:
                DEFECTS.append(f"(raceA) point {i} still carries payload "
                               f"keys {sorted(pl.keys())} after {PARTS} "
                               f"disjoint wait=true clears covering all ids "
                               f"— a concurrent clear was lost — "
                               f"qdrant_state_payload_clear_001 pins "
                               f"'targeted points carry no payload keys' — "
                               f"Type4_StateLogicViolation")
        check_ids_vectors("raceA", after_a)
        c_a = exact_count("raceA count", C)
        if c_a is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if c_a != N:
            DEFECTS.append(f"(raceA) exact count {c_a} != {N} after "
                           f"concurrent clears — Type4_StateLogicViolation")
        if not any("raceA" in d for d in DEFECTS):
            print(f"[raceA] OK: all {N} payloads empty after disjoint clears")

        # ---- (Race B clear vs full-overwrite, per round) ----
        for rnd in range(ROUNDS):
            t_clear = threading.Thread(target=do_clear,
                                       args=(C, IDS, f"raceB-r{rnd}-clear"))
            t_over = threading.Thread(
                target=lambda r=rnd: [do_overwrite(C, i, f"raceB-r{r}-ow")
                                      for i in IDS])
            t_clear.start()
            t_over.start()
            t_clear.join(120)
            t_over.join(120)
            st = drain_op_errors()
            if st == "abort":
                return "SCRIPT_ERROR"
            if st == "defect":
                return "DEFECT_FOUND"
            time.sleep(0.4)
            m = scroll_map(f"raceB-r{rnd} readback", C)
            if m is None:
                return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
            torn = 0
            for i in IDS:
                if i not in m:
                    continue
                pl, okp = pay_dict(m[i])
                if not okp:
                    DEFECTS.append(f"(raceB-r{rnd}) point {i} payload is not "
                                   f"an object — Type4_StateLogicViolation")
                    continue
                if pl != {} and pl != ORIG[i]:
                    torn += 1
                    DEFECTS.append(f"(raceB-r{rnd}) point {i} payload {pl!r} "
                                   f"is a TORN state — legal serial outcomes "
                                   f"are only {{}} or {ORIG[i]!r} — "
                                   f"Type4_StateLogicViolation")
            check_ids_vectors(f"raceB-r{rnd}", m)
            c_b = exact_count(f"raceB-r{rnd} count", C)
            if c_b is None:
                return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
            if c_b != N:
                DEFECTS.append(f"(raceB-r{rnd}) exact count {c_b} != {N} — "
                               f"Type4_StateLogicViolation")
            if torn == 0:
                empt = sum(1 for i in IDS if i in m
                           and len(pay_dict(m[i])[0]) == 0)
                print(f"[raceB-r{rnd}] OK: no torn payloads "
                      f"({empt} cleared / {N - empt} overwritten serializations)")

        # ---- (Convergence close) ----
        do_clear(C, IDS, "final-clear")
        st = drain_op_errors()
        if st == "abort":
            return "SCRIPT_ERROR"
        if st == "defect":
            return "DEFECT_FOUND"
        time.sleep(0.5)
        fin = scroll_map("final readback", C)
        if fin is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        for i in IDS:
            if i not in fin:
                continue
            pl, _ = pay_dict(fin[i])
            if len(pl) != 0:
                DEFECTS.append(f"(final) point {i} still carries payload keys "
                               f"{sorted(pl.keys())} after the final "
                               f"deterministic clear — no convergence — "
                               f"Type4_StateLogicViolation")
        c_f = exact_count("final count", C)
        if c_f is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if c_f != N:
            DEFECTS.append(f"(final) exact count {c_f} != {N} — "
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
