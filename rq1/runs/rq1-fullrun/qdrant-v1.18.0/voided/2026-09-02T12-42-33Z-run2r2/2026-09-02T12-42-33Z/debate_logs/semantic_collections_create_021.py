#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_021
# strategy: metamorphic
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_004
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-05 (documentation drift - the Cosine-normalization promise is
#   concept-doc side; the spec-side distance semantics are what must hold)
"""
Attack: metamorphic/state_check x qdrant_behavioral_collections_create_004
  (chunk_collections+create-2of2; PUT /collections/{name} create +
  points+upsert + points+get + points+search via runtime path keys
  create_collection / upsert_points / get_point / search; URLs from
  raw_knowledge api_endpoints[].url). The contract (state_check,
  by-design side): with distance Cosine, uploaded vectors are normalized
  on storage - stored norm-1 vectors are NOT a defect. The attack probes
  the DISTANCE-SEMANTIC invariants around that by-design behavior:
  (1) Cosine face (record-only per G3): upload [3,4] -> stored readback
      expected norm-1 [0.6,0.8]; a raw echo is RECORDED, not claimed
      (the contract only defends normalization, it does not promise
      storage form);
  (2) Euclid face (hard oracle - G9 asymmetry): the SAME upload [3,4] on
      a Euclid collection must be stored RAW - normalization under Euclid
      corrupts magnitude semantics (distance to origin must stay 5, not 1)
      = Type4_StateLogicViolation;
  (3) Cosine magnitude invariance (metamorphic): searching the stored
      point with query [3,4] vs [30,40] (same direction, 10x magnitude)
      must yield equal cosine scores within 1e-3 - a material difference
      = the normalization promise leaked into score computation =
      Type4_StateLogicViolation.
  Wire enums from the contract type constraint (Cosine/Euclid/Dot/
  Manhattan); note the runtime DISTANCE_MAP is NOT used for the Euclid
  face (it would send the non-v1.18.0 wire value 'Euclidean' - G2
  contract-derived value wins; prior round measured 'Euclidean' -> 400).
  [chunk_collections+create-2of2 coverage: metamorphic x
   qdrant_behavioral_collections_create_004 (Euclid non-normalization
   hard oracle + cosine magnitude invariance + cosine record-only leg)]
Oracle: the Euclid collection stores [3,4] as [3.0,4.0] within 1e-3
  (norm 5 preserved; a norm-1 echo = Type4_StateLogicViolation); cosine
  search scores for query [3,4] and [30,40] against the same stored point
  are equal within 1e-3 (a larger gap = Type4_StateLogicViolation); the
  Cosine-face stored readback and the Euclid search score are recorded
  without defect claims (by-design / corroboration) - constraint
  qdrant_behavioral_collections_create_004.

Rationale (G3/G9): by-design normalization on Cosine is skipped as an
  attack target per threat-model discipline; the attack lives on the two
  invariant closures the by-design note implies - magnitude must survive
  where distance depends on it (Euclid) and must NOT affect scores where
  distance ignores it (Cosine).
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

# ---- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p)
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

if os.environ.get("TESTVDB_TARGET", "").lower() != "qdrant":
    print(f"VERDICT: SCRIPT_ERROR - contract target mismatch (expected qdrant, got {os.environ.get('TESTVDB_TARGET')!r})")
    sys.exit(2)

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

if not os.environ.get("TESTVDB_DB_URL"):
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

print("[path derivation] create_collection/upsert_points/get_point/search = "
      "/collections/{name}[...points...] (raw_knowledge api_endpoints[].url)")

PREFIX = "scc021_"
RUN = str(int(time.time()))
CREATED = []
TOL = 1e-3


def safe_request(method, path_key, body=None, path_params=None, query_params=None, timeout=60):
    """All HTTP through the runtime; forwards method/path_key/body/path_params/
    query_params/timeout exactly (standing lesson). Returns (status, raw_text)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def jload(raw):
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz", timeout=15)
    print(f"[{tag}] /healthz probe status={hs} raw={str(hraw)[:120]}")
    return hs


def mkn(tag):
    return f"{PREFIX}{RUN}_{tag}"


def make_coll(name, distance):
    body = {"vectors": {"size": 2, "distance": distance}}
    st, raw = safe_request("PUT", "create_collection", body,
                           path_params={"name": name})
    print(f"[create {name} distance={distance}] status={st} raw={str(raw)[:250]}")
    if st == 0:
        if liveness("transport") != 200:
            script_error("transport failure on create and /healthz down")
        script_error("transport failure on create; /healthz alive")
    if st not in (200, 201):
        script_error(f"create {name} (distance={distance}) returned {st}; "
                     f"leg unavailable; raw={str(raw)[:200]}")
    CREATED.append(name)


def upload_and_read(name, vec):
    st, raw = safe_request("PUT", "upsert_points",
                           {"points": [{"id": 1, "vector": vec}]},
                           path_params={"name": name},
                           query_params={"wait": "true"})
    print(f"[upsert {name}] status={st} raw={str(raw)[:250]}")
    if st not in (200, 201):
        script_error(f"upsert into {name} returned {st}; raw={str(raw)[:200]}")
    gst, graw = safe_request("GET", "get_point", path_params={"name": name, "point_id": 1},
                             query_params={"with_vector": "true"})
    print(f"[get_point {name}] status={gst} raw={str(graw)[:300]}")
    if gst != 200:
        if gst == 0:
            if liveness("transport") != 200:
                script_error("transport failure on get_point and /healthz down")
            script_error("transport failure on get_point; /healthz alive")
        script_error(f"get_point on {name} returned {gst}; raw={str(graw)[:200]}")
    g = jload(graw)
    res = g.get("result") if isinstance(g, dict) else None
    if not isinstance(res, dict):
        script_error(f"get_point 200 body lacks result object; raw={str(graw)[:200]}")
    v = res.get("vector")
    if not isinstance(v, list) or len(v) != 2:
        script_error(f"get_point result.vector is not a 2-float list; got {v!r}; raw={str(graw)[:200]}")
    return [float(v[0]), float(v[1])]


def search_one(name, qvec):
    st, raw = safe_request("POST", "search",
                           {"vector": qvec, "limit": 1},
                           path_params={"name": name})
    print(f"[search {name} q={qvec}] status={st} raw={str(raw)[:300]}")
    if st != 200:
        if st == 0:
            if liveness("transport") != 200:
                script_error("transport failure on search and /healthz down")
            script_error("transport failure on search; /healthz alive")
        script_error(f"search on {name} returned {st}; raw={str(raw)[:200]}")
    b = jload(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, list) or not res or not isinstance(res[0], dict):
        script_error(f"search 200 body lacks result[0]; raw={str(raw)[:200]}")
    return res[0].get("score"), res[0].get("id")


def cleanup():
    for n in list(CREATED):
        try:
            rt.drop_collection(n)
        except Exception:
            pass


def main():
    hs, hraw = safe_request("GET", "healthz", timeout=15)
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")

    try:
        # ---- Euclid face: magnitude must survive storage ----
        e = mkn("euclid")
        make_coll(e, "Euclid")
        stored_e = upload_and_read(e, [3.0, 4.0])
        norm_e = math.sqrt(stored_e[0] ** 2 + stored_e[1] ** 2)
        print(f"[euclid] stored vector = {stored_e} (L2 norm = {norm_e:.6f})")
        if abs(stored_e[0] - 3.0) > TOL or abs(stored_e[1] - 4.0) > TOL:
            defect("Type4_StateLogicViolation",
                   f"Euclid collection stored [3,4] as {stored_e} (norm {norm_e:.4f}, "
                   f"expected 5.0) - magnitude semantics corrupted: Euclid distances "
                   f"depend on magnitude, a normalized echo makes |v-0| = 1 instead of 5 "
                   f"(expected vs actual: [3.0,4.0] vs {stored_e})")
        print(f"[euclid] raw storage preserved (norm {norm_e:.4f} == 5) - distance semantics intact")
        # corroboration (recorded, no claim): Euclid search score vs origin
        score_e, _ = search_one(e, [0.0, 0.0])
        print(f"[euclid] search([0,0]) score = {score_e!r} (negative-distance convention expected ~ -5.0; recorded)")

        # ---- Cosine face: by-design normalization (record-only) + invariance (hard) ----
        c = mkn("cosine")
        make_coll(c, "Cosine")
        stored_c = upload_and_read(c, [3.0, 4.0])
        norm_c = math.sqrt(stored_c[0] ** 2 + stored_c[1] ** 2)
        print(f"[cosine] stored vector = {stored_c} (L2 norm = {norm_c:.6f})")
        if abs(norm_c - 1.0) <= TOL:
            print("[cosine] norm-1 storage confirmed - matches the by-design declaration (SKIPPED as attack per threat_model/G3)")
        else:
            print(f"[cosine] stored norm {norm_c:.4f} != 1 - RECORDED ONLY (the contract "
                  f"defends normalized storage as by-design; it does not promise it; "
                  f"the score-invariance oracle below is the binding check)")

        s1, id1 = search_one(c, [3.0, 4.0])
        s2, id2 = search_one(c, [30.0, 40.0])
        print(f"[cosine invariance] score(q=[3,4])={s1!r} (hit id {id1!r}); "
              f"score(q=[30,40])={s2!r} (hit id {id2!r})")
        if not isinstance(s1, (int, float)) or not isinstance(s2, (int, float)):
            script_error(f"search scores not numeric: {s1!r}, {s2!r}")
        if id1 != 1 or id2 != 1:
            print(f"[cosine invariance] top-hit ids {id1!r}/{id2!r} - recorded "
                  f"(single-point collection; only the score equality is claimed)")
        gap = abs(float(s1) - float(s2))
        if gap > TOL:
            defect("Type4_StateLogicViolation",
                   f"cosine score changed with query magnitude: score([3,4])={s1} vs "
                   f"score([30,40])={s2} (gap {gap:.6f} > {TOL}) - cosine similarity is "
                   f"magnitude-invariant; a material gap means normalization leaked "
                   f"into score computation (expected vs actual: |s1-s2|<=1e-3 vs {gap:.6f})")
        print(f"[cosine invariance] |s1-s2| = {gap:.8f} <= {TOL} - magnitude-invariance holds")

        print("[summary] Euclid storage preserves magnitude; cosine scores are "
              "magnitude-invariant; the by-design normalization itself was skipped "
              "as an attack target per threat_model - constraint "
              "qdrant_behavioral_collections_create_004")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
