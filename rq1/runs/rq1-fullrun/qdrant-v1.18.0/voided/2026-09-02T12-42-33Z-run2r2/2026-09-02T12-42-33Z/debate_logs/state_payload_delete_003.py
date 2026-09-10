#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_delete_003
# strategy: concurrent
# endpoint: payload+delete
# constraint_ids: qdrant_state_payload_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 Concurrency State Blindness
"""
Attack: Strategy 4 (concurrent operations) against
  qdrant_state_payload_delete_001: "only the listed payload keys are
  removed; unlisted keys persist". Two races on a 20-point collection
  where every point carries the 3-key payload {"ka":i,"kb":"x<i>",
  "kc":"keep"} (all ops wait=true):
  (Race A overlapping-key deletes) threads concurrently delete key
      groups whose UNION is {"ka","kb"} over the SAME 20 points
      (with PARTS>2 the extra lanes repeat an already-covered key —
      concurrent identical deletes). After the join, EVERY point must
      carry exactly {"kc":"keep"}: a point still holding "ka"/"kb"
      means one concurrent key-delete was silently lost (lost update —
      Type4); a point that lost "kc" means a delete over-reached its
      listed keys (Type4); exact count must stay 20 (key deletion is
      not point deletion).
  (Race B key-delete vs set-payload, ROUNDS rounds) each round first
      presets the uniform payload {"ka":0,"kb":"x0","kc":"keep"} on
      all 20 points via payload+set, then one thread issues a delete
      of ["ka"] on all points while another concurrently payload+sets
      {"ka":0,"kb":"x0"} again. Legal serial outcomes per point are
      only: {"kb":"x0","kc":"keep"} (delete applied last) or exactly
      {"ka":0,"kb":"x0","kc":"keep"} (set applied last — set merges
      over survivors). ANY other key set or value (missing "kc",
      partial merge, unknown keys, mutated values) = a torn write the
      storage layer must never expose (Type4).
  (Convergence close) one final deterministic delete ["ka"] -> every
      point exactly {"kb":"x0","kc":"keep"}: the state machine must
      still converge after the races.
  Vectors are compared readback-vs-baseline-readback (R27 lesson:
  Cosine L2-normalizes at upsert by-design) — key deletion and set
  must never touch vectors.
  Op-level errors: 0 = transport (liveness re-check via /healthz);
  5xx with service alive = Type3_RuntimeFailure; 4xx on these plainly
  valid ops = Type4 (valid op rejected under concurrency).
  Thread scale from TESTVDB_CONCURRENT_THREADS (default 10, clamped to
  2..4 delete lanes for Race A).
  [chunk_payload+delete coverage: concurrent x
   qdrant_state_payload_delete_001 (overlapping concurrent key-deletes
   + delete-vs-set torn-state oracle)]
Oracle: after Race A all 20 payloads are exactly {"kc":"keep"} and
  count == 20; after every Race B round each payload is exactly
  {"kb":"x0","kc":"keep"} or {"ka":0,"kb":"x0","kc":"keep"} — anything
  else = Type4_StateLogicViolation torn state; no op returns 0/4xx/5xx
  (5xx judged Type3 only when /healthz is alive); after the final
  delete all 20 payloads are exactly {"kb":"x0","kc":"keep"}; vectors
  equal the baseline readback vectors (<=1e-6) throughout.
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

# payload+delete / payload+set are not in the runtime PATHS whitelist —
# register VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "payload+delete", "method": "POST",
#    "url": "/collections/{collection_name}/points/payload/delete"}
#   {"path": "payload+set", "method": "POST",
#    "url": "/collections/{collection_name}/points/payload"}
rt.PATHS["payload_delete"] = "/collections/{collection_name}/points/payload/delete"
rt.PATHS["payload_set"] = "/collections/{collection_name}/points/payload"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'payload' in k]}")
if (rt.PATHS.get("payload_delete") != "/collections/{collection_name}/points/payload/delete"
        or rt.PATHS.get("payload_set") != "/collections/{collection_name}/points/payload"):
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
ORIG = {i: {"ka": i, "kb": f"x{i}", "kc": "keep"} for i in IDS}
# Race A deletes these key groups over ALL points; PARTS>2 repeats a key
LANE_KEYS = [["ka"], ["kb"], ["ka"], ["kb"]][:PARTS]
# Race B uniform preset and the only two legal post-race payloads per point
PRESET_SET = {"ka": 0, "kb": "x0"}
RACE_B_LEGAL = [{"kb": "x0", "kc": "keep"},                      # delete last
                {"ka": 0, "kb": "x0", "kc": "keep"}]             # set last

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


def check_ids_vectors(tag, m, basevec):
    if set(m.keys()) != set(IDS):
        DEFECTS.append(f"({tag}) point id set {sorted(m.keys())} != 0..{N-1} "
                       f"— key-delete races must not delete points — "
                       f"Type4_StateLogicViolation")
    for i in IDS:
        if i not in m:
            continue
        _, okp = pay_dict(m[i])
        if not okp:
            DEFECTS.append(f"({tag}) point {i} payload is not an object — "
                           f"Type4_StateLogicViolation")
        if not vec_eq(vec_of(m[i]), basevec[i]):
            DEFECTS.append(f"({tag}) point {i} vector changed during payload "
                           f"races — Type4_StateLogicViolation")


def do_delete_keys(coll, keys, tag):
    s, raw = safe_request("POST", "payload_delete",
                          path_params={"collection_name": coll},
                          body={"keys": keys, "points": IDS},
                          query_params={"wait": "true"})
    print(f"[{tag} delete keys={keys}] status={s} raw={str(raw)[:160]}")
    if s != 200:
        OP_ERRORS.append((tag, s, raw))


def do_set_payload(coll, tag):
    s, raw = safe_request("POST", "payload_set",
                          path_params={"collection_name": coll},
                          body={"points": IDS, "payload": PRESET_SET},
                          query_params={"wait": "true"})
    print(f"[{tag} set {PRESET_SET}] status={s} raw={str(raw)[:160]}")
    if s != 200:
        OP_ERRORS.append((tag, s, raw))


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spd3_" + TS + "_"
    C = PFX + "col"

    try:
        # ---- (A setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [float(i) + 1.0, 1.0, 2.0, 3.0],
                "payload": ORIG[i]} for i in IDS]
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[A upsert {N}] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"

        base = scroll_map("A baseline", C)
        if base is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        BASEVEC = {i: vec_of(base[i]) for i in IDS}
        if set(base.keys()) != set(IDS) or any(v is None for v in BASEVEC.values()):
            print("SETUP_ERROR: baseline readback incomplete")
            return "SCRIPT_ERROR"

        # ---- (Race A overlapping-key deletes over the same points) ----
        print(f"[Race A] {PARTS} lanes, key groups {LANE_KEYS} "
              f"(union covers ka+kb on all {N} points)")
        ths = []
        for li, keys in enumerate(LANE_KEYS):
            t = threading.Thread(target=do_delete_keys,
                                 args=(C, keys, f"raceA-lane{li}"))
            ths.append(t)
            t.start()
        for t in ths:
            t.join()
        st = drain_op_errors()
        if st == "abort":
            return "SCRIPT_ERROR"
        if st == "defect":
            return "DEFECT_FOUND"
        time.sleep(0.5)
        ma = scroll_map("raceA readback", C)
        if ma is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        check_ids_vectors("raceA", ma, BASEVEC)
        for i in IDS:
            if i not in ma:
                continue
            pl, _ = pay_dict(ma[i])
            if pl != {"kc": "keep"}:
                DEFECTS.append(f"(raceA) point {i} payload {pl!r} != exactly "
                               f"{{'kc':'keep'}} — union-deleted ka/kb must be "
                               f"gone AND unlisted kc must persist (lost "
                               f"update or over-delete) — "
                               f"Type4_StateLogicViolation")
        ca = exact_count("raceA count", C)
        if ca is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if ca != N:
            DEFECTS.append(f"(raceA) exact count {ca} != {N} — "
                           f"Type4_StateLogicViolation")

        # restore full 3-key payload for Race B (uniform preset per round)
        do_set_payload(C, "restore-preset")
        st = drain_op_errors()
        if st == "abort":
            return "SCRIPT_ERROR"
        if st == "defect":
            return "DEFECT_FOUND"
        time.sleep(0.3)
        rb_base = scroll_map("restore readback", C)
        if rb_base is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        BASEVEC = {i: vec_of(rb_base[i]) for i in IDS}
        for i in IDS:
            pl, _ = pay_dict(rb_base[i])
            if pl != RACE_B_LEGAL[1]:
                DEFECTS.append(f"(restore) point {i} payload {pl!r} != preset "
                               f"{RACE_B_LEGAL[1]!r} — "
                               f"Type4_StateLogicViolation")

        # ---- (Race B key-delete vs set-payload, ROUNDS rounds) ----
        for rd in range(ROUNDS):
            tb = threading.Thread(target=do_delete_keys,
                                  args=(C, ["ka"], f"raceB-rd{rd}-del"))
            ts_ = threading.Thread(target=do_set_payload,
                                   args=(C, f"raceB-rd{rd}-set"))
            tb.start()
            ts_.start()
            tb.join()
            ts_.join()
            st = drain_op_errors()
            if st == "abort":
                return "SCRIPT_ERROR"
            if st == "defect":
                return "DEFECT_FOUND"
            time.sleep(0.4)
            mb = scroll_map(f"raceB-rd{rd} readback", C)
            if mb is None:
                return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
            check_ids_vectors(f"raceB-rd{rd}", mb, BASEVEC)
            for i in IDS:
                if i not in mb:
                    continue
                pl, _ = pay_dict(mb[i])
                if pl not in RACE_B_LEGAL:
                    DEFECTS.append(f"(raceB rd{rd}) point {i} torn payload "
                                   f"{pl!r} — legal serial outcomes are only "
                                   f"{RACE_B_LEGAL[0]!r} (delete last) or "
                                   f"{RACE_B_LEGAL[1]!r} (set last) — "
                                   f"Type4_StateLogicViolation")
            cb = exact_count(f"raceB-rd{rd} count", C)
            if cb is None:
                return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
            if cb != N:
                DEFECTS.append(f"(raceB rd{rd}) exact count {cb} != {N} — "
                               f"Type4_StateLogicViolation")

        # ---- (Convergence close) final deterministic delete ["ka"] ----
        do_delete_keys(C, ["ka"], "final")
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
            if pl != RACE_B_LEGAL[0]:
                DEFECTS.append(f"(final) point {i} payload {pl!r} != exactly "
                               f"{RACE_B_LEGAL[0]!r} after the final "
                               f"deterministic delete — no convergence — "
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
