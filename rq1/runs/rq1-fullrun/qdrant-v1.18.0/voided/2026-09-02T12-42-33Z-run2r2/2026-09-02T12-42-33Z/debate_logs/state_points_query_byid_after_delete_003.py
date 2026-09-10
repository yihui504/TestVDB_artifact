#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_byid_after_delete_003
# strategy: delete_consistency
# endpoint: points+query
# constraint_ids: qdrant_state_points_query_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
"""
Attack: post-DELETE by-id lookup consistency (Strategy 2: post-DELETE
  consistency) x qdrant_state_points_query_001 "by-id lookup (query =
  point id) fetches the stored vector of that point". A deleted point has
  NO stored vector, so a by-id query against it must error — serving 200
  means the by-id path read a resurrected/ghost vector. Legs:
  (P) seed ids {1,2,3}; count==3 arithmetic.
  (pos) by-id query on surviving id 2 -> 200 with points (the promise on
  live state).
  (del) DELETE point 1 wait=true -> 200; exact count must drop 3->2;
  single GET of id 1 -> 404 (corroborating the point is really gone).
  (neg1) by-id query {"query": 1} -> 4xx (no stored vector to fetch).
  200 = ghost read — Type4.
  (neg2) by-id query on never-created id 777777 -> 4xx (never-existed ids
  are the stronger ghost case: nothing ever stored).
  (pos2) by-id query on id 3 still -> 200 (survivor unaffected by the
  delete — no over-deletion side-effect on the read path).
  Mutation-point justification (G6): point-level delete is the mutation
  that empties exactly the state slot the by-id lookup dereferences;
  id-level (not collection-level) delete keeps every other observable
  alive, isolating the ghost-read question.
  [chunk_points+query coverage: delete_consistency x
  qdrant_state_points_query_001 (deleted-id ghost read + never-existing-id
  ghost read + survivor unaffected + count arithmetic 3->2)]
Oracle: (pos) by-id query of id 2 -> 200 non-empty; (del) delete -> 200,
  exact count == 2 (3-1 arithmetic), GET id 1 -> 404; (neg1) by-id query
  of deleted id 1 -> HTTP 4xx — 200 = ghost vector served
  (Type4_StateLogicViolation); (neg2) by-id query of never-existing id
  777777 -> 4xx — 200 = phantom state (Type4); (pos2) id 3 -> 200
  non-empty; 5xx with /healthz alive = Type3_RuntimeFailure; transport
  failure -> liveness re-check before any verdict.
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

print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('query', 'upsert_points', 'delete_points', 'get_point', 'count')]}")

DEFECTS = []
ABORT = [False]


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def handle_transport(tag, status, raw):
    if status == 0:
        if not liveness(tag):
            ABORT[0] = True
        return True
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {status} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return True
    return False


def result_of(raw):
    try:
        return json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return None


def upsert(coll, points):
    s, raw = safe_request("PUT", "upsert_points",
                          path_params={"name": coll},
                          body={"points": points},
                          query_params={"wait": "true"})
    print(f"[upsert {len(points)} pts] status={s} raw={str(raw)[:160]}")
    if handle_transport("upsert", s, raw):
        return False
    return s == 200


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if handle_transport(f"{tag} count", s, raw):
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} count returned {s}")
        return None
    res = result_of(raw)
    cnt = res.get("count") if isinstance(res, dict) else None
    if isinstance(cnt, bool) or not isinstance(cnt, int):
        print(f"SETUP_ERROR: {tag} count result.count missing — raw={str(raw)[:200]}")
        return None
    return cnt


def byid_query(tag, coll, pid, limit=3):
    body = {"query": pid, "limit": limit}
    s, raw = safe_request("POST", "query", path_params={"name": coll}, body=body)
    print(f"[{tag} by-id query {pid}] status={s} raw={str(raw)[:240]}")
    if handle_transport(tag, s, raw):
        return s, None
    if s != 200:
        return s, None
    res = result_of(raw)
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        DEFECTS.append(f"({tag}) 200 but result.points is not an array "
                       f"(contract response_shape: result.points array) — "
                       f"raw={str(raw)[:150]}")
        return s, None
    return s, [p.get("id") for p in pts if isinstance(p, dict)]


def delete_point(tag, coll, pid):
    s, raw = safe_request("POST", "delete_points",
                          path_params={"name": coll},
                          body={"points": [pid]},
                          query_params={"wait": "true"})
    print(f"[{tag} delete point {pid}] status={s} raw={str(raw)[:200]}")
    if handle_transport(tag, s, raw):
        return s
    return s


def get_point_status(tag, coll, pid):
    s, raw = safe_request("GET", "get_point",
                          path_params={"name": coll, "point_id": pid},
                          query_params={"with_payload": "false"})
    print(f"[{tag} GET {pid}] status={s} raw={str(raw)[:140]}")
    if handle_transport(f"{tag} GET {pid}", s, raw):
        return s
    return s


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spq3_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def vec(i):
        return [1.0, 0.02 * i, 0.0, 0.0]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        if not upsert(C, [{"id": i, "vector": vec(i)} for i in (1, 2, 3)]):
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if exact_count("seed", C) != 3:
            print("SETUP_ERROR: seed count != 3")
            return "SCRIPT_ERROR"

        # ---- pos: by-id query on a live point (the promise on live state) ----
        s_pos, ids_pos = byid_query("pos-id2", C, 2, limit=3)
        if s_pos != 200 or ids_pos is None:
            print("SETUP_ERROR: positive by-id query not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if not ids_pos:
            DEFECTS.append("(pos) by-id query of live id 2 returned 200 with "
                           "empty result.points — Type4_StateLogicViolation")
        else:
            print(f"[pos] OK: live id 2 by-id query returned {ids_pos}")

        # ---- del: delete point 1 (wait=true) ----
        if delete_point("del-1", C, 1) != 200:
            print("SETUP_ERROR: delete of id 1 not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        cnt = exact_count("after-del", C)
        if cnt is not None and cnt != 2:
            DEFECTS.append(f"(del) exact count {cnt} != 3-1=2 after deleting "
                           f"id 1 — Type4_StateLogicViolation")
        else:
            print("[del] OK: count 3->2 arithmetic holds")
        st = get_point_status("del-1", C, 1)
        if st == 200:
            DEFECTS.append("(del) GET of deleted id 1 returned 200 — zombie "
                           "point — Type4_StateLogicViolation")
        elif st not in (404, 0):
            DEFECTS.append(f"(del) GET of deleted id 1 returned {st} "
                           f"(expected 404) — Type4_StateLogicViolation")

        # ---- neg1: by-id query of the DELETED id must error ----
        s_n1, ids_n1 = byid_query("neg1-deleted-id1", C, 1, limit=3)
        if s_n1 == 200:
            DEFECTS.append(f"(neg1) by-id query of deleted id 1 returned 200 "
                           f"with ids={ids_n1} — ghost stored vector served — "
                           f"Type4_StateLogicViolation")
        elif s_n1 is not None and s_n1 > 0 and not (400 <= s_n1 <= 499):
            DEFECTS.append(f"(neg1) by-id query of deleted id 1 returned "
                           f"unexpected status {s_n1} — raw check needed")
        else:
            print(f"[neg1] OK: deleted id by-id lookup rejected with {s_n1}")

        # ---- neg2: by-id query of a NEVER-CREATED id must error ----
        s_n2, ids_n2 = byid_query("neg2-never-id", C, 777777, limit=3)
        if s_n2 == 200:
            DEFECTS.append(f"(neg2) by-id query of never-existing id 777777 "
                           f"returned 200 with ids={ids_n2} — phantom state — "
                           f"Type4_StateLogicViolation")
        elif s_n2 is not None and s_n2 > 0 and not (400 <= s_n2 <= 499):
            DEFECTS.append(f"(neg2) by-id query of never-existing id returned "
                           f"unexpected status {s_n2} — raw check needed")
        else:
            print(f"[neg2] OK: never-existing id by-id lookup rejected with {s_n2}")

        # ---- pos2: survivor unaffected ----
        s_p2, ids_p2 = byid_query("pos2-id3", C, 3, limit=3)
        if s_p2 != 200 or ids_p2 is None:
            print("SETUP_ERROR: survivor by-id query not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if not ids_p2:
            DEFECTS.append("(pos2) survivor id 3 by-id query returned 200 "
                           "with empty result.points — over-deletion on the "
                           "read path — Type4_StateLogicViolation")
        else:
            print(f"[pos2] OK: survivor id 3 by-id query returned {ids_p2}")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        if ABORT[0]:
            print("ABORT: environment/transport unavailable mid-run")
            return "SCRIPT_ERROR"
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
