#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_clear_002
# strategy: upsert_idempotence
# endpoint: payload+clear
# constraint_ids: qdrant_state_payload_clear_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/clear-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 3 (idempotence + state-machine loop) against
  qdrant_state_payload_clear_001: "after clear, targeted points carry no
  payload keys". The clear/set_payload pair is cycled on one point so the
  state machine must pass through these exact states:
  (A setup) 1 point, id=10, payload {"a":1,"b":"x"}, vector uploaded.
  (B clear#1) wait=true -> 200; point readback: payload EXACTLY empty,
      vector intact, count still 1.
  (C clear#2 idempotence) same body again -> 200 (not an error); state
      STAYS empty (a second clear must not corrupt, resurrect, or error;
      a 4xx/5xx on an already-empty target = the operation is not
      idempotent over its own output state).
  (D re-set after clear) set_payload {"c":2,"d":"y"} wait=true -> 200;
      readback payload == {"c":2,"d":"y"} EXACTLY — the cleared keys
      a/b must NOT resurrect (a merge-with-ghost state = clear did not
      durably forget the keys).
  (E clear#3) wait=true -> 200; payload empty again, vector intact,
      count still 1.
  (F measured-only) clear on a non-existent point id in a LIVE
      collection -> status printed, NOT adjudicated: idempotent-update
      semantics over absent targets is the same by-design family as
      "Idempotent DELETE returns 200 even if point doesn't exist"
      (SKIPPED: by-design per threat_model).
  Persistence judged via point readback after each mutation (payload
  gone / restored, vector intact, count unchanged) — never via the
  update response alone.
  [chunk_payload+clear coverage: upsert_idempotence x
   qdrant_state_payload_clear_001 (repeat-clear convergence +
   clear->set->clear loop + no ghost-key resurrection)]
Oracle: clear#1/#2/#3 each -> HTTP 200 and the point readback shows
  payload with exactly 0 keys; after set_payload the payload is exactly
  {"c":2,"d":"y"} (any a/b ghost key = Type4_StateLogicViolation);
  vector and exact count (1) invariant across the whole loop; a 4xx on
  the repeat clear = Type4 (non-idempotent over own output); 5xx only
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

# payload+clear / payload+set are not in the runtime PATHS whitelist —
# register VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "payload+clear", "method": "POST",
#    "url": "/collections/{collection_name}/points/payload/clear"}
#   {"path": "payload+set", "method": "POST",
#    "url": "/collections/{collection_name}/points/payload"}
rt.PATHS["payload_clear"] = "/collections/{collection_name}/points/payload/clear"
rt.PATHS["payload_set"] = "/collections/{collection_name}/points/payload"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'payload' in k]}")
if (rt.PATHS.get("payload_clear") != "/collections/{collection_name}/points/payload/clear"
        or rt.PATHS.get("payload_set") != "/collections/{collection_name}/points/payload"):
    print("VERDICT: SCRIPT_ERROR - payload endpoint URL registration failed")
    sys.exit(2)


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


DEFECTS = []


def check_clear_envelope(tag, raw):
    """response_shape pins result: object, result.operation_id: integer|null,
    result.status: string (present-but-wrong-typed = shape conflict)."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        DEFECTS.append(f"({tag}) 200 clear body is not JSON — raw={str(raw)[:150]}")
        return
    if not isinstance(b, dict) or not isinstance(b.get("result"), dict):
        DEFECTS.append(f"({tag}) 200 clear body result is not an object — "
                       f"materialized response_shape pins result: object — "
                       f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return
    res = b["result"]
    oid = res.get("operation_id")
    if oid is not None and (isinstance(oid, bool) or not isinstance(oid, int)):
        DEFECTS.append(f"({tag}) result.operation_id={oid!r} is not "
                       f"integer|null — Type4_StateLogicViolation")
    st = res.get("status")
    if st is not None and not isinstance(st, str):
        DEFECTS.append(f"({tag}) result.status={st!r} is not a string — "
                       f"Type4_StateLogicViolation")
    if st is None:
        print(f"[{tag}] measured: result.status absent in clear envelope")


def read_point(tag, coll, pid):
    """GET point with_payload+with_vector -> (payload_dict, vector, ok)."""
    s, raw = safe_request("GET", "get_point",
                          path_params={"name": coll, "point_id": pid},
                          query_params={"with_payload": "true",
                                        "with_vector": "true"})
    print(f"[{tag} get_point] status={s} raw={str(raw)[:200]}")
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
    except (json.JSONDecodeError, ValueError, TypeError):
        res = None
    if not isinstance(res, dict):
        print(f"SETUP_ERROR: get_point result missing — raw={str(raw)[:200]}")
        return None
    pl = res.get("payload")
    if pl is None:
        pl = {}
    if not isinstance(pl, dict):
        DEFECTS.append(f"({tag}) point payload is not an object — "
                       f"Type4_StateLogicViolation")
        pl = {}
    return pl, res.get("vector"), True


def vec_ok(v, expected, tol=1e-6):
    if not isinstance(v, list) or len(v) != len(expected):
        return False
    return all(isinstance(a, (int, float)) and abs(a - b) <= tol
               for a, b in zip(v, expected))


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


def expect_empty(tag, got):
    if len(got) != 0:
        DEFECTS.append(f"({tag}) point 10 carries payload keys {sorted(got.keys())} "
                       f"— qdrant_state_payload_clear_001 pins 'targeted points "
                       f"carry no payload keys' — Type4_StateLogicViolation")
    else:
        print(f"[{tag}] OK: payload exactly empty")


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spc2_" + TS + "_"
    C = PFX + "col"
    VEC = [10.0, 1.0, 2.0, 3.0]

    def do_clear(tag):
        s, raw = safe_request("POST", "payload_clear",
                              path_params={"collection_name": C},
                              body={"points": [10]},
                              query_params={"wait": "true"})
        print(f"[{tag}] status={s} raw={raw[:200]}")
        if s == 0:
            liveness(tag)
            return None
        if 500 <= s <= 599:
            if liveness(tag):
                DEFECTS.append(f"({tag}) clear returned {s} with service "
                               f"alive — Type3_RuntimeFailure — "
                               f"raw={raw[:150]}")
                return "DEF"
            return None
        return s, raw

    try:
        # ---- (A setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": [{"id": 10, "vector": VEC,
                                                    "payload": {"a": 1,
                                                                "b": "x"}}]},
                                  query_params={"wait": "true"})
        print(f"[A upsert] status={u_s} raw={u_raw[:150]}")
        if u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"

        # ---- (B clear #1) ----
        r = do_clear("B clear#1")
        if r is None:
            return "SCRIPT_ERROR"
        if r == "DEF":
            return "DEFECT_FOUND"
        if r[0] != 200:
            print(f"SETUP_ERROR: clear#1 returned {r[0]}")
            return "SCRIPT_ERROR"
        check_clear_envelope("B clear#1", r[1])
        got = read_point("B readback", C, 10)
        if got is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        expect_empty("B readback", got[0])
        if not vec_ok(got[1], VEC):
            DEFECTS.append("(B) point 10 vector changed after clear — "
                           "clear is payload-scoped — "
                           "Type4_StateLogicViolation")
        c1 = exact_count("B count", C)
        if c1 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if c1 != 1:
            DEFECTS.append(f"(B) exact count {c1} != 1 after clear — "
                           f"Type4_StateLogicViolation")

        # ---- (C clear #2 idempotence over own output) ----
        r = do_clear("C clear#2")
        if r is None:
            return "SCRIPT_ERROR"
        if r == "DEF":
            return "DEFECT_FOUND"
        if r[0] != 200:
            DEFECTS.append(f"(C) repeat clear on an already-empty target "
                           f"returned {r[0]} — clear must be idempotent over "
                           f"its own output state — "
                           f"Type4_StateLogicViolation — raw={r[1][:150]}")
        else:
            check_clear_envelope("C clear#2", r[1])
        got = read_point("C readback", C, 10)
        if got is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        expect_empty("C readback", got[0])

        # ---- (D re-set after clear: no ghost-key resurrection) ----
        s_s, s_raw = safe_request("POST", "payload_set",
                                  path_params={"collection_name": C},
                                  body={"payload": {"c": 2, "d": "y"},
                                        "points": [10]},
                                  query_params={"wait": "true"})
        print(f"[D set_payload] status={s_s} raw={s_raw[:200]}")
        if s_s == 0:
            liveness("D")
            return "SCRIPT_ERROR"
        if 500 <= s_s <= 599:
            if liveness("D"):
                DEFECTS.append(f"(D) set_payload returned {s_s} with service "
                               f"alive — Type3_RuntimeFailure")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if s_s != 200:
            print(f"SETUP_ERROR: set_payload returned {s_s}")
            return "SCRIPT_ERROR"
        got = read_point("D readback", C, 10)
        if got is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if got[0] != {"c": 2, "d": "y"}:
            ghosts = sorted(set(got[0].keys()) - {"c", "d"})
            DEFECTS.append(f"(D) after clear->set, payload is {got[0]!r} != "
                           f"{{'c': 2, 'd': 'y'}}"
                           + (f" — cleared keys {ghosts} RESURRECTED — "
                              f"clear did not durably forget the keys"
                              if ghosts else " — Type4_StateLogicViolation")
                           + " — Type4_StateLogicViolation")
        else:
            print("[D] OK: payload exactly the new dict, no ghost keys")

        # ---- (E clear #3: back to empty) ----
        r = do_clear("E clear#3")
        if r is None:
            return "SCRIPT_ERROR"
        if r == "DEF":
            return "DEFECT_FOUND"
        if r[0] != 200:
            print(f"SETUP_ERROR: clear#3 returned {r[0]}")
            return "SCRIPT_ERROR"
        got = read_point("E readback", C, 10)
        if got is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        expect_empty("E readback", got[0])
        if not vec_ok(got[1], VEC):
            DEFECTS.append("(E) point 10 vector changed after clear#3 — "
                           "Type4_StateLogicViolation")
        c3 = exact_count("E count", C)
        if c3 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if c3 != 1:
            DEFECTS.append(f"(E) exact count {c3} != 1 after the full loop — "
                           f"Type4_StateLogicViolation")

        # ---- (F measured-only: non-existent point target) ----
        f_s, f_raw = safe_request("POST", "payload_clear",
                                  path_params={"collection_name": C},
                                  body={"points": [9999]},
                                  query_params={"wait": "true"})
        print(f"[F non-existent point clear] MEASURED status={f_s} "
              f"raw={str(f_raw)[:200]} — SKIPPED: by-design per threat_model "
              f"(idempotent-update family, cf. idempotent DELETE on absent "
              f"point) — not adjudicated")

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
