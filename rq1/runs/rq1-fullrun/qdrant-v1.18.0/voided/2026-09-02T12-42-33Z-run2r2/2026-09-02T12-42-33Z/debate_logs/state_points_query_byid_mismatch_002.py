#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_byid_mismatch_002
# strategy: state_lookup_validation
# endpoint: points+query
# constraint_ids: qdrant_state_points_query_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
"""
Attack: by-id lookup vector-characteristics mismatch must ERROR (negative
  pairing for qdrant_state_points_query_001 "fetched vectors must match the
  characteristics of the using vector, otherwise an error is returned").
  C_main has named vectors {"t": size 4, "i": size 8}; C_aux8 is an unnamed
  8-dim collection; C_aux4 is an unnamed 4-dim collection. Legs (each
  negative has a positive control sharing the setup — G4):
  (D1 pos) point 1 has only "t"; query {"query":1,"using":"t"} -> 200.
  (D2 neg) same point, {"query":1,"using":"i"} -> 4xx: point 1 has no "i"
  vector, the fetched vector's characteristics do not match the using
  space. 200 here = using-space validation silently skipped.
  (D3 pos) point 2 has only "i"; {"query":2,"using":"i"} -> 200.
  (D4 neg) {"query":1,"using":"nope"} (name not in the collection config)
  -> 4xx.
  (D5 pos) lookup_from C_aux8 (unnamed dim 8) into using "i" (dim 8) ->
  200 (characteristics MATCH across collections).
  (D6 neg) lookup_from C_aux4 (unnamed dim 4) into using "i" (dim 8) ->
  4xx: fetched vector dim 4 != using space dim 8. 200 = illegal success.
  (D7 neg) C_aux4 unnamed collection, {"query":91,"using":"zzz"} -> 4xx
  (no named vectors exist at all).
  Mutation-point justification (G6): the named-vector subset + cross-dim
  lookup_from are the only constructions where the by-id fetch can
  legitimately succeed at the HTTP layer while the fetched vector belongs
  to a DIFFERENT vector space — exactly the silent-coercion gap BS-01
  predicts.
  [chunk_points+query coverage: state_lookup_validation x
  qdrant_state_points_query_001 (named-vector subset mismatch +
  nonexistent-name mismatch + cross-collection lookup dim mismatch, each
  with positive control)]
Oracle: D1/D3/D5 -> HTTP 200 with result.points array; D2/D4/D6/D7 ->
  HTTP 4xx (400 or 404 both count as the promised error; 200 =
  Type1_IllegalSuccess — the constraint explicitly promises "an error is
  returned"); any 5xx with /healthz alive = Type3_RuntimeFailure;
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

# runtime PATHS already carries query/upsert_points verbatim (canonical keys).
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('query', 'upsert_points', 'create_collection', 'drop_collection')]}")

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


def create_coll(coll, vectors_cfg):
    s, raw = safe_request("PUT", "create_collection",
                          path_params={"name": coll},
                          body={"vectors": vectors_cfg})
    print(f"[create {coll}] status={s} raw={str(raw)[:180]}")
    if handle_transport(f"create {coll}", s, raw):
        return False
    return s in (200, 201)


def upsert(coll, points):
    s, raw = safe_request("PUT", "upsert_points",
                          path_params={"name": coll},
                          body={"points": points},
                          query_params={"wait": "true"})
    print(f"[upsert {coll} {len(points)} pts] status={s} raw={str(raw)[:180]}")
    if handle_transport("upsert", s, raw):
        return False
    return s == 200


def query_leg(tag, coll, body, expect):
    """expect: 'ok200' or 'err4xx'. Adjudicates the characteristics promise."""
    s, raw = safe_request("POST", "query", path_params={"name": coll}, body=body)
    print(f"[{tag}] status={s} raw={str(raw)[:240]}")
    if handle_transport(tag, s, raw):
        return None
    if expect == "ok200":
        if s != 200:
            DEFECTS.append(f"({tag}) characteristics-MATCH by-id lookup returned "
                           f"{s} (constraint: matching vectors must be fetched "
                           f"and used, i.e. 200) — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")
            return s
        try:
            res = json.loads(raw).get("result")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            res = None
        pts = res.get("points") if isinstance(res, dict) else None
        if not isinstance(pts, list):
            DEFECTS.append(f"({tag}) 200 but result.points is not an array "
                           f"(contract response_shape: result.points array) — "
                           f"raw={str(raw)[:150]}")
        else:
            print(f"[{tag}] OK: 200 with {len(pts)} points (positive control)")
        return s
    # err4xx leg
    if 200 <= s <= 299:
        DEFECTS.append(f"({tag}) characteristics-MISMATCH by-id lookup returned "
                       f"{s} (constraint promises an error: fetched vector does "
                       f"not match the using vector's characteristics) — "
                       f"Type1_IllegalSuccess — raw={str(raw)[:150]}")
    elif not (400 <= s <= 499):
        DEFECTS.append(f"({tag}) characteristics-MISMATCH by-id lookup returned "
                       f"unexpected status {s} — raw={str(raw)[:150]}")
    else:
        print(f"[{tag}] OK: mismatch rejected with {s} (promised error)")
    return s


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spq2_" + TS + "_"
    C_MAIN = PFX + "main"   # named vectors: t=4, i=8
    C_AUX8 = PFX + "aux8"   # unnamed 8-dim (lookup source, dim matches "i")
    C_AUX4 = PFX + "aux4"   # unnamed 4-dim (lookup source, dim mismatches "i")

    v4 = [0.9, 0.1, 0.2, 0.3]
    v8 = [0.9, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    v4b = [0.1, 0.9, 0.2, 0.3]

    try:
        if not create_coll(C_MAIN, {"t": {"size": 4, "distance": "Cosine"},
                                    "i": {"size": 8, "distance": "Cosine"}}):
            print("SETUP_ERROR: C_MAIN create failed")
            return "SCRIPT_ERROR"
        if not create_coll(C_AUX8, {"size": 8, "distance": "Cosine"}):
            print("SETUP_ERROR: C_AUX8 create failed")
            return "SCRIPT_ERROR"
        if not create_coll(C_AUX4, {"size": 4, "distance": "Cosine"}):
            print("SETUP_ERROR: C_AUX4 create failed")
            return "SCRIPT_ERROR"
        if not upsert(C_MAIN, [{"id": 1, "vector": {"t": v4}},
                               {"id": 2, "vector": {"i": v8}}]):
            print("SETUP_ERROR: C_MAIN seed failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if not upsert(C_AUX8, [{"id": 90, "vector": v8}]):
            print("SETUP_ERROR: C_AUX8 seed failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if not upsert(C_AUX4, [{"id": 91, "vector": v4b}]):
            print("SETUP_ERROR: C_AUX4 seed failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # D1 (pos): point 1 HAS "t"
        query_leg("D1-pos-using-t", C_MAIN,
                  {"query": 1, "using": "t", "limit": 3}, "ok200")
        # D2 (neg): point 1 does NOT have "i" -> characteristics mismatch
        query_leg("D2-neg-using-i-missing", C_MAIN,
                  {"query": 1, "using": "i", "limit": 3}, "err4xx")
        # D3 (pos): point 2 HAS "i"
        query_leg("D3-pos-using-i", C_MAIN,
                  {"query": 2, "using": "i", "limit": 3}, "ok200")
        # D4 (neg): vector name absent from collection config
        query_leg("D4-neg-using-nope", C_MAIN,
                  {"query": 1, "using": "nope", "limit": 3}, "err4xx")
        # D5 (pos): cross-collection lookup, dim 8 source into dim 8 "i"
        query_leg("D5-pos-lookup-dim8", C_MAIN,
                  {"query": 90, "using": "i", "limit": 3,
                   "lookup_from": {"collection": C_AUX8}}, "ok200")
        # D6 (neg): cross-collection lookup, dim 4 source into dim 8 "i"
        query_leg("D6-neg-lookup-dim4-into-8", C_MAIN,
                  {"query": 91, "using": "i", "limit": 3,
                   "lookup_from": {"collection": C_AUX4}}, "err4xx")
        # D7 (neg): unnamed-vector collection, using a name that cannot exist
        query_leg("D7-neg-unnamed-using-zzz", C_AUX4,
                  {"query": 91, "using": "zzz", "limit": 3}, "err4xx")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        if ABORT[0]:
            print("ABORT: environment/transport unavailable mid-run")
            return "SCRIPT_ERROR"
        return "NO_DEFECT"
    finally:
        for coll in (C_MAIN, C_AUX8, C_AUX4):
            try:
                rt.drop_collection(coll)
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
