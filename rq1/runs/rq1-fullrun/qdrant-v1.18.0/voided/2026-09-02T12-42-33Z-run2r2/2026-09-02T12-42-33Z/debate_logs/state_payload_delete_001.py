#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_delete_001
# strategy: count_consistency
# endpoint: payload+delete
# constraint_ids: qdrant_state_payload_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 (CRUD-then-readback + count consistency) against
  qdrant_state_payload_delete_001: "only the listed payload keys are
  removed; unlisted keys persist". The key-deletion mutation is judged
  on four channels after a wait=true delete of keys ["city","score"]
  from an explicit points subset [1,2,3] of a 6-point collection where
  every point carries the SAME 4-key payload:
  (B baseline) scroll with_payload+with_vector -> 6 points, each with
      the exact 4-key payload; the readback vectors are snapshotted as
      BASEVEC (R27 lesson: on Cosine collections the stored vector is
      L2-normalized by-design, so every later vector comparison is
      readback-vs-baseline-readback, NEVER readback-vs-uploaded-raw).
  (D mutation) POST payload+delete {"points":[1,2,3],
      "keys":["city","score"]} wait=true -> 200 with the materialized
      envelope (result: object; result.operation_id integer|null;
      result.status string) — present-but-wrong-typed = shape conflict
      (spec wins).
  (E selective readback, the exact assertion split) targeted ids 1,2,3
      -> payload EXACTLY the unlisted survivors {"tag","note"} with
      their original values (a listed key surviving = under-delete; a
      survivor value mutated = not a pure delete); NON-targeted ids
      4,5,6 -> payload the exact original 4-key dict (any key loss on a
      non-targeted point = over-delete collateral).
  (F vector preservation) all 6 readback vectors equal BASEVEC within
      1e-6 (key deletion is payload-scoped — a changed vector =
      over-reach into the vector storage).
  (G count invariance) exact count stays 6 (key deletion is not point
      deletion).
  Persistence judged via scroll readback after the delete — never via
  the delete response alone.
  [chunk_payload+delete coverage: count_consistency x
   qdrant_state_payload_delete_001 (explicit-points selective key
   deletion + unlisted-key persistence + vector/count invariance)]
Oracle: after a wait=true key-delete of ["city","score"] on points
  [1,2,3] (expect HTTP 200) on a 6-point collection:
  HTTP 200 with result an object (operation_id integer|null, status
  string when present); ids 1-3 payload has exactly the unlisted keys
  {"tag","note"} with original values; ids 4-6 payload equals the
  original 4-key dict; all 6 vectors equal the baseline readback
  vectors (<=1e-6); exact count still 6. A listed key surviving on a
  targeted point, a survivor value changed, any key lost on a
  non-targeted point, a vector change, or a count drift =
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

# payload+delete is not in the runtime PATHS whitelist (verified: create/
# describe/drop/upsert/scroll/count/... are present, payload endpoints are
# not) — register VERBATIM from raw_knowledge api_endpoints[].url:
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


def pay_dict(p):
    """Payload of a scroll point as (dict, ok). Non-dict payload = corrupt."""
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
    PFX = "spd1_" + TS + "_"
    C = PFX + "col"

    IDS = list(range(1, 7))
    LISTED = ["city", "score"]           # keys requested for deletion
    ORIGINAL = {i: {"city": f"c{i}", "score": i, "tag": f"t{i % 2}",
                    "note": f"n{i}"} for i in IDS}
    SURVIVOR = {i: {"tag": ORIGINAL[i]["tag"], "note": ORIGINAL[i]["note"]}
                for i in IDS}

    try:
        # ---- (A setup) create + upsert 6 payload-bearing points ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [float(i), 1.0, 2.0, 3.0],
                "payload": ORIGINAL[i]} for i in IDS]
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[A upsert 6] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"

        # ---- (B baseline readback) 6 points, exact payload; snapshot BASEVEC ----
        base = scroll_map("B baseline", C)
        if base is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if set(base.keys()) != set(IDS):
            print(f"SETUP_ERROR: baseline ids {sorted(base.keys())} != 1..6")
            return "SCRIPT_ERROR"
        for i in IDS:
            pl, okp = pay_dict(base[i])
            if not okp:
                DEFECTS.append(f"(B baseline) point {i} payload is not an "
                               f"object — Type4_StateLogicViolation")
            elif pl != ORIGINAL[i]:
                DEFECTS.append(f"(B baseline) point {i} payload {pl!r} != "
                               f"uploaded {ORIGINAL[i]!r} — "
                               f"Type4_StateLogicViolation")
        BASEVEC = {i: vec_of(base[i]) for i in IDS}
        if any(v is None for v in BASEVEC.values()):
            print("SETUP_ERROR: baseline readback missing vectors")
            return "SCRIPT_ERROR"
        cnt0 = exact_count("C count-before", C)
        if cnt0 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if cnt0 != 6:
            DEFECTS.append(f"(C count-before) expected 6, got {cnt0} — "
                           f"Type4_StateLogicViolation")

        # ---- (D mutation) key-delete on targeted subset [1,2,3], wait=true ----
        d_s, d_raw = safe_request("POST", "payload_delete",
                                  path_params={"collection_name": C},
                                  body={"points": [1, 2, 3], "keys": LISTED},
                                  query_params={"wait": "true"})
        print(f"[D delete keys {LISTED} on 1-3] status={d_s} raw={d_raw[:200]}")
        if d_s == 0:
            liveness("D")
            return "SCRIPT_ERROR"
        if 500 <= d_s <= 599:
            if liveness("D"):
                DEFECTS.append(f"(D delete) returned {d_s} with service alive "
                               f"— Type3_RuntimeFailure — raw={d_raw[:150]} "
                               f"(qdrant_state_payload_delete_001)")
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        if d_s != 200:
            print(f"SETUP_ERROR: payload_delete returned {d_s} — cannot judge "
                  f"state semantics (200-branch adjudicated by "
                  f"state_payload_delete_005)")
            return "SCRIPT_ERROR"
        check_delete_envelope("D delete", d_raw)
        time.sleep(0.5)

        # ---- (E selective readback) listed gone on targets, rest intact ----
        after = scroll_map("E after-delete", C)
        if after is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if set(after.keys()) != set(IDS):
            DEFECTS.append(f"(E readback) point id set changed after "
                           f"key-delete: {sorted(after.keys())} != 1..6 — "
                           f"key deletion must not delete points — "
                           f"Type4_StateLogicViolation")
            after = {k: v for k, v in after.items() if k in ORIGINAL}
        for i in IDS:
            if i not in after:
                continue
            pl, okp = pay_dict(after[i])
            if not okp:
                DEFECTS.append(f"(E) point {i} payload is not an object — "
                               f"Type4_StateLogicViolation")
                continue
            if i in (1, 2, 3):
                for lk in LISTED:
                    if lk in pl:
                        DEFECTS.append(f"(E) TARGETED point {i} still carries "
                                       f"listed key {lk!r} after wait=true "
                                       f"key-delete — payload={pl!r} — "
                                       f"qdrant_state_payload_delete_001 pins "
                                       f"'only the listed payload keys are "
                                       f"removed' — Type4_StateLogicViolation")
                if pl != SURVIVOR[i]:
                    DEFECTS.append(f"(E) TARGETED point {i} survivors "
                                   f"{pl!r} != expected unlisted survivors "
                                   f"{SURVIVOR[i]!r} — delete must leave "
                                   f"unlisted keys untouched — "
                                   f"Type4_StateLogicViolation")
                else:
                    print(f"[E] OK: targeted point {i} keeps exactly "
                          f"unlisted keys {sorted(pl.keys())}")
            else:
                if pl != ORIGINAL[i]:
                    DEFECTS.append(f"(E) NON-targeted point {i} payload "
                                   f"changed by key-delete on [1,2,3]: "
                                   f"{pl!r} != {ORIGINAL[i]!r} — over-delete "
                                   f"collateral — Type4_StateLogicViolation")
                else:
                    print(f"[E] OK: non-targeted point {i} payload intact")

        # ---- (F vector preservation, readback vs BASEVEC readback) ----
        for i in IDS:
            if i in after and not vec_eq(vec_of(after[i]), BASEVEC[i]):
                DEFECTS.append(f"(F) point {i} vector changed after payload "
                               f"key-delete: {vec_of(after[i])!r} != baseline "
                               f"readback {BASEVEC[i]!r} — key deletion is "
                               f"payload-scoped — Type4_StateLogicViolation")
        print("[F] vector preservation checked for all readback points")

        # ---- (G count invariance) ----
        cnt1 = exact_count("G count-after", C)
        if cnt1 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if cnt1 != cnt0:
            DEFECTS.append(f"(G) exact count changed after key-delete: "
                           f"{cnt1} != {cnt0} — key deletion must not delete "
                           f"points — Type4_StateLogicViolation")

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
