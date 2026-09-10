#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_delete_005
# strategy: delete_consistency
# endpoint: payload+delete
# constraint_ids: qdrant_behavioral_payload_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 2 (post-DELETE state consistency) against the
  behavioral face qdrant_behavioral_payload_delete_001: "delete_payload
  returns HTTP 200 on valid targets; 400 on invalid input; 404 for a
  missing collection". The delete verdict must track the collection
  lifecycle AND the input-validity branches exactly:
  (A negative, 404 branch) never-created unique name, VALID body
      {"keys":["a"],"points":[1]} -> HTTP 404 EXACTLY (a 200 here
      reports success for a collection that never existed = phantom
      ack; a 5xx instead of 404 = the face cannot express absence; any
      other code violates the pinned 404 branch).
  (B setup) create + upsert 2 payload-bearing points -> 200 (gate).
  (C1 negative, 400 branch — invalid input on a LIVE collection):
      (i) body missing the required "keys" entirely; (ii) keys as a
      plain string "a" instead of array[string]; (iii) keys: null.
      Each must be REJECTED (400 pinned; 4xx family = rejected with
      clear diagnostics, not a defect). A 200/201 = invalid input
      accepted (Type1_IllegalSuccess); a 5xx with service alive =
      Type3_RuntimeFailure.
  (C2 positive, 200 branch) live collection, delete
      {"points":[1],"keys":["a"]} wait=true -> HTTP 200 with the
      materialized envelope (result: object; result.operation_id
      integer|null; result.status string), AND the 200 must not lie:
      point 1 readback loses exactly "a" keeping "b", while sibling
      point 2 keeps its exact payload.
  (D post-delete, 404 branch) drop the collection (confirmed via
      describe -> 404) -> delete the SAME name, valid body -> HTTP 404
      EXACTLY (a zombie 200 after a confirmed delete = the delete did
      not retire the write face).
  (E recreate, measured-only) recreate the same name; delete on the
      empty recreation targets a point that does not exist — status
      printed, NOT adjudicated: idempotent-update semantics over
      absent point targets is the by-design family of "Idempotent
      DELETE returns 200 even if point doesn't exist"
      (SKIPPED: by-design per threat_model).
  (F clean-slate) fresh upsert id=1 {"fresh":true} -> 200; baseline
      readback (payload + vector, R27 lesson: vector comparisons are
      readback-vs-baseline-readback) -> delete ["fresh"] -> 200 ->
      readback payload EXACTLY empty; any pre-drop "old" key
      reappearing = zombie state leaking across incarnations.
  [chunk_payload+delete coverage: delete_consistency x
   qdrant_behavioral_payload_delete_001 (never-created 404 + invalid
   input 400 + valid 200 envelope + post-delete 404 + recreate
   clean-slate)]
Oracle: never-created name -> HTTP 404; invalid input (missing keys /
  keys as string / keys null) on a live collection -> 4xx rejection
  (400 pinned; a 200 = Type1_IllegalSuccess; 5xx = Type3 only when
  /healthz alive); live collection -> HTTP 200 with result an object
  (operation_id integer|null, status string when present) and the
  targeted point loses exactly "a" keeping "b" while its sibling keeps
  its payload; after a confirmed drop -> HTTP 404 again; after
  recreate + fresh upsert + delete -> payload exactly empty with no
  pre-drop key resurrection. Any other status on the pinned branches =
  Type4_StateLogicViolation (or Type3 for 5xx with liveness).
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

# payload+delete is not in the runtime PATHS whitelist — register VERBATIM
# from raw_knowledge api_endpoints[].url:
#   {"path": "payload+delete", "method": "POST",
#    "url": "/collections/{collection_name}/points/payload/delete"}
rt.PATHS["payload_delete"] = "/collections/{collection_name}/points/payload/delete"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'payload' in k]}")
if rt.PATHS.get("payload_delete") != "/collections/{collection_name}/points/payload/delete":
    print("VERDICT: SCRIPT_ERROR - payload_delete URL registration failed")
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


def check_delete_envelope(tag, raw):
    """Spec-typed envelope check of a 200 key-delete body.
    response_shape pins result: object, result.operation_id: integer|null,
    result.status: string."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        DEFECTS.append(f"({tag}) 200 delete body is not JSON — raw={str(raw)[:150]}")
        return
    if not isinstance(b, dict):
        DEFECTS.append(f"({tag}) 200 delete body is not an object — raw={str(raw)[:150]}")
        return
    res = b.get("result")
    if not isinstance(res, dict):
        DEFECTS.append(f"({tag}) 200 delete body result is not an object "
                       f"(got {type(res).__name__}) — materialized "
                       f"response_shape pins result: object — "
                       f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return
    oid = res.get("operation_id")
    if oid is not None and (isinstance(oid, bool) or not isinstance(oid, int)):
        DEFECTS.append(f"({tag}) result.operation_id={oid!r} is not "
                       f"integer|null — Type4_StateLogicViolation")
    st = res.get("status")
    if st is not None and not isinstance(st, str):
        DEFECTS.append(f"({tag}) result.status={st!r} is not a string — "
                       f"Type4_StateLogicViolation")
    if st is None:
        print(f"[{tag}] measured: result.status absent in delete envelope")


def do_payload_delete(tag, coll, body, wait=True):
    s, raw = safe_request("POST", "payload_delete",
                          path_params={"collection_name": coll},
                          body=body,
                          query_params={"wait": "true"} if wait else None)
    print(f"[{tag}] status={s} raw={str(raw)[:220]}")
    return s, raw


def expect_404(tag, coll, body):
    """Pinned branch: missing collection -> 404 exactly."""
    s, raw = do_payload_delete(tag, coll, body)
    if s == 0:
        liveness(tag)
        return "abort"
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {s} (expected 404) with service "
                           f"alive — the face cannot express absence — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            return "defect"
        return "abort"
    if s in (200, 201):
        DEFECTS.append(f"({tag}) returned {s} (expected 404) — phantom ack "
                       f"for a missing collection — Type1_IllegalSuccess/"
                       f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return "defect"
    if s != 404:
        DEFECTS.append(f"({tag}) returned {s} (expected 404) — violates the "
                       f"pinned 404 branch of "
                       f"qdrant_behavioral_payload_delete_001 — "
                       f"Type4_StateLogicViolation")
        return "defect"
    print(f"[{tag}] OK: 404 as pinned")
    return "ok"


def expect_rejection(tag, coll, body):
    """Pinned branch: invalid input -> 400 (4xx family = rejected with
    diagnostics). 2xx = accepted invalid input; 5xx = Type3 w/ liveness."""
    s, raw = do_payload_delete(tag, coll, body)
    if s == 0:
        liveness(tag)
        return "abort"
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) invalid input produced {s} with service "
                           f"alive — Type3_RuntimeFailure — "
                           f"raw={str(raw)[:150]}")
            return "defect"
        return "abort"
    if s in (200, 201):
        DEFECTS.append(f"({tag}) INVALID input accepted with {s} — "
                       f"Type1_IllegalSuccess — raw={str(raw)[:150]}")
        return "defect"
    if s in (400, 422):
        print(f"[{tag}] OK: rejected with {s} (400 pinned) — "
              f"raw={str(raw)[:120]}")
        return "ok"
    print(f"[{tag}] measured: rejected with {s} (400 pinned, other 4xx "
          f"recorded, not adjudicated — rejection with diagnostics)")
    return "ok"


def pay_dict(p):
    pl = p.get("payload")
    if pl is None:
        return {}, True
    if isinstance(pl, dict):
        return pl, True
    return {}, False


def get_point(tag, coll, pid):
    s, raw = safe_request("GET", "get_point",
                          path_params={"name": coll, "point_id": pid},
                          query_params={"with_payload": "true",
                                        "with_vector": "true"})
    print(f"[{tag} get_point {pid}] status={s} raw={str(raw)[:180]}")
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


def vec_eq(a, b, tol=1e-6):
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
        return False
    return all(isinstance(x, (int, float)) and isinstance(y, (int, float))
               and abs(x - y) <= tol for x, y in zip(a, b))


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spd5_" + TS + "_"
    C = PFX + "col"
    NEVER = PFX + "never"

    try:
        # ---- (A negative: never-created collection -> 404) ----
        r = expect_404("A never-created", NEVER,
                       {"keys": ["a"], "points": [1]})
        if r == "abort":
            return "SCRIPT_ERROR"
        if r == "defect":
            return "DEFECT_FOUND"

        # ---- (B setup) create + upsert 2 payload-bearing points ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": [
                                      {"id": 1, "vector": [1.0, 2.0, 3.0, 4.0],
                                       "payload": {"a": 1, "b": "keep"}},
                                      {"id": 2, "vector": [5.0, 6.0, 7.0, 8.0],
                                       "payload": {"a": 2, "b": "sib"}}]},
                                  query_params={"wait": "true"})
        print(f"[B upsert 2] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("B")
            return "SCRIPT_ERROR"

        # ---- (C1 invalid input on a LIVE collection -> 4xx, 400 pinned) ----
        for tag, body in [
                ("C1-i missing keys", {"points": [1]}),
                ("C1-ii keys as string", {"keys": "a", "points": [1]}),
                ("C1-iii keys null", {"keys": None, "points": [1]})]:
            r = expect_rejection(tag, C, body)
            if r == "abort":
                return "SCRIPT_ERROR"
            if r == "defect":
                return "DEFECT_FOUND"

        # ---- (C2 positive: valid delete -> 200 + envelope + non-lie) ----
        s_c, raw_c = do_payload_delete("C2 valid delete", C,
                                       {"points": [1], "keys": ["a"]})
        if s_c == 0:
            liveness("C2")
            return "SCRIPT_ERROR"
        if 500 <= s_c <= 599:
            if liveness("C2"):
                DEFECTS.append(f"(C2) valid delete returned {s_c} with service "
                               f"alive — Type3_RuntimeFailure — "
                               f"raw={raw_c[:150]}")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if s_c != 200:
            DEFECTS.append(f"(C2) valid delete returned {s_c} (expected 200) "
                           f"— violates the pinned 200 branch of "
                           f"qdrant_behavioral_payload_delete_001 — "
                           f"Type4_StateLogicViolation")
            return "DEFECT_FOUND"
        check_delete_envelope("C2", raw_c)
        time.sleep(0.4)
        p1 = get_point("C2 point1", C, 1)
        if p1 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        pl1, ok1 = pay_dict(p1)
        if not ok1:
            DEFECTS.append("(C2) point 1 payload is not an object — "
                           "Type4_StateLogicViolation")
        elif pl1 != {"b": "keep"}:
            DEFECTS.append(f"(C2) the 200 lied: point 1 payload {pl1!r} != "
                           f"exactly {{'b':'keep'}} after deleting ['a'] — "
                           f"Type4_StateLogicViolation")
        else:
            print("[C2] OK: point 1 keeps exactly {'b':'keep'}")
        p2 = get_point("C2 point2", C, 2)
        if p2 is not None:
            pl2, _ = pay_dict(p2)
            if pl2 != {"a": 2, "b": "sib"}:
                DEFECTS.append(f"(C2) sibling point 2 payload changed: "
                               f"{pl2!r} != {{'a':2,'b':'sib'}} — "
                               f"Type4_StateLogicViolation")
            else:
                print("[C2] OK: sibling point 2 untouched")

        # ---- (D post-delete: confirmed drop -> 404) ----
        try:
            rt.drop_collection(C)
        except Exception:
            pass
        time.sleep(0.5)
        d_s, d_raw = safe_request("GET", "describe_collection",
                                  path_params={"name": C})
        print(f"[D drop-confirm describe] status={d_s} raw={d_raw[:150]}")
        if d_s != 404:
            print(f"SETUP_ERROR: drop not confirmed (describe={d_s})")
            return "SCRIPT_ERROR"
        r = expect_404("D post-drop", C, {"keys": ["a"], "points": [1]})
        if r == "abort":
            return "SCRIPT_ERROR"
        if r == "defect":
            return "DEFECT_FOUND"

        # ---- (E recreate, measured-only: absent-point target) ----
        ok2, err2 = rt.setup_default(C, 4, "Cosine")
        if not ok2:
            print(f"SETUP_ERROR: recreate failed: {err2}")
            return "SCRIPT_ERROR"
        s_e, raw_e = do_payload_delete("E recreated absent-point", C,
                                       {"keys": ["a"], "points": [1]})
        print(f"[E] measured only, NOT adjudicated (SKIPPED: by-design per "
              f"threat_model — idempotent-delete family over absent point "
              f"targets): status={s_e}")

        # ---- (F clean-slate: fresh upsert -> delete -> exactly empty) ----
        u_s2, u_raw2 = safe_request("PUT", "upsert_points",
                                    path_params={"name": C},
                                    body={"points": [
                                        {"id": 1,
                                         "vector": [1.0, 2.0, 3.0, 4.0],
                                         "payload": {"fresh": True}}]},
                                    query_params={"wait": "true"})
        print(f"[F fresh upsert] status={u_s2} raw={u_raw2[:150]}")
        if u_s2 not in (200, 201):
            print("SETUP_ERROR: fresh upsert failed")
            return "SCRIPT_ERROR"
        pf = get_point("F baseline", C, 1)
        if pf is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        basevec = pf.get("vector") if isinstance(pf.get("vector"), list) else None
        s_f, raw_f = do_payload_delete("F delete ['fresh']", C,
                                       {"points": [1], "keys": ["fresh"]})
        if s_f == 0:
            liveness("F")
            return "SCRIPT_ERROR"
        if 500 <= s_f <= 599:
            if liveness("F"):
                DEFECTS.append(f"(F) delete returned {s_f} with service alive "
                               f"— Type3_RuntimeFailure — raw={raw_f[:150]}")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if s_f != 200:
            DEFECTS.append(f"(F) delete returned {s_f} (expected 200) — "
                           f"Type4_StateLogicViolation")
        else:
            check_delete_envelope("F", raw_f)
        time.sleep(0.4)
        pf2 = get_point("F readback", C, 1)
        if pf2 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        plf, okf = pay_dict(pf2)
        if not okf:
            DEFECTS.append("(F) payload is not an object — "
                           "Type4_StateLogicViolation")
        elif len(plf) != 0:
            DEFECTS.append(f"(F) payload {plf!r} not exactly empty after "
                           f"deleting ['fresh'] — zombie keys leaking across "
                           f"collection incarnations — "
                           f"Type4_StateLogicViolation")
        else:
            print("[F] OK: payload exactly empty — clean slate")
        if basevec is not None and not vec_eq(pf2.get("vector"), basevec):
            DEFECTS.append("(F) vector changed across recreate+delete — "
                           "Type4_StateLogicViolation")

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
