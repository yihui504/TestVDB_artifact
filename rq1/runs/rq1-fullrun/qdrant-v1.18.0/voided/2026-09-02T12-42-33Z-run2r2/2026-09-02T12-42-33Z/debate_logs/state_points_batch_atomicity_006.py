#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_batch_atomicity_006
# strategy: transaction
# endpoint: points+batch
# constraint_ids: qdrant_state_points_batch_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
"""
Attack: batch atomicity under a mid-batch REJECTED operation (transaction
  strategy, sequence-negative) x qdrant_state_points_batch_001
  "operations are executed in order inside one batch request". Rationale
  (G6 mutation justification): a poison op at the LAST position maximizes
  the committed-prefix window — if the server applies ops in a for-loop
  and aborts on first error without rollback, the client gets a failure
  response while a prefix of writes is already durable (position-
  dependent partial commit). Poison op here is update_vectors with a
  2-dim vector against a 4-dim collection (dimension mismatch — the
  classic 400-class validation failure, exercised via the batch face,
  run2r#1-R3-adjacent novel trigger). Positive pairing (G4): a VALID
  update_vectors inside a batch must durably change the vector (readback
  with_vector). Faces: (F) fail-LAST [upsert 602, upsert 603, poison] vs
  (G) fail-FIRST [poison, upsert 604]; (G9) the SAME poison op must get
  the SAME disposition in both positions.
  [chunk_points+batch coverage: transaction/atomicity x
  qdrant_state_points_batch_001 (fail-last prefix-commit + fail-first +
  disposition consistency + valid update_vectors positive)]
Oracle: positive control -> 200 and point 601's vector readback ==
  V_NEW (unchanged vector = Type4); fail-last: if the batch is rejected
  (4xx) then NEITHER 602 nor 603 may be durably visible afterwards (a
  rejected batch with a visible prefix = Type4_StateLogicViolation
  response/state divergence); if it returns 200 with per-op results then
  result length == 3 and 602's vector must still be 4-dim (a 2-dim
  vector applied = corruption Type4); fail-first: 4xx -> 604 absent,
  602/603 payload untouched; fail-last and fail-first statuses must
  match (same poison op, differing status = inconsistent disposition =
  defect signal); 5xx with /healthz alive = Type3_RuntimeFailure;
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


def run_batch(tag, coll, ops):
    """Returns (status, per_op_result_list_or_None). 5xx/transport handled."""
    s, raw = safe_request("POST", "batch_update",
                          path_params={"collection_name": coll},
                          body={"operations": ops},
                          query_params={"wait": "true"})
    print(f"[{tag} batch {len(ops)} ops] status={s} raw={str(raw)[:260]}")
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
                           f"Type4_StateLogicViolation")
    return s, res


def visible_state(tag, coll, ids, with_vector=False):
    """Batch-get; returns {id: {"payload":..., "vector":...}} or None."""
    body = {"ids": ids, "with_payload": True}
    if with_vector:
        body["with_vector"] = True
    s, raw = safe_request("POST", "get_points_by_ids",
                          path_params={"collection_name": coll}, body=body)
    print(f"[{tag} get {ids}] status={s} raw={str(raw)[:300]}")
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
            out[p["id"]] = {"payload": p.get("payload"),
                            "vector": p.get("vector")}
    return out


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spba6_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def vec(x):
        return [float(x), 0.5, 0.75, 1.0]

    V_NEW = [9.0, 8.0, 7.0, 6.0]
    POISON = {"update_vectors": {"points": [
        {"id": 602, "vector": [0.1, 0.2]}]}}  # 2-dim vs 4-dim collection

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        # seed 601 with the plain upsert endpoint
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C},
                              body={"points": [{"id": 601, "vector": vec(1),
                                                "payload": {"n": 601}}]},
                              query_params={"wait": "true"})
        print(f"[seed 601] status={s} raw={str(raw)[:150]}")
        if s != 200:
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR"

        # ---- positive control: VALID update_vectors inside a batch ----
        s, res = run_batch("CTL-valid-update-vectors", C, [
            {"update_vectors": {"points": [
                {"id": 601, "vector": V_NEW}]}}])
        if s != 200:
            print(f"SETUP_ERROR: control batch status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        vis = visible_state("CTL", C, [601], with_vector=True)
        if vis is not None:
            got_vec = vis.get(601, {}).get("vector")
            if 601 not in vis:
                DEFECTS.append("(CTL) point 601 vanished after a valid "
                               "update_vectors — Type4_StateLogicViolation")
            elif got_vec != V_NEW:
                DEFECTS.append(f"(CTL) valid update_vectors did not durably "
                               f"apply: vector {got_vec!r} != {V_NEW!r} — "
                               f"Type4_StateLogicViolation")
            else:
                print("[CTL] OK: valid update_vectors applied in batch")

        # ---- F: poison op LAST (max committed-prefix window) ----
        s_f, res_f = run_batch("F-fail-last", C, [
            {"upsert": {"points": [
                {"id": 602, "vector": vec(2), "payload": {"pos": "F"}}]}},
            {"upsert": {"points": [
                {"id": 603, "vector": vec(3), "payload": {"pos": "F"}}]}},
            POISON,
        ])
        vis = visible_state("F-readback", C, [601, 602, 603], with_vector=True)
        if vis is not None:
            if 400 <= s_f <= 499:
                leaked = sorted(k for k in (602, 603) if k in vis)
                if leaked:
                    DEFECTS.append(f"(F) batch REJECTED with {s_f} yet "
                                   f"prefix ops {leaked} are durably "
                                   f"visible — rejected request committed "
                                   f"state (no rollback, position-dependent "
                                   f"partial commit) — "
                                   f"Type4_StateLogicViolation "
                                   f"(qdrant_state_points_batch_001)")
                else:
                    print("[F] OK: rejected batch left no visible prefix")
            elif s_f == 200:
                got_vec = vis.get(602, {}).get("vector")
                if 602 in vis and got_vec == [0.1, 0.2]:
                    DEFECTS.append(f"(F) 2-dim vector {got_vec!r} durably "
                                   f"applied to 4-dim point 602 — dimension "
                                   f"validation bypassed — "
                                   f"Type4_StateLogicViolation")
                elif 602 not in vis or 603 not in vis:
                    DEFECTS.append(f"(F) 200 batch but 602/603 missing in "
                                   f"readback — visible={sorted(vis)} — "
                                   f"Type4_StateLogicViolation")
                else:
                    print(f"[F] 200 with per-op results: {res_f!r}")

        # ---- G: poison op FIRST (nothing may apply after the abort) ----
        s_g, res_g = run_batch("G-fail-first", C, [
            POISON,
            {"upsert": {"points": [
                {"id": 604, "vector": vec(4), "payload": {"pos": "G"}}]}},
        ])
        vis = visible_state("G-readback", C, [602, 604], with_vector=True)
        if vis is not None:
            if 400 <= s_g <= 499:
                if 604 in vis:
                    DEFECTS.append(f"(G) batch REJECTED with {s_g} yet the "
                                   f"op AFTER the poison (604) is durably "
                                   f"visible — Type4_StateLogicViolation")
                else:
                    print("[G] OK: rejected batch applied nothing")
            elif s_g == 200 and 604 not in vis:
                DEFECTS.append("(G) 200 batch but post-poison upsert of 604 "
                               "not visible — Type4_StateLogicViolation")

        # ---- G9: same poison op, same disposition in both positions ----
        print(f"[disposition] fail-last={s_f} fail-first={s_g}")
        if (400 <= s_f <= 499) != (400 <= s_g <= 499):
            DEFECTS.append(f"(G9) the SAME poison op got status {s_f} at "
                           f"last position but {s_g} at first position — "
                           f"inconsistent disposition by position — "
                           f"Type4_StateLogicViolation")

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
