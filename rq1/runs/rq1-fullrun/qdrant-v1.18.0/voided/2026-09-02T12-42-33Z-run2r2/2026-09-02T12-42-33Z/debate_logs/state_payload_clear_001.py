#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_clear_001
# strategy: count_consistency
# endpoint: payload+clear
# constraint_ids: qdrant_state_payload_clear_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/clear-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 (CRUD-then-COUNT + readback) against
  qdrant_state_payload_clear_001: "clear removes all payload keys of the
  targeted points" / "after clear, targeted points carry no payload keys".
  The state mutation is judged on three channels after a wait=true clear
  of an explicit points subset [1,2,3] of a 6-point collection:
  (B baseline) scroll with_payload+with_vector -> 6 points, each with the
      exact 3-key payload and exact vector uploaded (setup gate).
  (D mutation) POST payload+clear {"points":[1,2,3]} wait=true -> 200
      with the materialized envelope (result: object; result.operation_id
      integer|null; result.status string) — present-but-wrong-typed = shape
      conflict (spec wins).
  (E selective readback) targeted ids 1,2,3 -> payload empty (0 keys);
      NON-targeted ids 4,5,6 -> payload still the exact original dict
      (over-clear = collateral state destruction).
  (F vector preservation) all 6 vectors byte-equal to the uploaded ones
      (clear is payload-scoped — a changed vector = over-reach).
  (G count invariance) exact count stays 6 (clear is not delete).
  Persistence judged via scroll/point readback after clear (payloads gone,
  vectors intact, count unchanged) — never via the clear response alone.
  [chunk_payload+clear coverage: count_consistency x
   qdrant_state_payload_clear_001 (explicit-points selective wipe +
   vector/count invariance)]
Oracle: after a wait=true clear of points [1,2,3] (expect HTTP 200)
  on a 6-point collection:
  HTTP 200 with result an object (operation_id integer|null, status
  string when present); ids 1-3 payload has exactly 0 keys; ids 4-6
  payload equals the original 3-key dict; all 6 vectors unchanged
  (<=1e-6); exact count still 6. Any residual key on a targeted point,
  any payload/vector change on a non-targeted point, or a count drift =
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

# payload+clear is not in the runtime PATHS whitelist (verified: create/
# describe/drop/upsert/scroll/count/... are present, payload endpoints are
# not) — register VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "payload+clear", "method": "POST",
#    "url": "/collections/{collection_name}/points/payload/clear"}
rt.PATHS["payload_clear"] = "/collections/{collection_name}/points/payload/clear"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'payload' in k]}")
if rt.PATHS.get("payload_clear") != "/collections/{collection_name}/points/payload/clear":
    print("VERDICT: SCRIPT_ERROR - payload_clear URL registration failed")
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
    """Spec-typed envelope check of a 200 clear body.
    response_shape pins result: object, result.operation_id: integer|null,
    result.status: string."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        DEFECTS.append(f"({tag}) 200 clear body is not JSON — raw={str(raw)[:150]}")
        return
    if not isinstance(b, dict):
        DEFECTS.append(f"({tag}) 200 clear body is not an object — raw={str(raw)[:150]}")
        return
    res = b.get("result")
    if not isinstance(res, dict):
        DEFECTS.append(f"({tag}) 200 clear body result is not an object "
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
        print(f"[{tag}] measured: result.status absent in clear envelope")


def pay_dict(p):
    """Payload of a scroll point as (dict, ok). Non-dict payload = corrupt."""
    pl = p.get("payload")
    if pl is None:
        return {}, True
    if isinstance(pl, dict):
        return pl, True
    return {}, False


def vec_ok(p, expected, tol=1e-6):
    v = p.get("vector")
    if not isinstance(v, list) or len(v) != len(expected):
        return False
    return all(isinstance(a, (int, float)) and abs(a - b) <= tol
               for a, b in zip(v, expected))


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


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spc1_" + TS + "_"
    C = PFX + "col"

    ORIGINAL = {i: {"city": f"c{i}", "score": i, "tag": f"t{i % 2}"}
                for i in range(1, 7)}
    VECTORS = {i: [float(i), 1.0, 2.0, 3.0] for i in range(1, 7)}

    try:
        # ---- (A setup) create + upsert 6 payload-bearing points ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": VECTORS[i], "payload": ORIGINAL[i]}
               for i in range(1, 7)]
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[A upsert 6] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"

        # ---- (B baseline readback) 6 points, exact payload + vector ----
        base = scroll_map("B baseline", C)
        if base is None:
            return "SCRIPT_ERROR"
        if set(base.keys()) != set(range(1, 7)):
            print(f"SETUP_ERROR: baseline ids {sorted(base.keys())} != 1..6")
            return "SCRIPT_ERROR"
        for i in range(1, 7):
            pl, okp = pay_dict(base[i])
            if not okp:
                DEFECTS.append(f"(B baseline) point {i} payload is not an "
                               f"object — Type4_StateLogicViolation")
            elif pl != ORIGINAL[i]:
                DEFECTS.append(f"(B baseline) point {i} payload {pl!r} != "
                               f"uploaded {ORIGINAL[i]!r} — "
                               f"Type4_StateLogicViolation")
        cnt0 = exact_count("C count-before", C)
        if cnt0 is None:
            return "SCRIPT_ERROR"
        if cnt0 != 6:
            DEFECTS.append(f"(C count-before) expected 6, got {cnt0} — "
                           f"Type4_StateLogicViolation")

        # ---- (D mutation) clear targeted subset [1,2,3], wait=true ----
        d_s, d_raw = safe_request("POST", "payload_clear",
                                  path_params={"collection_name": C},
                                  body={"points": [1, 2, 3]},
                                  query_params={"wait": "true"})
        print(f"[D clear 1-3] status={d_s} raw={d_raw[:200]}")
        if d_s == 0:
            liveness("D")
            return "SCRIPT_ERROR"
        if 500 <= d_s <= 599:
            if liveness("D"):
                DEFECTS.append(f"(D clear) returned {d_s} with service alive "
                               f"— Type3_RuntimeFailure — raw={d_raw[:150]} "
                               f"(qdrant_state_payload_clear_001)")
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        if d_s != 200:
            print(f"SETUP_ERROR: clear returned {d_s} — cannot judge state "
                  f"semantics (200-branch adjudicated by "
                  f"state_payload_clear_005)")
            return "SCRIPT_ERROR"
        check_clear_envelope("D clear", d_raw)
        time.sleep(0.5)

        # ---- (E selective readback) targeted empty, non-targeted intact ----
        after = scroll_map("E after-clear", C)
        if after is None:
            return "SCRIPT_ERROR"
        if set(after.keys()) != set(range(1, 7)):
            DEFECTS.append(f"(E readback) point id set changed after clear: "
                           f"{sorted(after.keys())} != 1..6 — clear must not "
                           f"delete points — Type4_StateLogicViolation")
            after = {k: v for k, v in after.items() if k in ORIGINAL}
        for i in range(1, 7):
            if i not in after:
                continue
            pl, okp = pay_dict(after[i])
            if not okp:
                DEFECTS.append(f"(E) point {i} payload is not an object — "
                               f"Type4_StateLogicViolation")
                continue
            if i in (1, 2, 3):
                if len(pl) != 0:
                    DEFECTS.append(f"(E) TARGETED point {i} still carries "
                                   f"payload keys {sorted(pl.keys())} after "
                                   f"wait=true clear — "
                                   f"qdrant_state_payload_clear_001 pins "
                                   f"'targeted points carry no payload keys' "
                                   f"— Type4_StateLogicViolation")
                else:
                    print(f"[E] OK: targeted point {i} payload empty")
            else:
                if pl != ORIGINAL[i]:
                    DEFECTS.append(f"(E) NON-targeted point {i} payload "
                                   f"changed by clear of [1,2,3]: {pl!r} != "
                                   f"{ORIGINAL[i]!r} — collateral wipe — "
                                   f"Type4_StateLogicViolation")
                else:
                    print(f"[E] OK: non-targeted point {i} payload intact")

        # ---- (F vector preservation) ----
        for i in range(1, 7):
            if i in after and not vec_ok(after[i], VECTORS[i]):
                DEFECTS.append(f"(F) point {i} vector changed after payload "
                               f"clear: {after[i].get('vector')!r} != "
                               f"{VECTORS[i]} — clear is payload-scoped — "
                               f"Type4_StateLogicViolation")
        print("[F] vector preservation checked for all readback points")

        # ---- (G count invariance) ----
        cnt1 = exact_count("G count-after", C)
        if cnt1 is None:
            return "SCRIPT_ERROR"
        if cnt1 != cnt0:
            DEFECTS.append(f"(G) exact count changed after clear: {cnt1} != "
                           f"{cnt0} — clear must not delete points — "
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
