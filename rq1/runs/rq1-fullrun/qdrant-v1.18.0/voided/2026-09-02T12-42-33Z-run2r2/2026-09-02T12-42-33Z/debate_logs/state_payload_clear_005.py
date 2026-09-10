#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_clear_005
# strategy: delete_consistency
# endpoint: payload+clear
# constraint_ids: qdrant_behavioral_payload_clear_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/clear-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 2 (post-DELETE state consistency) against the
  behavioral face qdrant_behavioral_payload_clear_001: "clear_payload
  returns HTTP 200 on valid targets; missing collection returns 404".
  The clear verdict must track the collection lifecycle exactly over
  the {collection_name} path:
  (A negative) never-created unique name -> HTTP 404 EXACTLY (a 200
      here reports success for a collection that never existed =
      phantom ack; a 500 instead of 404 = the face cannot express
      absence; any other code violates the pinned 404 branch).
  (B setup) create + upsert 2 payload-bearing points -> 200 (gate).
  (C positive) live collection, clear {"points":[1]} wait=true ->
      HTTP 200 with the materialized envelope (result: object;
      result.operation_id integer|null; result.status string), AND the
      200 must not lie: point 1 readback payload empty while sibling
      point 2 keeps its exact payload.
  (D post-delete) drop the collection (confirmed) -> clear the SAME
      name -> HTTP 404 EXACTLY (a zombie 200 after a confirmed delete =
      the delete did not retire the write face).
  (E recreate, measured-only) recreate the same name; clear on the
      empty recreation targets a point that does not exist — status
      printed, NOT adjudicated: idempotent-update semantics over
      absent point targets is the by-design family of "Idempotent
      DELETE returns 200 even if point doesn't exist"
      (SKIPPED: by-design per threat_model).
  (F clean-slate) fresh upsert id=1 {"fresh":true} -> clear -> 200 ->
      readback payload EXACTLY empty; any pre-drop "old" key
      reappearing = zombie state leaking across incarnations.
  [chunk_payload+clear coverage: delete_consistency x
   qdrant_behavioral_payload_clear_001 (never-created 404 + valid 200
   envelope + post-delete 404 + recreate clean-slate)]
Oracle: never-created name -> HTTP 404; live collection -> HTTP 200
  with result an object (operation_id integer|null, status string when
  present) and the targeted point actually payload-free while its
  sibling keeps its payload; after a confirmed drop -> HTTP 404 again;
  after recreate + fresh upsert + clear -> payload exactly empty with
  no pre-drop key resurrection. 200 on a missing collection, 404 on a
  live collection, or any non-404 on the missing branch =
  Type4_StateLogicViolation; 5xx = Type3 only when /healthz confirms
  liveness.
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

# payload+clear is not in the runtime PATHS whitelist — register VERBATIM
# from raw_knowledge api_endpoints[].url:
#   {"path": "payload+clear", "method": "POST",
#    "url": "/collections/{collection_name}/points/payload/clear"}
rt.PATHS["payload_clear"] = "/collections/{collection_name}/points/payload/clear"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'payload' in k]}")
if rt.PATHS.get("payload_clear") != "/collections/{collection_name}/points/payload/clear":
    print("VERDICT: SCRIPT_ERROR - payload_clear URL registration failed")
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


def do_clear(tag, coll, points):
    """One clear call. Returns '404'/'200'/'DEF'/'abort'."""
    s, raw = safe_request("POST", "payload_clear",
                          path_params={"collection_name": coll},
                          body={"points": points},
                          query_params={"wait": "true"})
    print(f"[{tag}] status={s} raw={raw[:220]}")
    if s == 0:
        liveness(tag)
        return "abort"
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) clear returned {s} with service alive — "
                           f"Type3_RuntimeFailure — raw={raw[:150]} "
                           f"(qdrant_behavioral_payload_clear_001)")
            return "DEF"
        return "abort"
    if s == 404:
        return "404"
    if s == 200:
        check_clear_envelope(tag, raw)
        return "200"
    DEFECTS.append(f"({tag}) clear returned {s} — the assertion pins only "
                   f"200 (valid target) / 404 (missing collection) — "
                   f"Type4_StateLogicViolation — raw={raw[:150]}")
    return "DEF"


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
    return pl


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spc5_" + TS + "_"
    C = PFX + "col"
    NEVER = PFX + "never_created"
    VEC = [1.0, 1.0, 2.0, 3.0]

    try:
        # ---- (A negative) never-created unique name -> 404 ----
        r = do_clear("A never-created", NEVER, [1])
        if r == "abort":
            return "SCRIPT_ERROR"
        if r == "DEF":
            return "DEFECT_FOUND"
        if r == "404":
            print("[A] OK: 404 (missing collection branch)")
        elif r == "200":
            DEFECTS.append("(A) clear returned 200 for a NEVER-CREATED "
                           "collection — phantom ack — "
                           "qdrant_behavioral_payload_clear_001 pins 404 for "
                           "a missing collection — Type4_StateLogicViolation")

        # ---- (B setup) create + 2 payload-bearing points ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": [
                                      {"id": 1, "vector": VEC,
                                       "payload": {"old": 1}},
                                      {"id": 2, "vector": [2.0, 1.0, 2.0, 3.0],
                                       "payload": {"keep": 2}}]},
                                  query_params={"wait": "true"})
        print(f"[B upsert 2] status={u_s} raw={u_raw[:150]}")
        if u_s not in (200, 201):
            liveness("B")
            return "SCRIPT_ERROR"

        # ---- (C positive) live collection -> 200 + envelope + real state ----
        r = do_clear("C live clear pt1", C, [1])
        if r == "abort":
            return "SCRIPT_ERROR"
        if r == "DEF":
            return "DEFECT_FOUND"
        if r == "404":
            DEFECTS.append("(C) clear returned 404 for a LIVE collection — "
                           "the write face lies about state — "
                           "qdrant_behavioral_payload_clear_001 pins HTTP "
                           "200 on valid targets — Type4_StateLogicViolation")
        elif r == "200":
            pl1 = read_point("C readback pt1", C, 1)
            pl2 = read_point("C readback pt2", C, 2)
            if pl1 is None or pl2 is None:
                return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
            if len(pl1) != 0:
                DEFECTS.append(f"(C) 200 ack but point 1 still carries "
                               f"payload keys {sorted(pl1.keys())} — the 200 "
                               f"is a lie — Type4_StateLogicViolation")
            else:
                print("[C] OK: 200 + point 1 payload actually empty")
            if pl2 != {"keep": 2}:
                DEFECTS.append(f"(C) sibling point 2 payload {pl2!r} != "
                               f"{{'keep': 2}} — collateral wipe — "
                               f"Type4_StateLogicViolation")
            else:
                print("[C] OK: sibling point 2 payload intact")

        # ---- (D post-delete) confirmed drop -> 404 ----
        d_s, d_raw = safe_request("DELETE", "drop_collection",
                                  path_params={"name": C},
                                  query_params={"timeout": "30"})
        print(f"[D drop] status={d_s} raw={d_raw[:150]}")
        if d_s != 200:
            print(f"SETUP_ERROR: drop returned {d_s} — cannot judge "
                  f"post-delete clear")
            return "SCRIPT_ERROR"
        r = do_clear("D post-delete", C, [1])
        if r == "abort":
            return "SCRIPT_ERROR"
        if r == "DEF":
            return "DEFECT_FOUND"
        if r == "404":
            print("[D] OK: 404 after confirmed delete")
        elif r == "200":
            DEFECTS.append("(D) clear returned 200 for a DROPPED collection "
                           "— zombie ack after confirmed delete — "
                           "Type4_StateLogicViolation")

        # ---- (E recreate, measured-only: absent point target) ----
        f_s, f_raw = safe_request("PUT", "create_collection",
                                  path_params={"name": C},
                                  body={"vectors": {"size": 4,
                                                    "distance": "Cosine"}})
        print(f"[E recreate] status={f_s} raw={f_raw[:150]}")
        if f_s != 200:
            print(f"SETUP_ERROR: recreate returned {f_s}")
            return "SCRIPT_ERROR"
        e_s, e_raw = safe_request("POST", "payload_clear",
                                  path_params={"collection_name": C},
                                  body={"points": [1]},
                                  query_params={"wait": "true"})
        print(f"[E clear on empty recreation] MEASURED status={e_s} "
              f"raw={str(e_raw)[:200]} — SKIPPED: by-design per threat_model "
              f"(idempotent-update family over an absent point target, cf. "
              f"idempotent DELETE on absent point) — not adjudicated")

        # ---- (F clean-slate: fresh payload cleared, no zombie keys) ----
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": [{"id": 1, "vector": VEC,
                                                    "payload": {"fresh": True}}]},
                                  query_params={"wait": "true"})
        print(f"[F upsert fresh] status={u_s} raw={u_raw[:150]}")
        if u_s not in (200, 201):
            liveness("F")
            return "SCRIPT_ERROR"
        r = do_clear("F clear fresh", C, [1])
        if r == "abort":
            return "SCRIPT_ERROR"
        if r == "DEF":
            return "DEFECT_FOUND"
        if r != "200":
            print(f"SETUP_ERROR: fresh clear returned non-200 ({r})")
            return "SCRIPT_ERROR"
        pl = read_point("F readback", C, 1)
        if pl is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if "old" in pl:
            DEFECTS.append(f"(F) pre-drop payload key 'old' RESURRECTED on "
                           f"the recreated collection — zombie state leaking "
                           f"across incarnations — Type4_StateLogicViolation "
                           f"— payload={pl!r}")
        elif len(pl) != 0:
            DEFECTS.append(f"(F) point 1 payload {pl!r} not empty after "
                           f"fresh clear — Type4_StateLogicViolation")
        else:
            print("[F] OK: clean-slate — payload exactly empty, no zombie keys")

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
