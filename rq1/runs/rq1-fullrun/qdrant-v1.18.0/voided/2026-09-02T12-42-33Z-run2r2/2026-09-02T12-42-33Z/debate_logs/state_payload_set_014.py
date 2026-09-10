#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_set_014
# strategy: count_consistency
# endpoint: payload+set
# constraint_ids: qdrant_state_payload_set_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/set-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 variant (filter-targeted merge + state scope) against
  qdrant_state_payload_set_001: "points OR filter must identify the
  targets". The filter half of the either-or selector is exercised on a
  6-point collection with payload {"grp":"A"/"B","score":i,"note":...}
  (odd ids 1,3,5 = "A"; even ids 2,4,6 = "B"). Filter syntax is
  contract-derived (data_types: Filter = {should?, min_should?, must?,
  must_not?}; Condition = FieldCondition {key, match}; Match =
  {value: string|int64|bool}):
  (A setup) baseline scroll snapshots BASEVEC (R27 lesson: on Cosine
      collections the stored vector is L2-normalized by-design — later
      vector comparisons are readback-vs-baseline-readback only).
  (F1 must-filter merge) POST payload+set {"payload":{"seen":true},
      "filter":{"must":[{"key":"grp","match":{"value":"A"}}]}}
      wait=true -> 200; readback: "A" points get "seen" MERGED onto
      their full original payload (set = merge keys — unlisted keys
      survive); "B" points byte-exact original (any "B" point gaining
      "seen" = filter over-reach).
  (F2 zero-match filter, both-branch state-only) the same set shape
      with {"must":[{"key":"grp","match":{"value":"ZZZ"}}]} matches NO
      point. Whether an empty match is 200-no-op or 4xx is NOT pinned
      by the chunk assertions — only the STATE face is adjudicated
      (both-branch safe): NO point may gain the "nope" key afterwards.
  (F3 must_not-filter merge) {"payload":{"neg":true},"filter":
      {"must_not":[{"key":"grp","match":{"value":"A"}}]}} wait=true ->
      200; readback: "B" points get "neg" merged; "A" points still
      exactly their F1 state (no regression).
  (G invariants) id set stays 1..6, all vectors equal BASEVEC
      (payload-scoped), exact count stays 6.
  [chunk_payload+set coverage: count_consistency x
   qdrant_state_payload_set_001 (filter-identified targets: must +
   must_not + zero-match state-safety)]
Oracle: F1 -> 200 and A-points (1,3,5) payload = original + "seen":
  true merged while B-points (2,4,6) byte-exact original (B gaining
  "seen" = filter over-reach — Type4_StateLogicViolation); F2 -> any
  status, but NO point gains "nope" (a point gaining a key via a
  zero-match filter = Type4_StateLogicViolation); F3 -> 200 and
  B-points get "neg": true merged while A-points keep their exact F1
  state (Type4 on drift); id set 1..6, vectors equal baseline readback
  (<=1e-6), exact count 6 throughout; 5xx only counts when /healthz
  confirms liveness (Type3_RuntimeFailure).
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

DEFECTS = []


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


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


def scroll_map(tag, coll, limit=50):
    """scroll with_payload+with_vector -> {id: point} or None on abort."""
    s, raw = safe_request("POST", "scroll", path_params={"name": coll},
                          body={"limit": limit, "with_payload": True,
                                "with_vector": True})
    print(f"[{tag} scroll] status={s} raw={str(raw)[:160]}")
    if s == 0:
        liveness(tag)
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) scroll returned {s} with service "
                           f"alive — Type3_RuntimeFailure — raw={str(raw)[:150]}")
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


def check_invariants(tag, m, basevec, ids, count):
    if set(m.keys()) != set(ids):
        DEFECTS.append(f"({tag}) point id set {sorted(m.keys())} != "
                       f"{sorted(ids)} — filter-targeted set must not delete "
                       f"points — Type4_StateLogicViolation")
    for i in ids:
        if i not in m:
            continue
        _, okp = pay_dict(m[i])
        if not okp:
            DEFECTS.append(f"({tag}) point {i} payload is not an object — "
                           f"Type4_StateLogicViolation")
        if not vec_eq(vec_of(m[i]), basevec[i]):
            DEFECTS.append(f"({tag}) point {i} vector changed after "
                           f"set-payload — set is payload-scoped — "
                           f"Type4_StateLogicViolation")
    if count != len(ids):
        DEFECTS.append(f"({tag}) exact count {count} != {len(ids)} — "
                       f"Type4_StateLogicViolation")


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sps14_" + TS + "_"
    C = PFX + "col"

    IDS = list(range(1, 7))
    GRP = {i: ("A" if i % 2 == 1 else "B") for i in IDS}
    ORIGINAL = {i: {"grp": GRP[i], "score": i, "note": f"n{i}"} for i in IDS}

    def f_must(grp_value):
        # contract data_types: Filter{must} -> Condition FieldCondition{key,
        # match} -> Match{value}
        return {"must": [{"key": "grp", "match": {"value": grp_value}}]}

    def f_must_not(grp_value):
        return {"must_not": [{"key": "grp", "match": {"value": grp_value}}]}

    try:
        # ---- (A setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [float(i), 1.0, 2.0, 3.0],
                "payload": ORIGINAL[i]} for i in IDS]
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[A upsert 6] status={u_s} raw={u_raw[:150]}")
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
        cnt0 = exact_count("A count", C)
        if cnt0 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- (F1 must-filter merge on grp=A) ----
        f1_body = {"payload": {"seen": True}, "filter": f_must("A")}
        f1_s, f1_raw = safe_request("POST", "payload_set",
                                    path_params={"collection_name": C},
                                    body=f1_body,
                                    query_params={"wait": "true"})
        print(f"[F1 set seen via must(grp=A)] status={f1_s} raw={f1_raw[:200]}")
        if f1_s == 0:
            liveness("F1")
            return "SCRIPT_ERROR"
        if 500 <= f1_s <= 599:
            if liveness("F1"):
                DEFECTS.append(f"(F1) filter-set returned {f1_s} with service "
                               f"alive — Type3_RuntimeFailure — "
                               f"raw={f1_raw[:150]}")
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        if f1_s != 200:
            print(f"SETUP_ERROR: filter-set returned {f1_s} — cannot judge "
                  f"filter targeting (status faces adjudicated in 015)")
            return "SCRIPT_ERROR"
        time.sleep(0.5)
        m1 = scroll_map("F1 readback", C)
        c1 = exact_count("F1 count", C)
        if m1 is None or c1 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        check_invariants("F1", m1, BASEVEC, IDS, c1)
        F1_STATE = {}
        for i in IDS:
            if i not in m1:
                continue
            pl, okp = pay_dict(m1[i])
            if not okp:
                continue
            if GRP[i] == "A":
                expect = dict(ORIGINAL[i])
                expect["seen"] = True
                F1_STATE[i] = expect
                if pl != expect:
                    DEFECTS.append(f"(F1) A-point {i} payload {pl!r} != MERGED "
                                   f"expectation {expect!r} — filter-targeted "
                                   f"set must merge keys (qdrant_state_"
                                   f"payload_set_001) — Type4_StateLogicViolation")
            else:
                F1_STATE[i] = ORIGINAL[i]
                if pl != ORIGINAL[i]:
                    DEFECTS.append(f"(F1) NON-matching B-point {i} payload "
                                   f"changed by must(grp=A) filter set: "
                                   f"{pl!r} != {ORIGINAL[i]!r} — filter "
                                   f"over-reach — Type4_StateLogicViolation")
        if not DEFECTS:
            print("[F1] OK: must(grp=A) merged 'seen' onto exactly the "
                  "3 A-points; 3 B-points byte-exact original")

        # ---- (F2 zero-match filter, both-branch state-only) ----
        f2_body = {"payload": {"nope": 1}, "filter": f_must("ZZZ")}
        f2_s, f2_raw = safe_request("POST", "payload_set",
                                    path_params={"collection_name": C},
                                    body=f2_body,
                                    query_params={"wait": "true"})
        print(f"[F2 set nope via must(grp=ZZZ) zero-match] status={f2_s} "
              f"raw={f2_raw[:200]}")
        if f2_s == 0:
            liveness("F2")
            return "SCRIPT_ERROR"
        if 500 <= f2_s <= 599:
            if liveness("F2"):
                DEFECTS.append(f"(F2) zero-match filter-set returned {f2_s} "
                               f"with service alive — Type3_RuntimeFailure — "
                               f"raw={f2_raw[:150]}")
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        # both-branch: 200-no-op OR 4xx-reject are both legal; only the
        # state face is adjudicated
        time.sleep(0.5)
        m2 = scroll_map("F2 readback", C)
        if m2 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        for i in IDS:
            if i not in m2:
                continue
            pl, okp = pay_dict(m2[i])
            if not okp:
                DEFECTS.append(f"(F2) point {i} payload is not an object — "
                               f"Type4_StateLogicViolation")
                continue
            if "nope" in pl:
                DEFECTS.append(f"(F2) point {i} GAINED key 'nope' via a "
                               f"zero-match filter (grp=ZZZ matches nothing) "
                               f"— payload={pl!r} — filter must identify "
                               f"targets precisely — "
                               f"Type4_StateLogicViolation")
            elif pl != F1_STATE.get(i):
                DEFECTS.append(f"(F2) point {i} payload drifted from F1 state "
                               f"on a zero-match filter set: {pl!r} != "
                               f"{F1_STATE.get(i)!r} — "
                               f"Type4_StateLogicViolation")
        if not DEFECTS:
            print(f"[F2] OK: zero-match filter changed no point state "
                  f"(status {f2_s} accepted as legal both-branch)")

        # ---- (F3 must_not-filter merge on grp!=A i.e. B) ----
        f3_body = {"payload": {"neg": True},
                   "filter": f_must_not("A")}
        f3_s, f3_raw = safe_request("POST", "payload_set",
                                    path_params={"collection_name": C},
                                    body=f3_body,
                                    query_params={"wait": "true"})
        print(f"[F3 set neg via must_not(grp=A)] status={f3_s} "
              f"raw={f3_raw[:200]}")
        if f3_s == 0:
            liveness("F3")
            return "SCRIPT_ERROR"
        if 500 <= f3_s <= 599:
            if liveness("F3"):
                DEFECTS.append(f"(F3) must_not filter-set returned {f3_s} "
                               f"with service alive — Type3_RuntimeFailure — "
                               f"raw={f3_raw[:150]}")
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        if f3_s != 200:
            print(f"SETUP_ERROR: must_not filter-set returned {f3_s} — "
                  f"cannot judge must_not targeting")
            return "SCRIPT_ERROR"
        time.sleep(0.5)
        m3 = scroll_map("F3 readback", C)
        c3 = exact_count("F3 count", C)
        if m3 is None or c3 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        check_invariants("F3", m3, BASEVEC, IDS, c3)
        for i in IDS:
            if i not in m3:
                continue
            pl, okp = pay_dict(m3[i])
            if not okp:
                continue
            if GRP[i] == "B":
                expect = dict(ORIGINAL[i])
                expect["neg"] = True
                if pl != expect:
                    DEFECTS.append(f"(F3) B-point {i} payload {pl!r} != MERGED "
                                   f"expectation {expect!r} — must_not(grp=A) "
                                   f"must merge onto exactly the B-points — "
                                   f"Type4_StateLogicViolation")
            else:
                if pl != F1_STATE.get(i):
                    DEFECTS.append(f"(F3) A-point {i} regressed from its F1 "
                                   f"state during a must_not(grp=A) set: "
                                   f"{pl!r} != {F1_STATE.get(i)!r} — "
                                   f"Type4_StateLogicViolation")
        if not DEFECTS:
            print("[F3] OK: must_not(grp=A) merged 'neg' onto exactly the "
                  "3 B-points; A-points kept their F1 state")

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
