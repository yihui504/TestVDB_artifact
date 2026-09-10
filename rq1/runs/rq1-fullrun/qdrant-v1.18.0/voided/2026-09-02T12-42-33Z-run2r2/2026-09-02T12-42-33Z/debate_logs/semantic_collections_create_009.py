#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_009
# strategy: illegal_rejection
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (boundary closure - the minima themselves are legal values
#   and must NOT be refused; off-by-one validation is the classic leak)
"""
Attack: illegal_rejection (Type-1 reverse: legal input wrongly rejected) x
  qdrant_range_collections_create_002 (chunk_collections+create-1of2;
  PUT /collections/{name}, path_key create_collection from runtime PATHS,
  URL from raw_knowledge api_endpoints[collections+create].url). The
  assertion (evidence_tier=explicit): hnsw_config at create takes the
  HnswConfigDiff schema with inclusive minima - m >= 0, ef_construct >= 4,
  full_scan_threshold >= 10 (KB), max_indexing_threads >= 0 (0 = auto),
  payload_m >= 0. G4 boundary closure: ONE create carrying ALL five fields at
  their exact minimum values must be accepted (schema minimums are inclusive),
  and the describe readback result.config.hnsw_config (response_shape:
  hnsw_config.m/ef_construct/full_scan_threshold/max_indexing_threads integer,
  payload_m integer|null) must echo the set values where distinguishable from
  defaults (m=0 vs default 16, ef_construct=4 vs default 100,
  full_scan_threshold=10 vs default 10 - equal-to-default echo recorded,
  payload_m=0 vs default 16; max_indexing_threads=0 means auto and the
  resolved config may substitute the auto-resolved thread count - recorded,
  not a mismatch claim).
  [chunk_collections+create-1of2 coverage: illegal_rejection x
   qdrant_range_collections_create_002 (all five minima accepted at once +
   persistence echoes)]
Oracle: the all-minima create (m=0, ef_construct=4, full_scan_threshold=10,
  max_indexing_threads=0, payload_m=0) returns 200 result=true (any 4xx =
  Type1_IllegalRejection - inclusive minima refused; 5xx with /healthz alive =
  Type3_RuntimeFailure) and describe echoes hnsw_config.m==0,
  ef_construct==4, payload_m==0 (echo != set value for a
  distinguishable-from-default field = Type4_StateLogicViolation;
  full_scan_threshold==10 and auto-resolved max_indexing_threads recorded) -
  constraint qdrant_range_collections_create_002.

Rationale (G4/G7/D3b): minima-are-legal is the promise's closure direction
(the violation direction is semantic_collections_create_010's business); the
readback expectations were aligned with the describe response_shape grid
before writing, and defaults-equal or auto-resolved echoes are recorded
instead of falsely claimed.
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

print("[path derivation] create_collection = /collections/{name} "
      "(raw_knowledge api_endpoints[collections+create].url = /collections/{collection_name})")

PREFIX = "scc09_"
RUN = str(int(time.time()))
CREATED = []


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


def create(name, body):
    st, raw = safe_request("PUT", "create_collection", body, path_params={"name": name})
    print(f"[create {name}] status={st} raw={str(raw)[:300]}")
    if st in (200, 201):
        CREATED.append(name)
    return st, raw


def describe_hnsw(name):
    st, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    print(f"[describe {name}] status={st} raw={str(raw)[:300]}")
    if st != 200:
        script_error(f"describe of freshly created {name} returned {st}; readback unavailable")
    b = jload(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        script_error(f"describe of {name} returned no result object: raw={str(raw)[:200]}")
    cfg = res.get("config")
    if not isinstance(cfg, dict):
        script_error(f"describe of {name} returned no config object: raw={str(raw)[:200]}")
    hnsw = cfg.get("hnsw_config")
    if not isinstance(hnsw, dict):
        script_error(f"describe of {name} returned no config.hnsw_config object "
                     f"(response_shape declares result.config.hnsw_config): "
                     f"raw={str(raw)[:200]}")
    return hnsw


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
        ok, err = rt.setup_default(mkn("ctl"), 4, "Cosine")
        if not ok:
            script_error(f"control setup_default failed: {err}")
        print("[control] setup_default create OK (deployment healthy)")
        try:
            rt.drop_collection(mkn("ctl"))
        except Exception:
            pass

        minima = {"m": 0, "ef_construct": 4, "full_scan_threshold": 10,
                  "max_indexing_threads": 0, "payload_m": 0}
        name = mkn("ok_minima")
        st, raw = create(name, {"vectors": {"size": 4, "distance": "Cosine"},
                                "hnsw_config": minima})
        if st == 0:
            liveness("transport")
            script_error("transport failure on all-minima create; no defect conclusion")
        if 500 <= st <= 599:
            if liveness("5xx") != 200:
                script_error(f"all-minima create 5xx ({st}) and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"[all-minima] legal minima create raised server error {st} while "
                   f"/healthz is alive; raw={str(raw)[:200]}")
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"[all-minima] hnsw_config at the exact inclusive minima {minima} "
                   f"was refused with {st}; constraint qdrant_range_collections_create_"
                   f"002 declares m>=0, ef_construct>=4, full_scan_threshold>=10, "
                   f"max_indexing_threads>=0 (0=auto), payload_m>=0 - schema minima "
                   f"are inclusive; raw={str(raw)[:250]}")
        b = jload(raw)
        if not isinstance(b, dict) or b.get("result") is not True:
            defect("Type4_StateLogicViolation",
                   f"[all-minima] 200 body must carry result=true (response_shape "
                   f"result:boolean); raw={str(raw)[:250]}")
        print("[all-minima] accepted with 200 and result=true")

        hnsw = describe_hnsw(name)
        print(f"[all-minima] persisted hnsw_config = {hnsw!r}")

        for field, expected, note in [
            ("m", 0, "distinguishable from default"),
            ("ef_construct", 4, "distinguishable from default"),
            ("payload_m", 0, "distinguishable from default"),
        ]:
            got = hnsw.get(field)
            if got != expected:
                defect("Type4_StateLogicViolation",
                       f"[all-minima] expected result.config.hnsw_config.{field} == "
                       f"{expected} ({note}), got {got!r} (expected vs actual mismatch); "
                       f"hnsw_config={hnsw!r}")
            print(f"[all-minima] hnsw_config.{field} echo == {expected} (OK)")

        fst = hnsw.get("full_scan_threshold")
        print(f"[all-minima] hnsw_config.full_scan_threshold echo = {fst!r} "
              f"(minimum 10 equals the resolved default; recorded)")
        mit = hnsw.get("max_indexing_threads")
        print(f"[all-minima] hnsw_config.max_indexing_threads echo = {mit!r} "
              f"(0 means auto; a resolved positive thread count is normalization, "
              f"recorded)")

        print("[summary] all five HnswConfigDiff minima accepted at once; the three "
              "default-distinguishable echoes match exactly - inclusive-minima "
              "promise holds per qdrant_range_collections_create_002")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
