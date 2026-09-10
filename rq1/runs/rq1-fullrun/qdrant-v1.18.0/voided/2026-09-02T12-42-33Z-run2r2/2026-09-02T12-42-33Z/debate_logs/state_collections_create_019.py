#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_019
# strategy: state_readback_normalization
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_004
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
"""
Attack: stored-state readback of the documented Cosine auto-normalization
  promise on PUT /collections/{name} + points upsert + scroll (URLs from
  raw_knowledge api_endpoints[].url). The assertion (state_check,
  evidence_tier=explicit) promises: with distance Cosine, uploaded vectors
  are normalized on storage — stored norm-1 vectors are the by-design
  state, NOT a defect. Legs: (A) create Cosine size=4, upsert ids 1,2 with
  deliberately non-normalized vectors [3,4,0,0] (norm 5) and [0,-5,12,0]
  (norm 13) wait=true, scroll with_vector=true -> each read-back vector
  must have L2 norm == 1 within 1e-3; (B) mirror control on a Euclid
  collection: the same upsert must read back ELEMENTWISE EQUAL to the
  originals (Euclid preserves magnitudes; a normalized readback there
  would corrupt distance semantics AND invalidate leg A's measurement).
  [chunk_collections+create-2of2 coverage: state_readback_normalization x
   qdrant_behavioral_collections_create_004 (Cosine stored-norm-1 promise
   + Euclid preserve-magnitude control)]
Oracle: create -> HTTP 200; upsert wait=true -> HTTP 200; scroll
  with_vector=true -> HTTP 200 returning both vectors; Cosine stored
  vectors must have |L2 norm - 1| <= 1e-3 (a stored norm equal to the
  uploaded 5 / 13 magnitudes means the documented normalization was not
  applied = Type4_StateLogicViolation); Euclid control readback must equal
  [3,4,0,0] / [0,-5,12,0] elementwise within 1e-4 (any deviation or a
  normalized Euclid readback = Type4_StateLogicViolation; a 4xx rejection
  of the legal create = SETUP_ERROR, cannot measure). 5xx responses are
  judged Type3 only after /healthz (HTTP 200) confirms liveness.
"""

import os
import sys
import json
import math
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

SRC_VECTORS = {1: [3.0, 4.0, 0.0, 0.0], 2: [0.0, -5.0, 12.0, 0.0]}  # norms 5 and 13


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)

def l2(vec):
    try:
        return math.sqrt(sum(float(x) * float(x) for x in vec))
    except (TypeError, ValueError):
        return None


def scroll_vectors(name):
    """POST scroll with_vector=true -> (status, {id: vector} or None, raw)."""
    s, raw = safe_request("POST", "scroll", path_params={"name": name},
                          body={"limit": 10, "with_vector": True,
                                "with_payload": False})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        pts = ((b or {}).get("result") or {}).get("points")
        if not isinstance(pts, list):
            return s, None, raw
        out = {}
        for p in pts:
            if isinstance(p, dict) and "id" in p:
                out[p["id"]] = p.get("vector")
        return s, out, raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def run_face(colname, distance, expect_normalized):
    """Create + upsert SRC_VECTORS + scroll readback for one distance face.
    Returns (verdict_or_None, defects_list)."""
    defects = []
    s, raw = safe_request("PUT", "create_collection", path_params={"name": colname},
                          body={"vectors": {"size": 4, "distance": distance}})
    print(f"[{distance} create] status={s} raw={raw[:200]}")
    if s == 0:
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[liveness {distance}-create-transport] healthz status={_hs} raw={str(_hraw)[:120]}")
        return "SCRIPT_ERROR", defects
    if 500 <= s <= 599 or s not in (200, 201):
        print(f"SETUP_ERROR: create({distance}) returned {s} — cannot judge face")
        return "SCRIPT_ERROR", defects
    pts = [{"id": i, "vector": v} for i, v in SRC_VECTORS.items()]
    us, uraw = safe_request("PUT", "upsert_points", path_params={"name": colname},
                            body={"points": pts}, query_params={"wait": "true"})
    print(f"[{distance} upsert] status={us} raw={uraw[:160]}")
    if us == 0 or 500 <= us <= 599:
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[liveness {distance}-upsert] healthz status={_hs} raw={str(_hraw)[:120]}")
        if _hs != 200:
            return "SCRIPT_ERROR", defects
        defects.append(f"upsert on {distance} collection returned {us} with service "
                       f"alive — Type3_RuntimeFailure — raw={uraw[:200]}")
        return "DEFECT_FOUND", defects
    if us not in (200, 201):
        print(f"SETUP_ERROR: upsert({distance}) returned {us}")
        return "SCRIPT_ERROR", defects

    ss, vecs, sraw = scroll_vectors(colname)
    print(f"[{distance} scroll] status={ss} vectors={json.dumps(vecs, default=str)[:300] if vecs else sraw[:200]}")
    if ss == 0 or 500 <= ss <= 599:
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[liveness {distance}-scroll] healthz status={_hs} raw={str(_hraw)[:120]}")
        if _hs != 200:
            return "SCRIPT_ERROR", defects
        defects.append(f"scroll on {distance} collection returned {ss} with service "
                       f"alive — Type3_RuntimeFailure — raw={sraw[:200]}")
        return "DEFECT_FOUND", defects
    if ss != 200 or not vecs:
        print(f"SETUP_ERROR: scroll({distance}) status={ss} — cannot measure stored vectors")
        return "SCRIPT_ERROR", defects
    missing_vector = [pid for pid, v in vecs.items() if not isinstance(v, list)]
    if missing_vector:
        print(f"SETUP_ERROR: scroll did not return vectors for ids {missing_vector} "
              f"(with_vector=true) — cannot measure")
        return "SCRIPT_ERROR", defects

    for pid, src in SRC_VECTORS.items():
        got = vecs.get(pid)
        if got is None:
            defects.append(f"point {pid} missing from {distance} scroll readback — "
                           f"Type4_StateLogicViolation")
            continue
        n = l2(got)
        if expect_normalized:
            if n is None or abs(n - 1.0) > 1e-3:
                defects.append(
                    f"Cosine stored vector id={pid} has L2 norm {n!r} "
                    f"(expected ~1.0 within 1e-3; uploaded norm was {l2(src)!r}) — "
                    f"documented auto-normalization not applied to stored state — "
                    f"Type4_StateLogicViolation "
                    f"(qdrant_behavioral_collections_create_004)")
        else:
            for j, (g, s0) in enumerate(zip(got, src)):
                if abs(float(g) - float(s0)) > 1e-4:
                    defects.append(
                        f"Euclid stored vector id={pid} component[{j}]={g!r} "
                        f"differs from uploaded {s0!r} — magnitude must be "
                        f"preserved (Euclid) — Type4_StateLogicViolation")
                    break
    return None, defects


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scc2e_" + TS + "_"
    C_COS = PFX + "cosn"
    C_EUC = PFX + "eucn"
    DEFECTS = []

    try:
        v1, d1 = run_face(C_COS, "Cosine", expect_normalized=True)
        DEFECTS.extend(d1)
        if v1 == "SCRIPT_ERROR":
            return "SCRIPT_ERROR"
        if v1 == "DEFECT_FOUND":
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"

        v2, d2 = run_face(C_EUC, "Euclid", expect_normalized=False)
        DEFECTS.extend(d2)
        if v2 == "SCRIPT_ERROR":
            return "SCRIPT_ERROR"

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for n in (C_COS, C_EUC):
            try:
                rt.drop_collection(n)
            except Exception:
                pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
