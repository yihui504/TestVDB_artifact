#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_overwrite_003
# strategy: concurrent
# endpoint: payload+overwrite
# constraint_ids: qdrant_state_payload_overwrite_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/overwrite-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 Concurrency State Blindness
"""
Attack: Strategy 4 (concurrent operations) against
  qdrant_state_payload_overwrite_001: "overwrite replaces the ENTIRE
  payload of the targeted points (set semantics: keys missing from the
  new payload are removed)". Under concurrency the full-replacement
  promise is atomicity-carrying: every concurrent overwrite must land
  as ONE indivisible payload object, never an interleaving of two.
  Two races on a 20-point collection where every point carries the
  3-key payload {"ka":i,"kb":"x<i>","kc":"z"} (all ops wait=true):
  (Race A full-replacement races) PARTS lanes concurrently PUT
      payload+overwrite with DISTINCT payloads P_j =
      {"ka":100+j,"kb":"lane<j>"} over the SAME 20 points. After the
      join every point payload must be EXACTLY one P_j (last-writer
      wins per point is legal). A payload mixing content from
      different lanes (e.g. {"ka":100,"kb":"lane1"}), carrying any
      surviving original key ("kc"), or holding anything outside
      {P_0..P_{PARTS-1}} = a TORN WRITE — overwrite degraded to
      key-wise merge or non-atomic partial application under
      concurrency — Type4_StateLogicViolation.
  (Race B overwrite vs set-payload, ROUNDS rounds) each round first
      presets the uniform payload {"ka":0,"kb":"x0","kc":"keep"} via a
      deterministic wait=true overwrite, then concurrently: T1
      overwrites ALL points with {"kb":"x0"}; T2 sets {"ka":0} on ALL
      points. The only legal serial outcomes per point are
      {"ka":0,"kb":"x0"} (overwrite then set), {"kb":"x0"} (set then
      overwrite — replacement removes the set key), or the preset
      {"ka":0,"kb":"x0","kc":"keep"} (set collapses into preset /
      neither visibly applied). Anything else = torn state (Type4).
      The mutation point is the strongest one for this invariant:
      replacement must REMOVE keys under a concurrent writer that
      ADDS them — exactly where merge-implementation bugs surface.
  (Convergence close) a final deterministic overwrite {"done":1} must
      leave EVERY point exactly {"done":1} — no residue from any lane.
  Invariants after every race: point id set == 0..19; all vectors
  equal the baseline readback vectors (<=1e-6; R27 lesson — Cosine
  normalizes by-design, comparisons are readback-vs-baseline-readback
  only); exact count stays 20.
  [chunk_payload+overwrite coverage: concurrent x
   qdrant_state_payload_overwrite_001 (full-replacement atomicity
   under concurrent overwrites + overwrite/set race + convergence)]
Oracle: after PARTS concurrent wait=true full-payload overwrites (all lanes expect HTTP 200)
  every point payload is exactly one of the written payloads (no torn mix,
  no surviving pre-race key); after each overwrite-vs-set race round
  every point payload is one of the three legal serial outcomes; after
  the final deterministic overwrite every point is exactly
  {"done":1}; point ids, vectors and exact count 20 are unchanged
  throughout. A torn payload, a lost point, a vector change, or a
  count drift = Type4_StateLogicViolation; op 5xx only counts when
  /healthz confirms liveness (Type3_RuntimeFailure).
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

# payload+overwrite / payload+set are not in the runtime PATHS whitelist —
# register VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "payload+overwrite", "method": "PUT",
#    "url": "/collections/{collection_name}/points/payload"}
#   {"path": "payload+set", "method": "POST",
#    "url": "/collections/{collection_name}/points/payload"}
rt.PATHS["payload_overwrite"] = "/collections/{collection_name}/points/payload"
rt.PATHS["payload_set"] = "/collections/{collection_name}/points/payload"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'payload' in k]}")
if (rt.PATHS.get("payload_overwrite") != "/collections/{collection_name}/points/payload"
        or rt.PATHS.get("payload_set") != "/collections/{collection_name}/points/payload"):
    print("VERDICT: SCRIPT_ERROR - payload endpoint URL registration failed")
    sys.exit(2)

N = 20
ROUNDS = 3
try:
    _env_thr = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10") or 10)
except ValueError:
    _env_thr = 10
PARTS = max(2, min(4, _env_thr))
IDS = list(range(N))
ORIG = {i: {"ka": i, "kb": f"x{i}", "kc": "z"} for i in IDS}
# Race A lanes write these DISTINCT full payloads (100+j cannot collide
# with any original ka value 0..19)
LANE_PAY = [{"ka": 100 + j, "kb": f"lane{j}"} for j in range(PARTS)]
# Race B uniform preset + the only three legal post-race payloads
PRESET = {"ka": 0, "kb": "x0", "kc": "keep"}
RACE_B_OVERWRITE = {"kb": "x0"}
RACE_B_SET = {"ka": 0}
RACE_B_LEGAL = [{"ka": 0, "kb": "x0"},                       # overwrite then set
                {"kb": "x0"},                                # set then overwrite
                {"ka": 0, "kb": "x0", "kc": "keep"}]         # preset (set collapses)

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
                       f"— payload races must not delete points — "
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


def do_overwrite_all(coll, payload, tag):
    s, raw = safe_request("PUT", "payload_overwrite",
                          path_params={"collection_name": coll},
                          body={"payload": payload, "points": IDS},
                          query_params={"wait": "true"})
    print(f"[{tag} PUT overwrite {payload!r}] status={s} raw={str(raw)[:160]}")
    if s != 200:
        OP_ERRORS.append((tag, s, raw))


def do_set_all(coll, payload, tag):
    s, raw = safe_request("POST", "payload_set",
                          path_params={"collection_name": coll},
                          body={"payload": payload, "points": IDS},
                          query_params={"wait": "true"})
    print(f"[{tag} POST set {payload!r}] status={s} raw={str(raw)[:160]}")
    if s != 200:
        OP_ERRORS.append((tag, s, raw))


def race_invariants(tag, coll, legal, basevec):
    """Readback + payload-in-legal-set + ids/vectors/count. Returns map/None."""
    m = scroll_map(tag + " readback", coll)
    if m is None:
        return None
    check_ids_vectors(tag, m, basevec)
    bad = 0
    for i in IDS:
        if i not in m:
            continue
        pl, _ = pay_dict(m[i])
        if pl not in legal:
            bad += 1
            if bad <= 5:
                DEFECTS.append(f"({tag}) point {i} payload {pl!r} not in "
                               f"legal set {legal!r} — torn/interleaved write "
                               f"(overwrite must land as ONE indivisible "
                               f"payload object) — Type4_StateLogicViolation")
    if bad == 0:
        print(f"[{tag}] OK: all readback payloads inside the legal set")
    cnt = exact_count(tag + " count", coll)
    if cnt is None:
        return None
    if cnt != N:
        DEFECTS.append(f"({tag}) exact count {cnt} != {N} — "
                       f"Type4_StateLogicViolation")
    return m


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spo3_" + TS + "_"
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

        # ---- (Race A concurrent DISTINCT full-payload overwrites) ----
        print(f"[Race A] {PARTS} lanes, payloads {LANE_PAY} on all {N} points")
        ths = []
        for j, pay in enumerate(LANE_PAY):
            t = threading.Thread(target=do_overwrite_all,
                                 args=(C, pay, f"raceA-lane{j}"))
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
        if race_invariants("raceA", C, LANE_PAY, BASEVEC) is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- (Race B overwrite vs set-payload, ROUNDS rounds) ----
        for rd in range(ROUNDS):
            # deterministic uniform preset (barrier) + BASEVEC resync
            do_overwrite_all(C, PRESET, f"raceB-rd{rd}-preset")
            st = drain_op_errors()
            if st == "abort":
                return "SCRIPT_ERROR"
            if st == "defect":
                return "DEFECT_FOUND"
            time.sleep(0.3)
            pb = scroll_map(f"raceB-rd{rd}-preset readback", C)
            if pb is None:
                return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
            BASEVEC = {i: vec_of(pb[i]) for i in IDS if i in pb}
            if set(pb.keys()) != set(IDS):
                DEFECTS.append(f"(raceB rd{rd} preset) id set "
                               f"{sorted(pb.keys())} != 0..{N-1} — "
                               f"Type4_StateLogicViolation")
            for i in IDS:
                if i in pb:
                    pl, _ = pay_dict(pb[i])
                    if pl != PRESET:
                        DEFECTS.append(f"(raceB rd{rd} preset) point {i} "
                                       f"payload {pl!r} != {PRESET!r} — "
                                       f"Type4_StateLogicViolation")
            # the race: full replacement (removes kc/ka) vs merge (adds ka)
            tb = threading.Thread(target=do_overwrite_all,
                                  args=(C, RACE_B_OVERWRITE,
                                        f"raceB-rd{rd}-overwrite"))
            ts_ = threading.Thread(target=do_set_all,
                                   args=(C, RACE_B_SET,
                                         f"raceB-rd{rd}-set"))
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
            if race_invariants(f"raceB-rd{rd}", C, RACE_B_LEGAL,
                               BASEVEC) is None:
                return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- (Convergence close) final deterministic overwrite ----
        do_overwrite_all(C, {"done": 1}, "final")
        st = drain_op_errors()
        if st == "abort":
            return "SCRIPT_ERROR"
        if st == "defect":
            return "DEFECT_FOUND"
        time.sleep(0.5)
        if race_invariants("final", C, [{"done": 1}], BASEVEC) is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

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
