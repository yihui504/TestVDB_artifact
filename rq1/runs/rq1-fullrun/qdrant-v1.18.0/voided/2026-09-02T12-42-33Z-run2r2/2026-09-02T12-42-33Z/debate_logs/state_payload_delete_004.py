#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_delete_004
# strategy: count_consistency
# endpoint: payload+delete
# constraint_ids: qdrant_state_payload_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 variant (filter-targeted selective key deletion) against
  qdrant_state_payload_delete_001: "only the listed payload keys are
  removed; unlisted keys persist". The chunk's request_required_paths
  carries TWO targeting branches — explicit `points` (covered by
  state_payload_delete_001) and `filter` (filter.must.key etc.). This
  script mutates the SELECTOR from explicit ids to a predicate, the
  mutation point where over-delete/under-delete risk is highest (the
  storage layer must resolve the predicate to exactly the matching ids
  AND delete only the listed keys on them):
  (A setup) 8 points; payload {"grp": "a"|"b", "n": i, "keep": "k"} —
      ids 0-3 grp=a, ids 4-7 grp=b; baseline readback snapshots the
      stored vectors (R27 lesson: readback-vs-baseline-readback only —
      Cosine normalizes by-design).
  (B keyword filter) delete keys ["n"] with
      {"filter":{"must":[{"key":"grp","match":{"value":"a"}}]}}
      wait=true -> 200; readback: grp=a ids 0-3 payload EXACTLY
      {"grp","keep"} with original values; grp=b ids 4-7 payload the
      EXACT original 3-key dict; count 8.
  (D restore) re-upsert all 8 points with the original payloads
      (wait=true) -> verify all 8 payloads restored exactly; take a
      FRESH vector snapshot after the restore (all later vector
      comparisons use the latest snapshot).
  (E numeric filter) delete keys ["grp"] with
      {"filter":{"must":[{"key":"n","range":{"gte":6}}]}} -> ids 6,7
      payload EXACTLY {"n","keep"}; ids 0-5 intact; count 8.
  (F no-match filter) delete keys ["keep"] with
      {"filter":{"must":[{"key":"grp","match":{"value":"zzz"}}]}} ->
      200 on a valid filter with ZERO matches; readback state must be
      BIT-UNCHANGED (a no-match delete that mutates anything = phantom
      wipe).
  Under-delete (a matching point keeps a listed key), over-delete (a
  non-matching point loses any key, or a matching point loses an
  unlisted key), survivor-value mutation, and count drift are all
  Type4_StateLogicViolation. Filter grammar grounded in contract
  data_types: Filter {should?, min_should?, must?, must_not?};
  FieldCondition {key, match|range}; Match oneOf value.
  [chunk_payload+delete coverage: count_consistency x
   qdrant_state_payload_delete_001 (filter-branch selective key
   deletion + no-match zero-mutation)]
Oracle: keyword filter delete of ["n"] (expect HTTP 200) removes "n"
  EXACTLY from the grp=a points (payload {"grp","keep"} with original
  values) leaving grp=b payloads byte-equal; numeric range gte=6
  delete of ["grp"] strips "grp" EXACTLY from ids 6,7; the no-match
  filter returns 200 and mutates nothing; exact count stays 8 and
  vectors equal the latest readback snapshot after every delete.
  Under-delete, over-delete, any mutation by the no-match filter, or
  count drift = Type4_StateLogicViolation; 5xx only counts when
  /healthz confirms liveness (Type3_RuntimeFailure).
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

N = 8
IDS = list(range(N))
ORIGINAL = {i: {"grp": "a" if i < 4 else "b", "n": i, "keep": "k"} for i in IDS}

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


def snapshot(tag, coll):
    """scroll readback -> (payload_map, vec_map) or (None, None) on abort."""
    m = scroll_map(tag, coll)
    if m is None:
        return None, None
    return ({i: pay_dict(m[i])[0] for i in m},
            {i: vec_of(m[i]) for i in m})


def check_vs_expected(tag, pays, expected):
    """expected: {id: exact payload dict}. Adjudicates payload + id set."""
    if set(pays.keys()) != set(IDS):
        DEFECTS.append(f"({tag}) point id set {sorted(pays.keys())} != 0..{N-1}"
                       f" — key deletion must not delete points — "
                       f"Type4_StateLogicViolation")
    for i in IDS:
        if i not in expected:
            continue
        if i not in pays:
            continue
        if pays[i] != expected[i]:
            DEFECTS.append(f"({tag}) point {i} payload {pays[i]!r} != expected "
                           f"{expected[i]!r} — under-/over-delete on the "
                           f"filter branch — Type4_StateLogicViolation")
        else:
            print(f"[{tag}] OK: point {i} payload == {pays[i]!r}")
    return True


def do_filter_delete(tag, coll, keys, must):
    """POST payload+delete with a filter selector, wait=true. Returns
    'ok' | 'defect' | None(abort)."""
    s, raw = safe_request("POST", "payload_delete",
                          path_params={"collection_name": coll},
                          body={"keys": keys,
                                "filter": {"must": must}},
                          query_params={"wait": "true"})
    print(f"[{tag} filter-delete keys={keys}] status={s} raw={str(raw)[:200]}")
    if s == 0:
        liveness(tag)
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) filter-delete returned {s} with service "
                           f"alive — Type3_RuntimeFailure — "
                           f"raw={str(raw)[:150]}")
        return "defect"
    if s != 200:
        print(f"SETUP_ERROR: filter-delete returned {s}")
        return None
    return "ok"


def check_vectors(tag, m, basevec):
    for i in IDS:
        if i in m and i in basevec and basevec[i] is not None:
            v = vec_of(m[i])
            if not vec_eq(v, basevec[i]):
                DEFECTS.append(f"({tag}) point {i} vector changed after "
                               f"payload key-delete: {v!r} != baseline "
                               f"readback {basevec[i]!r} — "
                               f"Type4_StateLogicViolation")


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spd4_" + TS + "_"
    C = PFX + "col"

    pts = [{"id": i, "vector": [float(i) + 1.0, 1.0, 2.0, 3.0],
            "payload": ORIGINAL[i]} for i in IDS]

    try:
        # ---- (A setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[A upsert 8] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"

        pays0, vecs0 = snapshot("A baseline", C)
        if pays0 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        for i in IDS:
            if pays0.get(i) != ORIGINAL[i]:
                DEFECTS.append(f"(A baseline) point {i} payload "
                               f"{pays0.get(i)!r} != {ORIGINAL[i]!r} — "
                               f"Type4_StateLogicViolation")
        cnt0 = exact_count("A count", C)
        if cnt0 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if cnt0 != N:
            DEFECTS.append(f"(A) expected count {N}, got {cnt0} — "
                           f"Type4_StateLogicViolation")

        # ---- (B keyword filter: delete ["n"] where grp == a) ----
        r = do_filter_delete("B grp=a", C, ["n"],
                             [{"key": "grp", "match": {"value": "a"}}])
        if r is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if r == "defect":
            return "DEFECT_FOUND"
        time.sleep(0.4)
        m = scroll_map("B readback", C)
        if m is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        pays_b = {i: pay_dict(m[i])[0] for i in m}
        exp_b = {i: ({"grp": ORIGINAL[i]["grp"], "keep": "k"} if i < 4
                     else dict(ORIGINAL[i])) for i in IDS}
        check_vs_expected("B", pays_b, exp_b)
        check_vectors("B", m, vecs0)
        cb = exact_count("B count", C)
        if cb is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if cb != cnt0:
            DEFECTS.append(f"(B) count {cb} != {cnt0} — "
                           f"Type4_StateLogicViolation")

        # ---- (D restore) re-upsert all 8 original payloads ----
        u_s2, u_raw2 = safe_request("PUT", "upsert_points",
                                    path_params={"name": C},
                                    body={"points": pts},
                                    query_params={"wait": "true"})
        print(f"[D restore upsert] status={u_s2} raw={u_raw2[:150]}")
        if u_s2 not in (200, 201):
            print("SETUP_ERROR: restore upsert failed")
            return "SCRIPT_ERROR"
        time.sleep(0.4)
        m2 = scroll_map("D restore readback", C)
        if m2 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        pays_d = {i: pay_dict(m2[i])[0] for i in m2}
        for i in IDS:
            if pays_d.get(i) != ORIGINAL[i]:
                DEFECTS.append(f"(D restore) point {i} payload "
                               f"{pays_d.get(i)!r} != {ORIGINAL[i]!r} — "
                               f"restore failed — "
                               f"Type4_StateLogicViolation")
        vecs_d = {i: vec_of(m2[i]) for i in m2}  # fresh snapshot after reset

        # ---- (E numeric filter: delete ["grp"] where n >= 6) ----
        r = do_filter_delete("E n>=6", C, ["grp"],
                             [{"key": "n", "range": {"gte": 6}}])
        if r is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if r == "defect":
            return "DEFECT_FOUND"
        time.sleep(0.4)
        m3 = scroll_map("E readback", C)
        if m3 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        pays_e = {i: pay_dict(m3[i])[0] for i in m3}
        exp_e = {i: ({"n": i, "keep": "k"} if i >= 6 else dict(ORIGINAL[i]))
                 for i in IDS}
        check_vs_expected("E", pays_e, exp_e)
        check_vectors("E", m3, vecs_d)
        ce = exact_count("E count", C)
        if ce is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if ce != cnt0:
            DEFECTS.append(f"(E) count {ce} != {cnt0} — "
                           f"Type4_StateLogicViolation")

        # ---- (F no-match filter: delete ["keep"] where grp == zzz) ----
        pre_f = {i: pay_dict(m3[i])[0] for i in m3}  # state right before F
        r = do_filter_delete("F grp=zzz", C, ["keep"],
                             [{"key": "grp", "match": {"value": "zzz"}}])
        if r is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if r == "defect":
            return "DEFECT_FOUND"
        time.sleep(0.4)
        m4 = scroll_map("F readback", C)
        if m4 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        pays_f = {i: pay_dict(m4[i])[0] for i in m4}
        if pays_f != pre_f:
            diff = [i for i in IDS if pays_f.get(i) != pre_f.get(i)]
            DEFECTS.append(f"(F) no-match filter mutated points {diff} — "
                           f"a zero-match delete must be a no-op (phantom "
                           f"wipe) — Type4_StateLogicViolation")
        else:
            print("[F] OK: no-match filter mutated nothing")
        check_vectors("F", m4, vecs_d)
        cf = exact_count("F count", C)
        if cf is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if cf != cnt0:
            DEFECTS.append(f"(F) count {cf} != {cnt0} — "
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
