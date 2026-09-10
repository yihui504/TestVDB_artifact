#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_overwrite_002
# strategy: upsert_idempotence
# endpoint: payload+overwrite
# constraint_ids: qdrant_state_payload_overwrite_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/overwrite-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 3 (idempotence + state-machine loop) against
  qdrant_state_payload_overwrite_001: "overwrite replaces the ENTIRE
  payload (set semantics: keys missing from the new payload are
  removed)". The overwrite/set-payload pair is cycled on one point so
  the state machine must pass through these EXACT states:
  (A setup) 1 point, id=10, payload {"a":1,"b":"x","c":true}; baseline
      readback snapshots the stored vector as BASEVEC (R27 lesson: on
      Cosine collections the stored vector is L2-normalized by-design —
      later vector comparisons are readback-vs-baseline-readback only).
  (D1 overwrite#1) PUT {"payload":{"d":"new"}} wait=true -> 200; point
      readback payload EXACTLY {"d":"new"} — a, b, c all removed (full
      replacement, not merge).
  (D2 overwrite#2 idempotence) same body again -> 200 (not an error);
      state STAYS {"d":"new"} (a repeat of the same full replacement
      must neither corrupt, duplicate keys, resurrect removed keys, nor
      error — a 4xx/5xx on the operation's own prior output state =
      not idempotent over its own result).
  (D3 set-payload merge contrast) POST payload+set
      {"payload":{"e":"setval"}} wait=true -> 200; readback EXACTLY
      {"d":"new","e":"setval"} — the POST verb MERGES into the current
      payload. This step pins the verb asymmetry: if PUT had merged,
      D1 already fails; if POST replaced, D3 readback would be
      {"e":"setval"}.
  (D4 overwrite after merge) PUT {"payload":{"f":2}} wait=true -> 200;
      readback EXACTLY {"f":2} — d AND e removed: full replacement
      reasserts over a merged state (a surviving d/e here = the
      replacement is order-dependent).
  (D5 empty-payload overwrite, set-semantics limit) PUT
      {"payload":{}} wait=true — "keys missing from the new payload
      are removed" with an EMPTY new payload means ALL keys removed.
      R28 lesson: payload is required and presence-only — empty-object
      acceptance is NOT explicitly pinned, so a 4xx on {} is recorded
      but NOT adjudicated; IF accepted (200), the readback payload
      must be empty ({} or null) with no previous key surviving.
  (H invariants) vector equals BASEVEC (<=1e-6) after every step;
      exact count stays 1 throughout.
  Persistence judged via scroll readback after each mutation — never
  via the operation response alone.
  [chunk_payload+overwrite coverage: upsert_idempotence x
   qdrant_state_payload_overwrite_001 (overwrite idempotence over own
   output + overwrite/set verb asymmetry + post-merge replacement +
   empty-payload limit)]
Oracle: on a 1-point collection (every step expects HTTP 200):
  overwrite {"d":"new"} twice -> both HTTP 200 and readback stays EXACTLY {"d":"new"}; set {"e":"setval"}
  -> readback EXACTLY {"d":"new","e":"setval"}; overwrite {"f":2} ->
  readback EXACTLY {"f":2}; overwrite {} -> if 200 then readback
  payload empty ({} or null). Vector equals the baseline readback
  (<=1e-6) and exact count 1 at every checkpoint. Any state deviation,
  an error on the repeated identical overwrite, a non-empty payload
  after an accepted {} overwrite, a vector change, or count drift =
  Type4_StateLogicViolation; 5xx only counts when /healthz confirms
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

DEFECTS = []
ABORT = [False]


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


def scroll_one(tag, coll):
    """scroll -> single point dict for id=10, or None on abort."""
    s, raw = safe_request("POST", "scroll", path_params={"name": coll},
                          body={"limit": 10, "with_payload": True,
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
    for p in pts:
        if isinstance(p, dict) and p.get("id") == 10:
            return p
    print(f"SETUP_ERROR: point 10 missing from scroll — got "
          f"{[p.get('id') for p in pts if isinstance(p, dict)]}")
    return None


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


def step_overwrite(tag, coll, payload):
    """PUT payload+overwrite wait=true. Returns status (or -2 abort)."""
    s, raw = safe_request("PUT", "payload_overwrite",
                          path_params={"collection_name": coll},
                          body={"payload": payload, "points": [10]},
                          query_params={"wait": "true"})
    print(f"[{tag} PUT overwrite payload={payload!r}] status={s} "
          f"raw={str(raw)[:180]}")
    if s == 0:
        liveness(tag)
        return -2
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) overwrite returned {s} with service "
                           f"alive — Type3_RuntimeFailure — "
                           f"raw={str(raw)[:150]}")
        return -2
    return s


def step_set(tag, coll, payload):
    """POST payload+set wait=true. Returns status (or -2 abort)."""
    s, raw = safe_request("POST", "payload_set",
                          path_params={"collection_name": coll},
                          body={"payload": payload, "points": [10]},
                          query_params={"wait": "true"})
    print(f"[{tag} POST set payload={payload!r}] status={s} "
          f"raw={str(raw)[:180]}")
    if s == 0:
        liveness(tag)
        return -2
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) set returned {s} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        return -2
    return s


def checkpoint(tag, coll, expected, basevec, allow_empty_null=False):
    """Readback point 10; adjudicate payload == expected + vector + count."""
    p = scroll_one(tag, coll)
    if p is None:
        return None
    pl, okp = pay_dict(p)
    if not okp:
        DEFECTS.append(f"({tag}) point 10 payload is not an object — "
                       f"Type4_StateLogicViolation")
        return pl
    if allow_empty_null:
        okpay = (pl == {} or pl == expected)
    else:
        okpay = (pl == expected)
    if not okpay:
        DEFECTS.append(f"({tag}) point 10 payload {pl!r} != expected "
                       f"{expected!r} — qdrant_state_payload_overwrite_001 "
                       f"set semantics — Type4_StateLogicViolation")
    else:
        print(f"[{tag}] OK: payload exactly {pl!r}")
    if not vec_eq(vec_of(p), basevec):
        DEFECTS.append(f"({tag}) point 10 vector changed: {vec_of(p)!r} != "
                       f"baseline readback {basevec!r} — payload operations "
                       f"are payload-scoped — Type4_StateLogicViolation")
    cnt = exact_count(tag + " count", coll)
    if cnt is None:
        return pl
    if cnt != 1:
        DEFECTS.append(f"({tag}) exact count {cnt} != 1 — payload "
                       f"operations must not delete points — "
                       f"Type4_StateLogicViolation")
    return pl


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spo2_" + TS + "_"
    C = PFX + "col"
    PID = 10

    try:
        # ---- (A setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": [{"id": PID,
                                                    "vector": [1.0, 2.0, 3.0, 4.0],
                                                    "payload": {"a": 1, "b": "x",
                                                                "c": True}}]},
                                  query_params={"wait": "true"})
        print(f"[A upsert] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"
        p0 = scroll_one("A baseline", C)
        if p0 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        BASEVEC = vec_of(p0)
        if BASEVEC is None:
            print("SETUP_ERROR: baseline readback missing vector")
            return "SCRIPT_ERROR"
        pl0, _ = pay_dict(p0)
        if pl0 != {"a": 1, "b": "x", "c": True}:
            DEFECTS.append(f"(A baseline) payload {pl0!r} != uploaded — "
                           f"Type4_StateLogicViolation")

        # ---- (D1 overwrite#1) full replacement ----
        s1 = step_overwrite("D1 overwrite#1", C, {"d": "new"})
        if s1 == -2:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if s1 != 200:
            print(f"SETUP_ERROR: D1 overwrite returned {s1} — cannot judge "
                  f"state machine (faces adjudicated by "
                  f"state_payload_overwrite_005)")
            return "SCRIPT_ERROR"
        time.sleep(0.3)
        checkpoint("D1 readback", C, {"d": "new"}, BASEVEC)

        # ---- (D2 overwrite#2 idempotence over own output) ----
        s2 = step_overwrite("D2 overwrite#2 (repeat)", C, {"d": "new"})
        if s2 == -2:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if s2 not in (200, 201):
            DEFECTS.append(f"(D2) repeating the IDENTICAL overwrite that "
                           f"already produced its own output state returned "
                           f"{s2} — the operation is not idempotent over its "
                           f"own result — Type4_StateLogicViolation")
        time.sleep(0.3)
        checkpoint("D2 readback", C, {"d": "new"}, BASEVEC)

        # ---- (D3 set-payload merge contrast) ----
        s3 = step_set("D3 set-merge", C, {"e": "setval"})
        if s3 == -2:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if s3 != 200:
            print(f"SETUP_ERROR: D3 set returned {s3}")
            return "SCRIPT_ERROR"
        time.sleep(0.3)
        checkpoint("D3 readback", C, {"d": "new", "e": "setval"}, BASEVEC)

        # ---- (D4 overwrite after merge reasserts replacement) ----
        s4 = step_overwrite("D4 overwrite-after-merge", C, {"f": 2})
        if s4 == -2:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if s4 != 200:
            print(f"SETUP_ERROR: D4 overwrite returned {s4}")
            return "SCRIPT_ERROR"
        time.sleep(0.3)
        checkpoint("D4 readback", C, {"f": 2}, BASEVEC)

        # ---- (D5 empty-payload overwrite, set-semantics limit) ----
        s5 = step_overwrite("D5 overwrite {}", C, {})
        if s5 == -2:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if 200 <= s5 <= 299:
            time.sleep(0.3)
            checkpoint("D5 readback", C, {}, BASEVEC, allow_empty_null=True)
        elif 400 <= s5 <= 499:
            print(f"[D5] MEASURED (not adjudicated): empty-object overwrite "
                  f"rejected with {s5} — empty-payload acceptance is not "
                  f"explicitly pinned (payload is presence-required only)")
            p5 = scroll_one("D5 state-unchanged check", C)
            if p5 is not None:
                pl5, _ = pay_dict(p5)
                if pl5 != {"f": 2}:
                    DEFECTS.append(f"(D5) a 4xx-rejected overwrite still "
                                   f"mutated state: {pl5!r} != {{'f': 2}} — "
                                   f"rejected operation must not write — "
                                   f"Type4_StateLogicViolation")
        else:
            print(f"[D5] MEASURED (not adjudicated): overwrite {{}} returned "
                  f"unexpected status {s5}")

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
