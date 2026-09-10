#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_delete_002
# strategy: upsert_idempotence
# endpoint: payload+delete
# constraint_ids: qdrant_state_payload_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 3 (idempotence + state-machine loop) against
  qdrant_state_payload_delete_001: "only the listed payload keys are
  removed; unlisted keys persist". The key-delete/set-payload pair is
  cycled on one point so the state machine must pass through these
  exact states:
  (A setup) 1 point, id=10, payload {"a":1,"b":"x","c":true}; baseline
      readback snapshots the stored vector as BASEVEC (R27 lesson: on
      Cosine collections the stored vector is L2-normalized by-design —
      later vector comparisons are readback-vs-baseline-readback only).
  (D1 delete#1) keys ["a"] wait=true -> 200; point readback payload
      EXACTLY {"b":"x","c":true} — one listed key removed, both
      unlisted keys persist with original values.
  (D2 delete#2 idempotence) same body again -> 200 (not an error);
      state STAYS {"b":"x","c":true} (a repeat delete of an
      already-removed key must neither corrupt, resurrect, nor error;
      a 4xx/5xx on its own prior output state = the operation is not
      idempotent over its own result).
  (D3 re-set after delete) payload+set {"a":99,"d":"new"} wait=true ->
      200; readback payload == {"a":99,"b":"x","c":true,"d":"new"}
      EXACTLY — the pre-delete "a":1 value must NOT resurrect as a
      ghost (a merge-with-ghost state = the delete did not durably
      forget the old value; a set that loses "c" = the set is not a
      merge over survivors).
  (D4 multi-key delete) keys ["a","b"] -> 200; readback EXACTLY
      {"c":true,"d":"new"}.
  (D5 delete-to-empty) keys ["c","d"] -> 200; readback payload EXACTLY
      empty — key deletion must be able to reach the no-keys state
      without touching the point itself.
  (D6 measured-only) delete of a key that NEVER existed on a live
      point -> status printed, NOT adjudicated: idempotent-delete
      semantics over absent keys is the same by-design family as
      "Idempotent DELETE returns 200 even if point doesn't exist"
      (SKIPPED: by-design per threat_model).
  Exact count must stay 1 and the vector equal BASEVEC across the whole
  loop. Persistence judged via point readback after each mutation —
  never via the mutation response alone.
  [chunk_payload+delete coverage: upsert_idempotence x
   qdrant_state_payload_delete_001 (repeat-delete convergence +
   delete->set ghost-value check + delete-to-empty)]
Oracle: D1/D2/D4/D5 each -> HTTP 200 and the point readback shows
  exactly {"b":"x","c":true} after D1/D2, {"c":true,"d":"new"} after
  D4, and 0 keys after D5; after D3 the payload is exactly
  {"a":99,"b":"x","c":true,"d":"new"} (an a:1 ghost or a lost c =
  Type4_StateLogicViolation); a 4xx on the repeat delete (D2) =
  Type4 (non-idempotent over own output); vector equal to the baseline
  readback (<=1e-6) and exact count 1 invariant throughout; 5xx only
  counts when /healthz confirms liveness (Type3_RuntimeFailure).
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

PID = 10
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


def get_point(tag, coll):
    """get_point with_payload+with_vector -> point dict or None on abort."""
    s, raw = safe_request("GET", "get_point",
                          path_params={"name": coll, "point_id": PID},
                          query_params={"with_payload": "true",
                                        "with_vector": "true"})
    print(f"[{tag} get_point] status={s} raw={str(raw)[:180]}")
    if s == 0:
        liveness(tag)
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) get_point returned {s} with service "
                           f"alive — Type3_RuntimeFailure — raw={str(raw)[:150]}")
        return None
    if s != 200:
        print(f"SETUP_ERROR: get_point returned {s}")
        return None
    try:
        res = json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        res = None
    if not isinstance(res, dict):
        print(f"SETUP_ERROR: get_point result missing — raw={str(raw)[:200]}")
        return None
    return res


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


def expect_state(tag, coll, expected, basevec, count0):
    """Read back the point, adjudicate payload/vector/count against the
    declared expectation. Returns False on readback abort."""
    p = get_point(tag, coll)
    if p is None:
        return False
    pl, okp = pay_dict(p)
    if not okp:
        DEFECTS.append(f"({tag}) payload is not an object — "
                       f"Type4_StateLogicViolation")
    elif pl != expected:
        DEFECTS.append(f"({tag}) payload {pl!r} != expected {expected!r} — "
                       f"qdrant_state_payload_delete_001 — "
                       f"Type4_StateLogicViolation")
    else:
        print(f"[{tag}] OK: payload == {pl!r}")
    if not vec_eq(vec_of(p), basevec):
        DEFECTS.append(f"({tag}) vector changed: {vec_of(p)!r} != baseline "
                       f"readback {basevec!r} — payload ops must not touch "
                       f"vectors — Type4_StateLogicViolation")
    cnt = exact_count(tag + " count", coll)
    if cnt is None:
        return False
    if cnt != count0:
        DEFECTS.append(f"({tag}) exact count {cnt} != {count0} — payload ops "
                       f"must not delete points — Type4_StateLogicViolation")
    return True


def do_delete_keys(tag, coll, keys):
    s, raw = safe_request("POST", "payload_delete",
                          path_params={"collection_name": coll},
                          body={"points": [PID], "keys": keys},
                          query_params={"wait": "true"})
    print(f"[{tag} delete keys={keys}] status={s} raw={str(raw)[:200]}")
    if s == 0:
        liveness(tag)
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) delete returned {s} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        return "defect"
    if s != 200:
        DEFECTS.append(f"({tag}) plainly valid key-delete returned {s} — "
                       f"Type4_StateLogicViolation (non-idempotent over own "
                       f"output or valid op rejected) — raw={str(raw)[:150]}")
        return "defect"
    return "ok"


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spd2_" + TS + "_"
    C = PFX + "col"

    P0 = {"a": 1, "b": "x", "c": True}
    AFTER_D1 = {"b": "x", "c": True}
    AFTER_D3 = {"a": 99, "b": "x", "c": True, "d": "new"}
    AFTER_D4 = {"c": True, "d": "new"}

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
                                                    "payload": P0}]},
                                  query_params={"wait": "true"})
        print(f"[A upsert] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"
        p_base = get_point("A baseline", C)
        if p_base is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        pl0, ok0 = pay_dict(p_base)
        if not ok0 or pl0 != P0:
            DEFECTS.append(f"(A baseline) payload {pl0!r} != uploaded "
                           f"{P0!r} — Type4_StateLogicViolation")
        BASEVEC = vec_of(p_base)
        if BASEVEC is None:
            print("SETUP_ERROR: baseline readback missing vector")
            return "SCRIPT_ERROR"
        count0 = exact_count("A count", C)
        if count0 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if count0 != 1:
            DEFECTS.append(f"(A) expected count 1, got {count0} — "
                           f"Type4_StateLogicViolation")

        # ---- (D1 delete#1 ["a"]) ----
        r = do_delete_keys("D1", C, ["a"])
        if r is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        time.sleep(0.3)
        if not expect_state("D1", C, AFTER_D1, BASEVEC, count0):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- (D2 delete#2 same body — idempotence over own output) ----
        r = do_delete_keys("D2", C, ["a"])
        if r is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        time.sleep(0.3)
        if not expect_state("D2", C, AFTER_D1, BASEVEC, count0):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- (D3 re-set after delete — ghost-value check) ----
        s3, raw3 = safe_request("POST", "payload_set",
                                path_params={"collection_name": C},
                                body={"points": [PID],
                                      "payload": {"a": 99, "d": "new"}},
                                query_params={"wait": "true"})
        print(f"[D3 set a=99,d=new] status={s3} raw={raw3[:200]}")
        if s3 == 0:
            liveness("D3")
            return "SCRIPT_ERROR"
        if 500 <= s3 <= 599:
            if liveness("D3"):
                DEFECTS.append(f"(D3) set_payload returned {s3} with service "
                               f"alive — Type3_RuntimeFailure — "
                               f"raw={raw3[:150]}")
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        if s3 != 200:
            print(f"SETUP_ERROR: set_payload returned {s3}")
            return "SCRIPT_ERROR"
        time.sleep(0.3)
        if not expect_state("D3", C, AFTER_D3, BASEVEC, count0):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- (D4 multi-key delete ["a","b"]) ----
        r = do_delete_keys("D4", C, ["a", "b"])
        if r is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        time.sleep(0.3)
        if not expect_state("D4", C, AFTER_D4, BASEVEC, count0):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- (D5 delete-to-empty ["c","d"]) ----
        r = do_delete_keys("D5", C, ["c", "d"])
        if r is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        time.sleep(0.3)
        if not expect_state("D5", C, {}, BASEVEC, count0):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- (D6 measured-only: never-existing key — by-design family) ----
        s6, raw6 = safe_request("POST", "payload_delete",
                                path_params={"collection_name": C},
                                body={"points": [PID],
                                      "keys": ["never_existed_key"]},
                                query_params={"wait": "true"})
        print(f"[D6 delete never-existing key] status={s6} raw={raw6[:200]} "
              f"— measured only, NOT adjudicated "
              f"(SKIPPED: by-design per threat_model — idempotent-delete "
              f"family over absent targets)")

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
