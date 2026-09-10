#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_clear_004
# strategy: count_consistency
# endpoint: payload+clear
# constraint_ids: qdrant_state_payload_clear_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/clear-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 variant (filter-targeted selective wipe) against
  qdrant_state_payload_clear_001: "clear removes all payload keys of the
  TARGETED points". The chunk's request_required_paths carries TWO
  targeting branches — explicit `points` (covered by
  state_payload_clear_001) and `filter` (filter.must.key etc.). This
  script mutates the SELECTOR from explicit ids to a predicate, the
  mutation point where over-clear/under-clear risk is highest (the
  storage layer must resolve the predicate to exactly the matching ids):
  (A setup) 8 points; payload {"grp": "a"|"b", "n": i}.
  (B keyword filter) clear {"filter":{"must":[{"key":"grp",
      "match":{"value":"a"}}]}} wait=true -> 200; readback: grp=a ids
      0-3 payload EMPTY, grp=b ids 4-7 payload EXACT original; count 8.
  (D restore) per-point full overwrite wait=true; verify all 8 restored.
  (E numeric filter) clear {"filter":{"must":[{"key":"n",
      "range":{"gte":6}}]}} -> ids 6,7 empty; 0-5 intact; count 8.
  (F no-match filter) clear {"filter":{"must":[{"key":"grp",
      "match":{"value":"zzz"}}]}} -> 200 on a valid target with ZERO
      matches; readback state must be BIT-UNCHANGED (a no-match clear
      that mutates anything = phantom wipe).
  Under-clear (a matching point keeps a key), over-clear (a non-matching
  point loses its payload), and count drift are all
  Type4_StateLogicViolation. Filter grammar grounded in contract
  data_types: Filter {should?, min_should?, must?, must_not?};
  FieldCondition {key, match|range}; Match oneOf value.
  [chunk_payload+clear coverage: count_consistency x
   qdrant_state_payload_clear_001 (filter-branch selective wipe +
   no-match zero-mutation)]
Oracle: keyword filter clear (expect HTTP 200) empties EXACTLY the
  grp=a points (0 payload keys) leaving
  grp=b payloads byte-equal; numeric range gte=6 clears EXACTLY ids
  6,7; the no-match filter returns 200 and mutates nothing; exact count
  stays 8 and vectors unchanged after every clear. Under-clear,
  over-clear, any mutation by the no-match filter, or count drift =
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

# payload+clear / payload+overwrite are not in the runtime PATHS whitelist —
# register VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "payload+clear", "method": "POST",
#    "url": "/collections/{collection_name}/points/payload/clear"}
#   {"path": "payload+overwrite", "method": "PUT",
#    "url": "/collections/{collection_name}/points/payload"}
rt.PATHS["payload_clear"] = "/collections/{collection_name}/points/payload/clear"
rt.PATHS["payload_overwrite"] = "/collections/{collection_name}/points/payload"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'payload' in k]}")
if (rt.PATHS.get("payload_clear") != "/collections/{collection_name}/points/payload/clear"
        or rt.PATHS.get("payload_overwrite") != "/collections/{collection_name}/points/payload"):
    print("VERDICT: SCRIPT_ERROR - payload endpoint URL registration failed")
    sys.exit(2)

N = 8
IDS = list(range(N))
ORIG = {i: {"grp": "a" if i < 4 else "b", "n": i} for i in IDS}
VECTORS = {i: [float(i) + 1.0, 1.0, 2.0, 3.0] for i in IDS}

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


def pay_dict(p):
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


def filter_clear(tag, coll, filt):
    s, raw = safe_request("POST", "payload_clear",
                          path_params={"collection_name": coll},
                          body={"filter": filt},
                          query_params={"wait": "true"})
    print(f"[{tag}] status={s} raw={raw[:220]}")
    if s == 0:
        liveness(tag)
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) filter clear returned {s} with service "
                           f"alive — Type3_RuntimeFailure — raw={raw[:150]}")
            return "DEF"
        return None
    if s != 200:
        print(f"SETUP_ERROR: filter clear returned {s} — cannot judge state")
        return None
    check_clear_envelope(tag, raw)
    return "OK"


def judge_selective(tag, m, expect_empty, expect_intact, snapshot):
    """expect_empty/expect_intact: id lists; snapshot: {id: payload-before}."""
    for i in expect_empty:
        if i not in m:
            continue
        pl, okp = pay_dict(m[i])
        if not okp:
            DEFECTS.append(f"({tag}) point {i} payload is not an object — "
                           f"Type4_StateLogicViolation")
        elif len(pl) != 0:
            DEFECTS.append(f"({tag}) UNDER-CLEAR: matching point {i} still "
                           f"carries payload keys {sorted(pl.keys())} — "
                           f"qdrant_state_payload_clear_001 — "
                           f"Type4_StateLogicViolation")
    for i in expect_intact:
        if i not in m:
            continue
        pl, okp = pay_dict(m[i])
        if not okp:
            DEFECTS.append(f"({tag}) point {i} payload is not an object — "
                           f"Type4_StateLogicViolation")
        elif pl != snapshot[i]:
            DEFECTS.append(f"({tag}) OVER-CLEAR: non-matching point {i} "
                           f"payload {pl!r} != expected {snapshot[i]!r} — "
                           f"Type4_StateLogicViolation")
    for i in IDS:
        if i in m and not vec_ok(m[i], VECTORS[i]):
            DEFECTS.append(f"({tag}) point {i} vector changed after payload "
                           f"clear — Type4_StateLogicViolation")


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spc4_" + TS + "_"
    C = PFX + "col"

    try:
        # ---- (A setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": VECTORS[i], "payload": ORIG[i]}
               for i in IDS]
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[A upsert {N}] status={u_s} raw={u_raw[:150]}")
        if u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"
        base = scroll_map("A baseline", C)
        if base is None:
            return "SCRIPT_ERROR"
        for i in IDS:
            pl, okp = pay_dict(base.get(i, {}))
            if not okp or pl != ORIG[i]:
                print(f"SETUP_ERROR: baseline point {i} payload {pl!r}")
                return "SCRIPT_ERROR"

        # ---- (B keyword filter clear: grp == "a") ----
        r = filter_clear("B clear grp=a", C,
                         {"must": [{"key": "grp", "match": {"value": "a"}}]})
        if r is None:
            return "SCRIPT_ERROR"
        if r == "DEF":
            return "DEFECT_FOUND"
        time.sleep(0.5)
        m = scroll_map("B readback", C)
        if m is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        judge_selective("B", m, expect_empty=[0, 1, 2, 3],
                        expect_intact=[4, 5, 6, 7], snapshot=ORIG)
        c_b = exact_count("B count", C)
        if c_b is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if c_b != N:
            DEFECTS.append(f"(B) exact count {c_b} != {N} after filter clear "
                           f"— Type4_StateLogicViolation")

        # ---- (D restore via per-point full overwrite) ----
        for i in IDS:
            s, raw = safe_request("PUT", "payload_overwrite",
                                  path_params={"collection_name": C},
                                  body={"payload": ORIG[i], "points": [i]},
                                  query_params={"wait": "true"})
            if s != 200:
                print(f"[D restore pt{i}] status={s} raw={str(raw)[:150]}")
                liveness("D")
                return "SCRIPT_ERROR"
        m = scroll_map("D restore readback", C)
        if m is None:
            return "SCRIPT_ERROR"
        for i in IDS:
            pl, okp = pay_dict(m.get(i, {}))
            if not okp or pl != ORIG[i]:
                print(f"SETUP_ERROR: restore point {i} payload {pl!r} != {ORIG[i]!r}")
                return "SCRIPT_ERROR"
        print("[D] OK: all payloads restored to original")

        # ---- (E numeric range filter clear: n >= 6) ----
        r = filter_clear("E clear n>=6", C,
                         {"must": [{"key": "n", "range": {"gte": 6}}]})
        if r is None:
            return "SCRIPT_ERROR"
        if r == "DEF":
            return "DEFECT_FOUND"
        time.sleep(0.5)
        m = scroll_map("E readback", C)
        if m is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        judge_selective("E", m, expect_empty=[6, 7],
                        expect_intact=[0, 1, 2, 3, 4, 5], snapshot=ORIG)
        c_e = exact_count("E count", C)
        if c_e is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if c_e != N:
            DEFECTS.append(f"(E) exact count {c_e} != {N} after filter clear "
                           f"— Type4_StateLogicViolation")

        # ---- (F no-match filter: zero-mutation oracle) ----
        before_f = scroll_map("F before", C)
        if before_f is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        snap = {i: pay_dict(before_f[i])[0] for i in IDS if i in before_f}
        r = filter_clear("F clear grp=zzz", C,
                         {"must": [{"key": "grp",
                                    "match": {"value": "zzz"}}]})
        if r is None:
            return "SCRIPT_ERROR"
        if r == "DEF":
            return "DEFECT_FOUND"
        time.sleep(0.5)
        m = scroll_map("F after", C)
        if m is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        for i in IDS:
            if i not in m or i not in snap:
                continue
            pl, _ = pay_dict(m[i])
            if pl != snap[i]:
                DEFECTS.append(f"(F) NO-MATCH clear mutated point {i}: "
                               f"{pl!r} != pre-state {snap[i]!r} — phantom "
                               f"wipe — Type4_StateLogicViolation")
        c_f = exact_count("F count", C)
        if c_f is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if c_f != N:
            DEFECTS.append(f"(F) exact count {c_f} != {N} after a no-match "
                           f"clear — Type4_StateLogicViolation")
        if not any("(F)" in d for d in DEFECTS):
            print("[F] OK: no-match clear returned 200 and mutated nothing")

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
