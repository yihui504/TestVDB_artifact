#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_batch_reject404_007
# strategy: transaction
# endpoint: points+batch
# constraint_ids: qdrant_state_points_batch_001, qdrant_behavioral_points_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/batch-update
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: regression + generalization of the run2r#1-R3 confirmed defect
  class on points+batch — a mid-batch op that fails with NotFound
  (delete_vectors naming a vector that does not exist in a collection
  whose ONLY vector is the unnamed default) makes the WHOLE request
  return 404 while ops already applied in the for-loop stay committed
  (collection update loop early-exit, no rollback, position-dependent).
  Faces: (CTL) positive pairing — a poison-free batch [upsert 611,
  set_payload 611] must commit both; (F) poison LAST — [upsert 612,
  set_payload 612, delete_vectors missing-name] expected whole-request
  4xx (404 per the confirmed instance): if 612 is STILL durably
  visible afterwards, the rejected batch committed a prefix =
  Type4_StateLogicViolation (known-defect regression); (G) poison FIRST
  — [delete_vectors missing-name, upsert 613] must reject and apply
  nothing; (G9) the same poison op must get the same disposition in
  both positions (404 vs 400 vs 200 divergence = inconsistent
  disposition = defect signal).
  [chunk_points+batch coverage: transaction/atomicity x
  qdrant_state_points_batch_001 + qdrant_behavioral_points_batch_001
  (404-class poison: prefix-commit regression + poison-first +
  disposition consistency)]
Oracle: CTL -> 200 and 611 visible with payload exactly {"n":611,"tag":"x"}
  (missing/partial CTL commit = Type4); F -> whole-request 4xx AND 612
  absent from readback (612 visible after a rejected batch =
  Type4_StateLogicViolation — rejected request committed state); if F
  returns 200 instead, per-op result length == 3 and 612 payload must be
  the full CTL-style payload ({"n":612,"tag":"x"}); G -> 4xx AND 613
  absent AND 611 payload unchanged; F status != G status for the same
  poison op = inconsistent disposition (defect signal, recorded with
  both statuses); 5xx with /healthz alive = Type3_RuntimeFailure;
  transport failure -> liveness re-check before any verdict.
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

# URLs registered VERBATIM from raw_knowledge api_endpoints[]:
#   {"path": "points+batch", "method": "POST",
#    "url": "/collections/{collection_name}/points/batch"}
#   {"path": "points+get", "method": "POST",
#    "url": "/collections/{collection_name}/points"}
rt.PATHS["batch_update"] = "/collections/{collection_name}/points/batch"
rt.PATHS["get_points_by_ids"] = "/collections/{collection_name}/points"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('batch_update', 'get_points_by_ids')]}")

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


def result_of(raw):
    try:
        return json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return None


def type_strict_eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return type(a) is type(b) and a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return (set(a.keys()) == set(b.keys())
                and all(type_strict_eq(a[k], b[k]) for k in a))
    if isinstance(a, list):
        return (len(a) == len(b)
                and all(type_strict_eq(x, y) for x, y in zip(a, b)))
    return a == b


def run_batch(tag, coll, ops):
    s, raw = safe_request("POST", "batch_update",
                          path_params={"collection_name": coll},
                          body={"operations": ops},
                          query_params={"wait": "true"})
    print(f"[{tag} batch {len(ops)} ops] status={s} raw={str(raw)[:280]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        else:
            DEFECTS.append(f"({tag}) batch transport failure with service "
                           f"alive — Type3_RuntimeFailure")
        return s, None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) batch returned {s} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return s, None
    res = None
    if s == 200:
        res = result_of(raw)
        if not isinstance(res, list):
            DEFECTS.append(f"({tag}) 200 batch result is not an array — "
                           f"raw={str(raw)[:200]} — Type4_StateLogicViolation")
            res = None
        elif len(res) != len(ops):
            DEFECTS.append(f"({tag}) 200 batch returned {len(res)} result "
                           f"entries for {len(ops)} operations — "
                           f"Type4_StateLogicViolation "
                           f"(qdrant_behavioral_points_batch_001)")
    return s, res


def visible_payloads(tag, coll, ids):
    s, raw = safe_request("POST", "get_points_by_ids",
                          path_params={"collection_name": coll},
                          body={"ids": ids, "with_payload": True})
    print(f"[{tag} get {ids}] status={s} raw={str(raw)[:280]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) batch-get returned {s} with service "
                           f"alive — Type3_RuntimeFailure")
        else:
            ABORT[0] = True
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} batch-get returned {s}")
        return None
    res = result_of(raw)
    if not isinstance(res, list):
        print(f"SETUP_ERROR: {tag} batch-get result not a list")
        return None
    out = {}
    for p in res:
        if isinstance(p, dict) and "id" in p:
            out[p["id"]] = p.get("payload") if isinstance(p.get("payload"), dict) else {}
    return out


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spbv7_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def vec(x):
        return [float(x), 0.5, 0.75, 1.0]

    POISON = {"delete_vectors": {"points": [611],
                                 "vector": ["no_such_vector"]}}

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        # ---- CTL: poison-free batch commits both ops (positive pairing) ----
        s, _ = run_batch("CTL", C, [
            {"upsert": {"points": [
                {"id": 611, "vector": vec(1), "payload": {"n": 611}}]}},
            {"set_payload": {"payload": {"tag": "x"}, "points": [611]}},
        ])
        if s != 200:
            print(f"SETUP_ERROR: CTL status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        vis = visible_payloads("CTL", C, [611])
        if vis is not None:
            if set(vis.keys()) != {611}:
                DEFECTS.append(f"(CTL) point 611 missing after poison-free "
                               f"200 batch — Type4_StateLogicViolation")
            elif not type_strict_eq(vis[611], {"n": 611, "tag": "x"}):
                DEFECTS.append(f"(CTL) 611 payload {vis[611]!r} != "
                               f"{{'n': 611, 'tag': 'x'}} — "
                               f"Type4_StateLogicViolation")
            else:
                print("[CTL] OK: poison-free batch fully committed")

        # ---- F: poison LAST (prefix-commit window, known instance) ----
        s_f, res_f = run_batch("F-fail-last", C, [
            {"upsert": {"points": [
                {"id": 612, "vector": vec(2), "payload": {"n": 612}}]}},
            {"set_payload": {"payload": {"tag": "x"}, "points": [612]}},
            POISON,
        ])
        vis = visible_payloads("F-readback", C, [612])
        if vis is not None:
            if 400 <= s_f <= 499:
                if 612 in vis:
                    DEFECTS.append(f"(F) batch REJECTED with {s_f} yet the "
                                   f"prefix ops on 612 are durably visible "
                                   f"(payload {vis[612]!r}) — rejected "
                                   f"request committed state (no rollback, "
                                   f"position-dependent partial commit — "
                                   f"run2r#1-R3 defect class) — "
                                   f"Type4_StateLogicViolation")
                else:
                    print("[F] OK: rejected batch left no visible prefix")
            elif s_f == 200:
                if set(vis.keys()) != {612}:
                    DEFECTS.append(f"(F) 200 batch but 612 not visible — "
                                   f"Type4_StateLogicViolation")
                elif not type_strict_eq(vis[612], {"n": 612, "tag": "x"}):
                    DEFECTS.append(f"(F) 200 batch but 612 payload "
                                   f"{vis[612]!r} != full expected payload "
                                   f"— Type4_StateLogicViolation")
                else:
                    print(f"[F] 200 with per-op results: {res_f!r}")

        # ---- G: poison FIRST (nothing may apply) ----
        s_g, res_g = run_batch("G-fail-first", C, [
            POISON,
            {"upsert": {"points": [
                {"id": 613, "vector": vec(3), "payload": {"n": 613}}]}},
        ])
        vis = visible_payloads("G-readback", C, [611, 613])
        if vis is not None:
            if 400 <= s_g <= 499:
                if 613 in vis:
                    DEFECTS.append(f"(G) batch REJECTED with {s_g} yet the "
                                   f"op AFTER the poison (613) is durably "
                                   f"visible — Type4_StateLogicViolation")
                else:
                    print("[G] OK: rejected batch applied nothing")
                if set(vis.keys()) != {611}:
                    DEFECTS.append(f"(G) readback after rejection shows "
                                   f"{sorted(vis.keys())} != [611] — "
                                   f"Type4_StateLogicViolation")
                elif not type_strict_eq(vis[611], {"n": 611, "tag": "x"}):
                    DEFECTS.append(f"(G) pre-existing 611 payload drifted: "
                                   f"{vis[611]!r} — "
                                   f"Type4_StateLogicViolation")
            elif s_g == 200 and 613 not in vis:
                DEFECTS.append("(G) 200 batch but post-poison upsert of 613 "
                               "not visible — Type4_StateLogicViolation")

        # ---- G9: disposition consistency of the same poison op ----
        print(f"[disposition] fail-last={s_f} fail-first={s_g}")
        if (400 <= s_f <= 499) != (400 <= s_g <= 499):
            DEFECTS.append(f"(G9) the SAME delete_vectors-missing-name op "
                           f"got status {s_f} at last position but {s_g} "
                           f"at first position — inconsistent disposition "
                           f"by position — Type4_StateLogicViolation")

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
