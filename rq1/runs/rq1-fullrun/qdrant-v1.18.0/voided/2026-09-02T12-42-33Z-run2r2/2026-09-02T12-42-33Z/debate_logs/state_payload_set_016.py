#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_set_016
# strategy: count_consistency
# endpoint: payload+set
# constraint_ids: qdrant_type_payload_set_001
# source_url: https://qdrant.tech/documentation/manage-data/payload/
# doc_version: current (site latest; no version archive)
"""
Attack: Strategy 1 variant (typed-literal round-trip + merge-state
  consistency) against qdrant_type_payload_set_001: "payload values
  with non-trivial literal syntax: geo values are objects {lon, lat}
  of doubles; datetime values are RFC 3339 strings; uuid values are
  uuid strings; arrays must be same-type". The contract data_types
  entry "Payload JSON types (filterable)" lists integer and float as
  DISTINCT 64-bit classes, so the round-trip oracle is TYPE-STRICT
  (int vs float vs bool distinguished — a silent 7 -> 7.0 coercion
  changes the payload's filterable type class).
  (A setup) 1 point id=1, payload {"s":"seed"}; baseline scroll
      snapshots BASEVEC (R27 lesson: on Cosine collections the stored
      vector is L2-normalized by-design — later vector comparisons
      are readback-vs-baseline-readback only).
  (T1 well-formed literal round-trip) one wait=true set carrying one
      literal of EVERY pinned format: geo {"lon":13.405,"lat":52.52}
      (object of doubles), datetime "2026-09-02T12:42:33Z" (RFC 3339
      string), uuid "9f8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d" (uuid
      string), same-typed arrays [1,2,3] and ["alpha","beta"], plus
      scalar float 2.5 / int 7 / bool false -> 200; readback must
      deep-equal the sent payload with STRICT type identity. Dict
      key-mapping catches a lon/lat VALUE TRANSPOSITION (server-side
      swap would read back lon=52.52); the type-strict comparator
      catches silent numeric coercions.
  (T2 typed update face) set geo_pin -> {"lon":1.0,"lat":2.0} and
      created -> "2027-01-01T00:00:00Z" -> 200; readback: those two
      keys hold the NEW literals exactly, every other T1 key intact
      (merge must not disturb untouched typed keys).
  (T3 malformed literals, both-branch state-safe) acceptance of
      malformed literals is NOT pinned as reject — each face is legal
      as EITHER 4xx-reject-cleanly OR 2xx-store-exactly-what-was-sent;
      only divergence is a defect (silent transformation):
      (T3a) geo with a STRING coordinate {"geo_bad":{"lon":"13.4",
            "lat":1.0}} — if 200: readback keeps lon the STRING
            "13.4" (a coerced double = silent type rewrite); if 4xx:
            geo_bad absent, full T2 state intact.
      (T3b) mixed-type array {"mixed":[1,"two"]} — if 200: readback
            keeps [1,"two"] element-exact; if 4xx: absent + T2 state
            intact.
  (G invariants) id set {1}, vector equal BASEVEC (payload-scoped),
      exact count 1 throughout.
  [chunk_payload+set coverage: count_consistency x
   qdrant_type_payload_set_001 (geo/datetime/uuid/same-typed-array
   round-trip + typed update merge + malformed both-branch
   state-safety)]
Oracle: T1 -> 200 and the readback payload deep-equals the sent
  typed-literal dict with STRICT type identity (int vs float vs bool
  distinct; lon=13.405/lat=52.52 untransposed; RFC 3339 + uuid strings
  byte-equal; arrays element-exact) — any silent coercion, drop, or
  transposition = Type4_StateLogicViolation; T2 -> 200 and geo_pin/
  created hold the new literals with all other T1 keys intact (Type4
  on drift); T3a/T3b -> 4xx with prior state intact OR 200 with
  EXACTLY what was sent (a coerced/dropped/partially-applied value =
  Type4_StateLogicViolation); vector equal baseline readback
  (<=1e-6), exact count 1; 5xx only counts when /healthz confirms
  liveness (Type3_RuntimeFailure).
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


def type_strict_eq(a, b):
    """Deep equality with STRICT JSON type identity.

    bool is checked BEFORE int (bool is an int subclass in Python);
    int and float are DISTINCT payload classes per contract data_types
    ("Payload JSON types (filterable)": integer i64 vs float f64).
    """
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


def describe_type_mismatch(a, b, path="payload"):
    """First differing path for diagnostics."""
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
            return f"{path}: keys differ (missing={sorted(only_b)}, extra={sorted(only_a)})"
        for k in a:
            d = describe_type_mismatch(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: len {len(a)} vs {len(b)}"
        for idx, (x, y) in enumerate(zip(a, b)):
            d = describe_type_mismatch(x, y, f"{path}[{idx}]")
            if d:
                return d
        return None
    if a != b:
        return f"{path}: {a!r} vs {b!r}"
    return None


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


def scroll_map(tag, coll, limit=10):
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


def do_typed_set(tag, coll, payload, basevec):
    """set-payload + readback. Returns (branch, payload_dict|None):
    branch in {'ok','branch4xx','abort'}."""
    s, raw = safe_request("POST", "payload_set",
                          path_params={"collection_name": coll},
                          body={"payload": payload, "points": [1]},
                          query_params={"wait": "true"})
    print(f"[{tag} set] status={s} raw={str(raw)[:200]}")
    if s == 0:
        liveness(tag)
        return "abort", None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) set returned {s} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            return "defect", None
        return "abort", None
    branch = "ok" if s == 200 else ("branch4xx" if 400 <= s <= 499 else None)
    if branch is None:
        print(f"[{tag}] UNEXPECTED status {s} — treating as setup error")
        return "abort", None
    time.sleep(0.3)
    m = scroll_map(tag + " readback", coll)
    if m is None:
        return "abort", None
    p = m.get(1)
    if p is None:
        DEFECTS.append(f"({tag}) point 1 disappeared after set-payload — "
                       f"Type4_StateLogicViolation")
        return "defect", None
    pl, okp = pay_dict(p)
    if not okp:
        DEFECTS.append(f"({tag}) point 1 payload is not an object — "
                       f"Type4_StateLogicViolation")
        return "defect", None
    if not vec_eq(vec_of(p), basevec):
        DEFECTS.append(f"({tag}) point 1 vector changed after set-payload — "
                       f"set is payload-scoped — Type4_StateLogicViolation")
    cnt = exact_count(tag + " count", coll)
    if cnt is None:
        return "abort", None
    if cnt != 1:
        DEFECTS.append(f"({tag}) exact count {cnt} != 1 — set must not "
                       f"delete points — Type4_StateLogicViolation")
    return branch, pl


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sps16_" + TS + "_"
    C = PFX + "col"

    T1 = {
        "geo_pin": {"lon": 13.405, "lat": 52.52},
        "created": "2026-09-02T12:42:33Z",
        "uid": "9f8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d",
        "ints": [1, 2, 3],
        "kws": ["alpha", "beta"],
        "f64": 2.5,
        "i64": 7,
        "flag": False,
    }

    try:
        # ---- (A setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": 1, "vector": [1.0, 2.0, 3.0, 4.0],
                "payload": {"s": "seed"}}]
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[A upsert 1] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"
        base = scroll_map("A baseline", C)
        if base is None or 1 not in base:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        BASEVEC = vec_of(base[1])
        if BASEVEC is None:
            print("SETUP_ERROR: baseline readback missing vector")
            return "SCRIPT_ERROR"

        # ---- (T1 well-formed literal round-trip) ----
        branch, pl = do_typed_set("T1 typed literals", C, T1, BASEVEC)
        if branch == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if branch == "defect":
            return "DEFECT_FOUND"
        if branch != "ok":
            print("SETUP_ERROR: plainly valid T1 typed set rejected — "
                  "cannot judge round-trip (status faces in 015)")
            return "SCRIPT_ERROR"
        # merge: seed key "s" must survive plus all typed keys
        t1_expect = dict({"s": "seed"})
        t1_expect.update(T1)
        if not type_strict_eq(pl, t1_expect):
            diff = describe_type_mismatch(pl, t1_expect)
            DEFECTS.append(f"(T1) typed-literal round-trip FAILED — first "
                           f"divergence at {diff} — readback={pl!r} — "
                           f"qdrant_type_payload_set_001 pins geo/datetime/"
                           f"uuid/array literal formats (silent coercion, "
                           f"drop, or lon/lat transposition) — "
                           f"Type4_StateLogicViolation")
        else:
            print(f"[T1] OK: all typed literals round-tripped with strict "
                  f"type identity: {pl!r}")
        lon_ok = isinstance(pl.get("geo_pin"), dict) \
            and pl["geo_pin"].get("lon") == 13.405 \
            and pl["geo_pin"].get("lat") == 52.52
        print(f"[T1] geo lon/lat transposition check: "
              f"{'OK (lon=13.405, lat=52.52)' if lon_ok else 'CHECK ABOVE'}")

        # ---- (T2 typed update face) ----
        T2SET = {"geo_pin": {"lon": 1.0, "lat": 2.0},
                 "created": "2027-01-01T00:00:00Z"}
        t2_expect = dict(t1_expect)
        t2_expect.update(T2SET)
        branch, pl = do_typed_set("T2 typed update", C, T2SET, BASEVEC)
        if branch == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if branch == "defect":
            return "DEFECT_FOUND"
        if branch != "ok":
            print("SETUP_ERROR: plainly valid T2 typed update rejected")
            return "SCRIPT_ERROR"
        if not type_strict_eq(pl, t2_expect):
            diff = describe_type_mismatch(pl, t2_expect)
            DEFECTS.append(f"(T2) typed update drift — first divergence at "
                           f"{diff} — readback={pl!r} — a typed key replace "
                           f"must leave every untouched key intact — "
                           f"Type4_StateLogicViolation")
        else:
            print(f"[T2] OK: geo_pin + created updated, all other typed "
                  f"keys intact")

        # ---- (T3a malformed geo: string coordinate, both-branch) ----
        T3A = {"geo_bad": {"lon": "13.4", "lat": 1.0}}
        t3a_accept = dict(t2_expect)
        t3a_accept.update(T3A)
        branch, pl = do_typed_set("T3a geo string-lon", C, T3A, BASEVEC)
        if branch == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if branch == "defect":
            return "DEFECT_FOUND"
        if branch == "ok":
            if not type_strict_eq(pl, t3a_accept):
                diff = describe_type_mismatch(pl, t3a_accept)
                DEFECTS.append(f"(T3a) accepted the malformed literal but "
                               f"readback diverges from what was sent — "
                               f"first divergence at {diff} — silent "
                               f"transformation of stored state — "
                               f"Type4_StateLogicViolation")
            else:
                print("[T3a] accepted-branch: stored EXACTLY as sent "
                      "(string lon preserved, no coercion) — legal")
        else:
            if "geo_bad" in pl or not type_strict_eq(pl, t2_expect):
                diff = describe_type_mismatch(pl, t2_expect)
                DEFECTS.append(f"(T3a) rejected the malformed literal but "
                               f"state was NOT left intact — divergence at "
                               f"{diff} — partial application on rejection — "
                               f"Type4_StateLogicViolation")
            else:
                print("[T3a] rejected-branch: clean rejection, T2 state "
                      "intact — legal")

        # ---- (T3b malformed array: mixed types, both-branch) ----
        T3B = {"mixed": [1, "two"]}
        # pl is the verified current state after T3a (either branch):
        # accepted -> t3a state; rejected -> t2 state. T3b's expectations
        # build on exactly that current state.
        t3b_accept = dict(pl)
        t3b_accept.update(T3B)
        t3b_reject = pl
        branch, pl = do_typed_set("T3b mixed array", C, T3B, BASEVEC)
        if branch == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if branch == "defect":
            return "DEFECT_FOUND"
        if branch == "ok":
            if not type_strict_eq(pl, t3b_accept):
                diff = describe_type_mismatch(pl, t3b_accept)
                DEFECTS.append(f"(T3b) accepted the mixed-type array but "
                               f"readback diverges from what was sent — "
                               f"first divergence at {diff} — silent "
                               f"transformation (e.g. element coercion or "
                               f"drop) — Type4_StateLogicViolation")
            else:
                print("[T3b] accepted-branch: stored element-exact [1,"
                      "\"two\"] — legal (same-type is a filterability "
                      "promise, storage is JSON)")
        else:
            if not type_strict_eq(pl, t3b_reject):
                diff = describe_type_mismatch(pl, t3b_reject)
                DEFECTS.append(f"(T3b) rejected the mixed-type array but "
                               f"state was NOT left intact — divergence at "
                               f"{diff} — Type4_StateLogicViolation")
            else:
                print("[T3b] rejected-branch: clean rejection, prior state "
                      "intact — legal")

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
