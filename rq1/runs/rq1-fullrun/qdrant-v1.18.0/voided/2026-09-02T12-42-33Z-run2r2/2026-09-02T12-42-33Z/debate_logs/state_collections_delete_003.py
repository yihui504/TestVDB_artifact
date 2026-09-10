#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_delete_003
# strategy: count_consistency
# endpoint: collections+delete
# constraint_ids: qdrant_behavioral_collections_delete_001, qdrant_bc_delete_invisibility_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: CRUD-then-COUNT reconciliation across a collection delete
  (collections+delete; URLs from raw_knowledge api_endpoints[].url).
  Strategy-1 count consistency specialized to the chunk's delete units:
  (A setup) create -> upsert N=12 points (wait=true) -> exact count
  must equal 12 (positive control: counting works before the mutation).
  (B mutation point — G6 justification: the destructive power of
  DELETE /collections/{name} is total-state removal + name reuse, the
  two spots where counters classically lie: stale counters surviving
  the drop, and pre-delete rows resurrecting into a same-name
  recreate) -> DELETE -> 200.
  (C) count on the deleted name must be 404 — a 200 with ANY number
  (0, 12, stale) means the data face outlived the confirmed delete =
  Type4.
  (D recreate) recreate the SAME name with the same vector config ->
  200 -> exact count must be 0 (fresh namespace; count > 0 =
  pre-delete points resurrected through the name = Type4).
  (E closure) upsert 1 fresh point (wait=true) -> exact count must be
  1 (the recreated collection counts normally; guards against a
  counter stuck at 0 masking (D)).
  [chunk_collections+delete coverage: count_consistency x
   qdrant_behavioral_collections_delete_001 +
   qdrant_bc_delete_invisibility_001 (count face across delete and
   recreate)]
Oracle: pre-delete exact count == 12; post-delete count -> 404;
  post-recreate exact count == 0; after 1 fresh upsert exact count
  == 1. 200-with-stale-count after delete or count>0 after recreate
  = Type4_StateLogicViolation; 5xx judged Type3 only after /healthz
  confirms liveness.
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


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
        return b if isinstance(b, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def exact_count(name):
    """POST count {exact:true} -> (status, count-or-None, raw)."""
    s, raw = safe_request("POST", "count", path_params={"name": name},
                          body={"exact": True})
    body = parse_json(raw) or {}
    res = body.get("result")
    val = res.get("count") if isinstance(res, dict) else None
    return s, val, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scdl3_" + TS + "_"
    C = PFX + "cnt"
    DIM = 4
    N = 12
    VEC_CFG = {"vectors": {"size": DIM, "distance": "Cosine"}}
    DEFECTS = []

    def liveness(tag):
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    try:
        # ---- (A setup) create + N points + positive count control ----
        cr_s, cr_raw = safe_request("PUT", "create_collection", path_params={"name": C},
                                    body=VEC_CFG)
        print(f"[A create] status={cr_s} raw={cr_raw[:160]}")
        if cr_s not in (200, 201):
            print("SETUP_ERROR: create failed")
            return "SCRIPT_ERROR"
        up_body = {"points": [{"id": i, "vector": [round(0.02 * (i % 7 + 1), 4)] * DIM}
                              for i in range(1, N + 1)]}
        up_s, up_raw = safe_request("PUT", "upsert_points", path_params={"name": C},
                                    body=up_body, query_params={"wait": "true"})
        print(f"[A upsert x{N}] status={up_s} raw={up_raw[:160]}")
        if up_s not in (200, 201):
            print(f"SETUP_ERROR: upsert returned {up_s}")
            return "SCRIPT_ERROR"
        a_s, a_val, a_raw = exact_count(C)
        print(f"[A count] status={a_s} count={a_val} raw={a_raw[:160]}")
        if a_s == 0 or 500 <= a_s <= 599:
            if not liveness("A-count"):
                return "SCRIPT_ERROR"
            print(f"SETUP_ERROR: count returned {a_s} with service alive — Type3 "
                  f"before any mutation; refusing to judge")
            return "SCRIPT_ERROR"
        if a_s != 200 or a_val != N:
            print(f"SETUP_ERROR: pre-delete count {a_val} != {N} — counter already "
                  f"broken before the delete mutation; cannot attribute")
            return "SCRIPT_ERROR"

        # ---- (B mutation) delete -> 200 (premise gate) ----
        d_s, d_raw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[B delete] status={d_s} raw={d_raw[:160]}")
        if d_s == 0:
            liveness("B-delete")
            return "SCRIPT_ERROR"
        if 500 <= d_s <= 599:
            if not liveness("B-delete"):
                return "SCRIPT_ERROR"
            DEFECTS.append(f"(B) DELETE returned {d_s} with service alive — "
                           f"Type3_RuntimeFailure — raw={d_raw[:200]}")
        elif d_s != 200:
            DEFECTS.append(f"(B) DELETE on a counted-existing collection returned "
                           f"{d_s} (assertion: confirmed with 200) — "
                           f"Type4_StateLogicViolation — raw={d_raw[:200]}")

        # ---- (C) count face after delete -> 404 ----
        c_s, c_val, c_raw = exact_count(C)
        print(f"[C count-after-delete] status={c_s} count={c_val} raw={c_raw[:160]}")
        if c_s == 0 or 500 <= c_s <= 599:
            if not liveness("C-count"):
                return "SCRIPT_ERROR"
            DEFECTS.append(f"(C) count after 200 delete returned {c_s} with service "
                           f"alive — Type3_RuntimeFailure — raw={c_raw[:200]}")
        elif c_s != 404:
            DEFECTS.append(f"(C) count after 200 delete returned {c_s} "
                           f"count={c_val} (expected 404 — data face must not "
                           f"outlive a confirmed delete) — Type4_StateLogicViolation "
                           f"(qdrant_bc_delete_invisibility_001) — raw={c_raw[:200]}")

        # ---- (D recreate) same name -> count must be exactly 0 ----
        r_s, r_raw = safe_request("PUT", "create_collection", path_params={"name": C},
                                  body=VEC_CFG)
        print(f"[D recreate] status={r_s} raw={r_raw[:160]}")
        if r_s == 0:
            liveness("D-recreate")
            return "SCRIPT_ERROR"
        if 500 <= r_s <= 599:
            if not liveness("D-recreate"):
                return "SCRIPT_ERROR"
            DEFECTS.append(f"(D) recreate after delete returned {r_s} with service "
                           f"alive — Type3_RuntimeFailure — raw={r_raw[:200]}")
        elif r_s != 200:
            DEFECTS.append(f"(D) recreate of a deleted name returned {r_s} "
                           f"(expected 200) — delete residue — "
                           f"Type4_StateLogicViolation — raw={r_raw[:160]}")
        else:
            d2_s, d2_val, d2_raw = exact_count(C)
            print(f"[D count-after-recreate] status={d2_s} count={d2_val} "
                  f"raw={d2_raw[:160]}")
            if d2_s == 0 or 500 <= d2_s <= 599:
                if not liveness("D-count"):
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"(D) count after recreate returned {d2_s} with "
                               f"service alive — Type3_RuntimeFailure — "
                               f"raw={d2_raw[:200]}")
            elif d2_s != 200 or d2_val != 0:
                DEFECTS.append(f"(D) exact count after recreating the deleted name "
                               f"= {d2_val} (status {d2_s}; expected exactly 0) — "
                               f"pre-delete points resurrected through the name — "
                               f"Type4_StateLogicViolation — raw={d2_raw[:200]}")

            # ---- (E closure) 1 fresh point -> count 1 ----
            up2_body = {"points": [{"id": 1001, "vector": [0.0311] * DIM}]}
            up2_s, up2_raw = safe_request("PUT", "upsert_points",
                                          path_params={"name": C},
                                          body=up2_body,
                                          query_params={"wait": "true"})
            print(f"[E upsert x1] status={up2_s} raw={up2_raw[:160]}")
            if up2_s in (200, 201):
                e_s, e_val, e_raw = exact_count(C)
                print(f"[E count] status={e_s} count={e_val} raw={e_raw[:160]}")
                if e_s == 0 or 500 <= e_s <= 599:
                    if not liveness("E-count"):
                        return "SCRIPT_ERROR"
                    DEFECTS.append(f"(E) count after fresh upsert returned {e_s} "
                                   f"with service alive — Type3_RuntimeFailure — "
                                   f"raw={e_raw[:200]}")
                elif e_s != 200 or e_val != 1:
                    DEFECTS.append(f"(E) exact count after 1 fresh upsert on the "
                                   f"recreated collection = {e_val} (status {e_s}; "
                                   f"expected 1) — counter does not reconcile — "
                                   f"Type4_StateLogicViolation — raw={e_raw[:200]}")
            else:
                print(f"NOTE: (E) fresh upsert on recreated collection returned "
                      f"{up2_s} — recreate leg usability not confirmed; (D) count "
                      f"judgement above stands on its own")

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
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
