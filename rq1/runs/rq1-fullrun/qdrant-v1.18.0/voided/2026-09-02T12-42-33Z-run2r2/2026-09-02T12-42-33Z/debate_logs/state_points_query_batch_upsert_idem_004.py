#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_batch_upsert_idem_004
# strategy: upsert_idempotence
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: upsert idempotence observed through the batch query face
  (Strategy 3: upsert idempotence) x
  qdrant_behavioral_points_query_batch_001 ("200 with one result per
  search"). Legs:
  (idem) upsert id 500 (V1) wait=true -> count==1; upsert the SAME id
  500 (V2, orthogonal vector) wait=true -> count must STAY 1 (an
  idempotent overwrite adds no point — supports
  qdrant_inv_count_consistency_001); a third duplicate upsert of V2 ->
  count still 1.
  (readback) after each write the state is read back through the batch
  by-id search (with_vector) AND through the single GET baseline. Per
  R27 the comparison baseline is ALWAYS a read-back (GET with_vector),
  never the uploaded raw vectors: the batch-face readback must equal the
  GET read-back of the same moment (cross-face read consistency), and
  the V2 read-back must differ from the V1 read-back (the overwrite
  actually landed — a stale V1 read-back after the V2 overwrite = stale
  read, Type4).
  V1=[1,0,0,0] and V2=[0,1,0,0] are orthogonal so the flip check is
  robust under any storage normalization.
  If the batch entry does not carry a vector, no claim is made (the
  chunk's response_shape grid promises only result[].points objects —
  R39: missing-response-field claims require a promised field);
  recorded as WARN and the leg degrades to id-presence checks.
  [chunk_points+query+batch coverage: upsert_idempotence x
  qdrant_behavioral_points_query_batch_001 (duplicate-upsert count
  invariance + batch by-id readback vs GET-baseline equality + overwrite
  flip + stale-read detection)]
Oracle: every duplicate upsert leaves exact count == 1 (2 = duplicated
  point, Type4_StateLogicViolation); every batch -> 200 with
  len(result) == len(searches) and the by-id entry containing exactly
  point id 500 (missing/extra ids = Type4); batch by-id vector readback
  == concurrent GET with_vector readback (mismatch = cross-face
  inconsistency, Type4); post-overwrite readbacks (batch and GET) both
  differ from the pre-overwrite readback (stale V1 = stale read, Type4);
  vector-absent entries -> WARN + degraded checks (no defect claim on
  an unpromised field); 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> liveness re-check before
  any verdict.
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
#   {"path": "points+query+batch", "method": "POST",
#    "url": "/collections/{collection_name}/points/query/batch"}
rt.PATHS["query_batch"] = "/collections/{collection_name}/points/query/batch"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('query_batch', 'upsert_points', 'get_point', 'count', 'healthz')]}")

DEFECTS = []
WARNINGS = []
ABORT = [False]

PID = 500
V1 = [1.0, 0.0, 0.0, 0.0]
V2 = [0.0, 1.0, 0.0, 0.0]
TOL = 1e-9


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


def transport_or_5xx(tag, status, raw):
    if status == 0:
        if not liveness(tag):
            ABORT[0] = True
        return True
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {status} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return True
    return False


def vec_close(a, b, tol=TOL):
    return (isinstance(a, list) and isinstance(b, list)
            and len(a) == len(b)
            and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                    and isinstance(y, (int, float)) and not isinstance(y, bool)
                    and abs(float(x) - float(y)) <= tol
                    for x, y in zip(a, b)))


def vec_far(a, b, tol=1e-6):
    return not vec_close(a, b, tol)


def default_vector(vec_field):
    """vector readback may be a list (default) or a named dict {\"\": [...]}."""
    if isinstance(vec_field, list):
        return vec_field
    if isinstance(vec_field, dict) and isinstance(vec_field.get(""), list):
        return vec_field[""]
    return None


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if transport_or_5xx(tag + "-count", s, raw):
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} count returned {s}")
        return None
    res = result_of(raw)
    cnt = res.get("count") if isinstance(res, dict) else None
    if isinstance(cnt, bool) or not isinstance(cnt, int):
        print(f"SETUP_ERROR: {tag} count result.count missing")
        return None
    return cnt


def upsert(tag, coll, vector):
    s, raw = safe_request("PUT", "upsert_points",
                          path_params={"name": coll},
                          body={"points": [{"id": PID, "vector": vector}]},
                          query_params={"wait": "true"})
    print(f"[{tag} upsert {PID}] status={s} raw={str(raw)[:180]}")
    if s == 0 or 500 <= s <= 599:
        transport_or_5xx(tag, s, raw)
        return False
    if s != 200:
        print(f"SETUP_ERROR: {tag} upsert returned {s}")
        return False
    return True


def get_baseline(tag, coll):
    """GET read-back of the stored vector (R27: baseline is a read-back)."""
    s, raw = safe_request("GET", "get_point",
                          path_params={"name": coll, "point_id": PID},
                          query_params={"with_vector": "true"})
    print(f"[{tag} GET {PID}] status={s} raw={str(raw)[:240]}")
    if transport_or_5xx(tag + "-get", s, raw):
        return "TRANSPORT"
    if s != 200:
        print(f"SETUP_ERROR: {tag} GET returned {s}")
        return None
    res = result_of(raw)
    if not isinstance(res, dict):
        print(f"SETUP_ERROR: {tag} GET result unreadable")
        return None
    return default_vector(res.get("vector"))


def batch_readback(tag, coll):
    """Batch by-id search with vector readback. Returns (ids, vector) or
    'TRANSPORT' / None on non-200."""
    searches = [{"query": PID, "limit": 3, "with_vector": True},
                {"query": [0.5, 0.5, 0.0, 0.0], "limit": 2}]
    s, raw = safe_request("POST", "query_batch",
                          path_params={"collection_name": coll},
                          body={"searches": searches})
    print(f"[{tag} batch by-id {PID}] status={s} raw={str(raw)[:400]}")
    if transport_or_5xx(tag, s, raw):
        return "TRANSPORT"
    if s != 200:
        DEFECTS.append(f"({tag}) batch query returned {s} — assertion pins "
                       f"200 with one result per search — "
                       f"Type4_StateLogicViolation")
        return None
    res = result_of(raw)
    if not isinstance(res, list) or len(res) != len(searches):
        DEFECTS.append(f"({tag}) 200 batch result is not a "
                       f"{len(searches)}-entry array — "
                       f"Type4_StateLogicViolation")
        return None
    entry = res[0]
    if not isinstance(entry, dict) or not isinstance(entry.get("points"),
                                                     list):
        DEFECTS.append(f"({tag}) result[0] violates response_shape — "
                       f"Type4_StateLogicViolation")
        return None
    pts = entry["points"]
    ids = [p.get("id") for p in pts
           if isinstance(p, dict) and "id" in p]
    if ids != [PID]:
        DEFECTS.append(f"({tag}) by-id search of {PID} returned ids {ids} "
                       f"(expected exactly [{PID}]) — duplicated or missing "
                       f"point — Type4_StateLogicViolation")
    vec = None
    for p in pts:
        if isinstance(p, dict) and p.get("id") == PID:
            vec = default_vector(p.get("vector"))
    if vec is None:
        WARNINGS.append(f"({tag}) batch by-id entry carries no readable "
                        f"vector — vector comparison skipped (response_shape "
                        f"does not promise the field; no defect claim)")
    return ids, vec


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spqb4_" + TS + "_"
    C = PFX + "col"

    try:
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        # ---- write 1: V1 ----
        if not upsert("w1", C, V1):
            return "SCRIPT_ERROR" if ABORT[0] else "DEFECT_FOUND" \
                if DEFECTS else "SCRIPT_ERROR"
        cnt = exact_count("w1", C)
        if cnt is not None and cnt != 1:
            DEFECTS.append(f"(w1) count {cnt} != 1 after single upsert — "
                           f"Type4_StateLogicViolation")
        base1 = get_baseline("w1", C)
        if base1 == "TRANSPORT":
            pass
        elif base1 is None:
            print("SETUP_ERROR: w1 baseline unreadable")
            return "SCRIPT_ERROR"
        out1 = batch_readback("w1-batch", C)

        # ---- write 2: SAME id, V2 (idempotent overwrite) ----
        if not upsert("w2", C, V2):
            return "SCRIPT_ERROR" if ABORT[0] else "DEFECT_FOUND" \
                if DEFECTS else "SCRIPT_ERROR"
        cnt = exact_count("w2", C)
        if cnt is not None and cnt != 1:
            DEFECTS.append(f"(idem) count {cnt} != 1 after re-upserting the "
                           f"same id — duplicated point — "
                           f"Type4_StateLogicViolation")
        base2 = get_baseline("w2", C)
        out2 = batch_readback("w2-batch", C)

        # ---- write 3: duplicate V2 again ----
        if not upsert("w3", C, V2):
            return "SCRIPT_ERROR" if ABORT[0] else "DEFECT_FOUND" \
                if DEFECTS else "SCRIPT_ERROR"
        cnt = exact_count("w3", C)
        if cnt is not None and cnt != 1:
            DEFECTS.append(f"(idem) count {cnt} != 1 after duplicate upsert "
                           f"— duplicated point — "
                           f"Type4_StateLogicViolation")
        base3 = get_baseline("w3", C)
        out3 = batch_readback("w3-batch", C)

        # ---- read-back reconciliation ----
        if base1 not in ("TRANSPORT", None) and base2 not in ("TRANSPORT", None):
            if vec_close(base1, base2):
                DEFECTS.append("(flip) V2 overwrite not visible in GET "
                               "read-back (still equals V1 read-back) — "
                               "stale state — Type4_StateLogicViolation")
        if base2 not in ("TRANSPORT", None) and base3 not in ("TRANSPORT", None):
            if not vec_close(base2, base3):
                DEFECTS.append("(dup) duplicate upsert CHANGED the stored "
                               "vector between identical writes — "
                               "Type4_StateLogicViolation")
        for tag, base, out in (("w1", base1, out1),
                               ("w2", base2, out2),
                               ("w3", base3, out3)):
            if out in ("TRANSPORT", None) or base in ("TRANSPORT", None):
                continue
            _, bvec = out
            if bvec is None:
                continue
            if not vec_close(bvec, base):
                DEFECTS.append(f"({tag}) batch by-id vector readback != GET "
                               f"baseline read-back (batch={bvec} "
                               f"get={base}) — cross-face inconsistency — "
                               f"Type4_StateLogicViolation")
        if (out2 not in ("TRANSPORT", None) and out1 not in ("TRANSPORT", None)
                and out2[1] is not None and out1[1] is not None
                and vec_close(out2[1], out1[1])):
            DEFECTS.append("(flip) batch by-id readback still equals the V1 "
                           "read-back after the V2 overwrite — stale read "
                           "on the batch face — Type4_StateLogicViolation")

        for w in WARNINGS:
            print(f"WARN: {w}")
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
