#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_percol_payload_overwrite_007
# strategy: count_consistency
# endpoint: per_collection
# constraint_ids: qdrant_inv_payload_overwrite_readback_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
"""
Attack: count_consistency (payload-readback variant — the state invariant
  is a readback promise, not a numeric count) x
  qdrant_inv_payload_overwrite_readback_001 "after a payload overwrite
  the stored payload equals exactly the provided payload": payload
  overwrite is REPLACE semantics (the complement of payload+set's MERGE
  semantics covered in the R30 chunk) — "keys absent from the request
  are removed". Sequence: (A) 3 points with seed payloads
  {"a": i, "keep": "x", "old": true}; baseline scroll snapshot (R27
  lesson: on Cosine collections the stored vector is L2-normalized
  by-design — vector oracles compare readback-vs-baseline-readback
  only). (T1 replace face) PUT points/payload overwrite points [1,2]
  with B {"b": "new", "num": 7, "flag": false} wait=true -> 200;
  readback: 1 and 2 carry EXACTLY B with strict type identity — the
  seed keys a/keep/old must be GONE — while point 3 keeps its seed
  payload byte-exact (the selector must be surgical). (T2 empty
  closure face) overwrite point [3] with the EMPTY payload {} — the
  boundary closure of "exactly the provided payload" (G4): readback
  must show ZERO keys ({} or null — both mean no keys); points 1,2
  must still carry exactly B. (T3 typed-rewrite face) overwrite ALL
  three points with C {"c": [1, 2], "geo": {"lon": 13.405, "lat":
  52.52}} -> readback deep-equals C on all three (typed literals must
  survive the replace with strict identity — int array stays
  int-elemented, geo lon/lat untransposed). Throughout: exact count
  stays 3 (a payload write must not create or delete points) and the
  vectors equal the baseline readback (payload overwrite is
  payload-scoped).
  [chunk_per_collection coverage: count_consistency (payload-readback
  variant) x qdrant_inv_payload_overwrite_readback_001 (replace
  semantics + empty closure + targeted selector + typed rewrite)]
Oracle: T1 -> 200 and readback of points 1,2 deep-equals B with
  STRICT type identity and NO seed keys left (a surviving a/keep/old
  key = merge-instead-of-replace = Type4_StateLogicViolation); point 3
  byte-equal to its seed payload (cross-point drift = Type4); T2 ->
  200 and point 3 reads back ZERO payload keys while 1,2 still equal
  B exactly; T3 -> 200 and all three points deep-equal C type-strict
  (int array elements stay ints; lon=13.405/lat=52.52 untransposed);
  exact count == 3 at every checkpoint; vectors equal the baseline
  readback (tolerance 1e-6); 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> liveness re-check first.
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

# payload+overwrite is not in the runtime PATHS whitelist — register
# VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "payload+overwrite", "method": "PUT",
#    "url": "/collections/{collection_name}/points/payload"}
rt.PATHS["payload_overwrite"] = "/collections/{collection_name}/points/payload"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k == 'payload_overwrite']}")

DEFECTS = []
ABORT = [False]


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
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


def diff_at(a, b, path="payload"):
    if isinstance(a, bool) or isinstance(b, bool):
        if not (isinstance(a, bool) and isinstance(b, bool) and a == b):
            return f"{path}: {type(a).__name__}={a!r} vs {type(b).__name__}={b!r}"
        return None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not (type(a) is type(b) and a == b):
            return f"{path}: {type(a).__name__}={a!r} vs {type(b).__name__}={b!r}"
        return None
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__}={a!r} vs {type(b).__name__}={b!r}"
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            only_a = set(a.keys()) - set(b.keys())
            only_b = set(b.keys()) - set(a.keys())
            return (f"{path}: keys differ (residue={sorted(only_a)}, "
                    f"missing={sorted(only_b)})")
        for k in a:
            d = diff_at(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: len {len(a)} vs {len(b)}"
        for idx, (x, y) in enumerate(zip(a, b)):
            d = diff_at(x, y, f"{path}[{idx}]")
            if d:
                return d
        return None
    if a != b:
        return f"{path}: {a!r} vs {b!r}"
    return None


def vec_eq(a, b, tol=1e-6):
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
        return False
    return all(isinstance(x, (int, float)) and isinstance(y, (int, float))
               and abs(x - y) <= tol for x, y in zip(a, b))


def scroll_map(tag, coll):
    """scroll with_payload+with_vector -> {id: point} or None on abort."""
    s, raw = safe_request("POST", "scroll", path_params={"name": coll},
                          body={"limit": 10, "with_payload": True,
                                "with_vector": True})
    print(f"[{tag} scroll] status={s} raw={str(raw)[:160]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) scroll returned {s} with service "
                           f"alive — Type3_RuntimeFailure")
        else:
            ABORT[0] = True
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
        if not liveness(tag):
            ABORT[0] = True
        else:
            DEFECTS.append(f"({tag}) count transport failure with service "
                           f"alive — Type3_RuntimeFailure")
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) count returned {s} with service alive "
                           f"— Type3_RuntimeFailure")
        else:
            ABORT[0] = True
        return None
    if s != 200:
        return None
    try:
        res = json.loads(raw).get("result")
        cnt = res.get("count") if isinstance(res, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        cnt = None
    return cnt if isinstance(cnt, int) and not isinstance(cnt, bool) else None


def overwrite(tag, coll, payload, ids):
    s, raw = safe_request("PUT", "payload_overwrite",
                          path_params={"collection_name": coll},
                          body={"payload": payload, "points": ids},
                          query_params={"wait": "true"})
    print(f"[{tag} overwrite ids={ids}] status={s} raw={str(raw)[:180]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        else:
            DEFECTS.append(f"({tag}) overwrite transport failure with "
                           f"service alive — Type3_RuntimeFailure")
        return False
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) overwrite returned {s} with service "
                           f"alive — Type3_RuntimeFailure")
        else:
            ABORT[0] = True
        return False
    if s != 200:
        print(f"SETUP_ERROR: {tag} overwrite returned {s} (plainly valid "
              f"replace must be accepted)")
        return False
    return True


def pay_of(m, i):
    p = m.get(i)
    if p is None:
        return None
    pl = p.get("payload")
    if pl is None:
        return {}
    return pl if isinstance(pl, dict) else {}


def check_common(tag, coll, m, basevec):
    """count==3 and vectors==baseline for all 3 points."""
    cnt = exact_count(tag, coll)
    if cnt is not None and cnt != 3:
        DEFECTS.append(f"({tag}) exact count {cnt} != 3 — a payload "
                       f"overwrite must not create/delete points — "
                       f"Type4_StateLogicViolation")
    for i in (1, 2, 3):
        p = m.get(i)
        if p is None:
            DEFECTS.append(f"({tag}) point {i} disappeared after a payload "
                           f"overwrite — Type4_StateLogicViolation")
            continue
        v = p.get("vector")
        if not vec_eq(v if isinstance(v, list) else None, basevec):
            DEFECTS.append(f"({tag}) point {i} vector changed after a "
                           f"payload-scoped overwrite — "
                           f"Type4_StateLogicViolation")


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spow7_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    B = {"b": "new", "num": 7, "flag": False}
    C_PL = {"c": [1, 2], "geo": {"lon": 13.405, "lat": 52.52}}

    def seed(i):
        return {"a": i, "keep": "x", "old": True}

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [float(i), 1.0, 0.5, 0.25],
                "payload": seed(i)} for i in (1, 2, 3)]
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C}, body={"points": pts},
                              query_params={"wait": "true"})
        print(f"[A upsert 3] status={s} raw={raw[:150]}")
        if s != 200:
            print("SETUP_ERROR: A upsert failed")
            return "SCRIPT_ERROR"
        m = scroll_map("A baseline", C)
        if m is None or set(m.keys()) != {1, 2, 3}:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        bv = m[1].get("vector")
        BASEVEC = bv if isinstance(bv, list) else None
        if BASEVEC is None:
            print("SETUP_ERROR: baseline vector missing")
            return "SCRIPT_ERROR"
        print(f"[A baseline] BASEVEC={BASEVEC}")

        # ---- (T1 replace face on points 1,2) ----
        if not overwrite("T1", C, B, [1, 2]):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        time.sleep(0.3)
        m = scroll_map("T1 readback", C)
        if m is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        for i in (1, 2):
            pl = pay_of(m, i)
            if pl is None:
                DEFECTS.append(f"(T1) point {i} lost after overwrite — "
                               f"Type4_StateLogicViolation")
                continue
            if not type_strict_eq(pl, B):
                d = diff_at(pl, B)
                DEFECTS.append(f"(T1) point {i} payload after overwrite is "
                               f"{pl!r} != exactly {B!r} (first divergence: "
                               f"{d}) — replace semantics: keys absent from "
                               f"the request MUST be removed — "
                               f"Type4_StateLogicViolation")
        pl3 = pay_of(m, 3)
        if pl3 is None or not type_strict_eq(pl3, seed(3)):
            DEFECTS.append(f"(T1) untouched point 3 payload drifted: "
                           f"{pl3!r} != {seed(3)!r} — the overwrite selector "
                           f"must be surgical — Type4_StateLogicViolation")
        else:
            print("[T1] OK: 1,2 replaced exactly; 3 untouched")
        check_common("T1", C, m, BASEVEC)

        # ---- (T2 empty-payload closure on point 3) ----
        if not overwrite("T2", C, {}, [3]):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        time.sleep(0.3)
        m = scroll_map("T2 readback", C)
        if m is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        raw3 = (m.get(3) or {}).get("payload", "MISSING")
        pl3 = pay_of(m, 3)
        if pl3 is None:
            DEFECTS.append("(T2) point 3 lost after empty overwrite — "
                           "Type4_StateLogicViolation")
        else:
            if len(pl3) != 0:
                DEFECTS.append(f"(T2) point 3 payload after overwrite with "
                               f"{{}} is {raw3!r} — 'exactly the provided "
                               f"payload' with zero keys must leave zero "
                               f"keys — Type4_StateLogicViolation")
            else:
                print("[T2] OK: point 3 payload is now empty (zero keys)")
        for i in (1, 2):
            pl = pay_of(m, i)
            if pl is None or not type_strict_eq(pl, B):
                DEFECTS.append(f"(T2) point {i} drifted from B during "
                               f"point-3's empty overwrite: {pl!r} — "
                               f"Type4_StateLogicViolation")
        check_common("T2", C, m, BASEVEC)

        # ---- (T3 typed rewrite on all three) ----
        if not overwrite("T3", C, C_PL, [1, 2, 3]):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        time.sleep(0.3)
        m = scroll_map("T3 readback", C)
        if m is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        for i in (1, 2, 3):
            pl = pay_of(m, i)
            if pl is None:
                DEFECTS.append(f"(T3) point {i} lost after typed overwrite — "
                               f"Type4_StateLogicViolation")
                continue
            if not type_strict_eq(pl, C_PL):
                d = diff_at(pl, C_PL)
                DEFECTS.append(f"(T3) point {i} payload {pl!r} != {C_PL!r} "
                               f"(first divergence: {d}) — typed literals "
                               f"must survive the replace with strict "
                               f"identity — Type4_StateLogicViolation")
        geo = pay_of(m, 1).get("geo")
        if isinstance(geo, dict) and geo.get("lon") == 52.52:
            DEFECTS.append("(T3) geo lon/lat TRANSPOSED on readback "
                           f"(lon={geo.get('lon')!r}) — "
                           f"Type4_StateLogicViolation")
        else:
            print("[T3] OK: all three points carry exactly C type-strict")
        check_common("T3", C, m, BASEVEC)

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
