#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_012
# strategy: illegal_rejection
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_004
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (boundary closure - inclusive minima and both endpoints of
#   the deleted_threshold [0, 1] interval are legal and must not be refused)
"""
Attack: illegal_rejection (Type-1 reverse: legal input wrongly rejected) x
  qdrant_range_collections_create_004 (chunk_collections+create-1of2;
  PUT /collections/{name}, path_key create_collection from runtime PATHS,
  URL from raw_knowledge api_endpoints[collections+create].url). The
  assertion (evidence_tier=explicit): optimizers_config at create takes the
  OptimizersConfigDiff schema with bounds deleted_threshold in [0, 1],
  vacuum_min_vector_number minimum 100, max_segment_size minimum 1 (KB),
  memmap_threshold minimum 0, indexing_threshold minimum 0 (KB). NOTE the
  wire asymmetry (spec-derived): the request field is "optimizers_config"
  while the describe readback serves "result.config.optimizer_config" (no
  's') - per that response_shape grid. Probes (fresh names):
    - create A: ALL minima at once (deleted_threshold=0.0, vacuum=100,
      max_segment_size=1, memmap=0, indexing=0) -> 200
    - create B: deleted_threshold=1.0 (upper endpoint of the closed
      interval) -> 200
    Persistence echoes checked where distinguishable from defaults
      (deleted_threshold 0.0/1.0 vs default, vacuum 100 vs default 1000);
      threshold echoes recorded.
  [chunk_collections+create-1of2 coverage: illegal_rejection x
   qdrant_range_collections_create_004 (all minima + upper endpoint
   accepted; persistence echoes)]
Oracle: both creates return 200 result=true (any 4xx = Type1_IllegalRejection
  - inclusive bounds refused; 5xx with /healthz alive = Type3_RuntimeFailure)
  and describe echoes optimizer_config.deleted_threshold == 0.0 / == 1.0 and
  vacuum_min_vector_number == 100 (echo mismatch on a
  default-distinguishable field = Type4_StateLogicViolation) - constraint
  qdrant_range_collections_create_004.

Rationale (G4/G7/D3b): the closure direction (minima + closed-interval upper
endpoint must be accepted) is this script's claim; the violation direction
belongs to semantic_collections_create_013. The readback path was aligned
with the published response_shape (optimizer_config, not optimizers_config)
before writing so the persistence assertion cannot fail on a name guess.
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

PREFIX = "scc12_"
RUN = str(int(time.time()))
CREATED = []
DENSE = {"size": 4, "distance": "Cosine"}
EPS = 1e-9


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


def create(name, optimizers):
    st, raw = safe_request("PUT", "create_collection",
                           {"vectors": DENSE, "optimizers_config": optimizers},
                           path_params={"name": name})
    print(f"[create {name}] status={st} raw={str(raw)[:300]}")
    if st in (200, 201):
        CREATED.append(name)
    return st, raw


def describe_optimizer(name):
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
    opt = cfg.get("optimizer_config")
    if not isinstance(opt, dict):
        script_error(f"describe of {name} returned no config.optimizer_config "
                     f"(response_shape declares result.config.optimizer_config; the "
                     f"request field is optimizers_config - wire asymmetry): "
                     f"raw={str(raw)[:200]}")
    return opt


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

        # ---- create A: all minima at once ----
        minima = {"deleted_threshold": 0.0, "vacuum_min_vector_number": 100,
                  "max_segment_size": 1, "memmap_threshold": 0,
                  "indexing_threshold": 0}
        name = mkn("ok_minima")
        st, raw = create(name, minima)
        if st == 0:
            liveness("transport")
            script_error("transport failure on all-minima optimizers create; no defect conclusion")
        if 500 <= st <= 599:
            if liveness("5xx") != 200:
                script_error(f"all-minima optimizers create 5xx ({st}) and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"[opt minima] legal minima create raised server error {st} while "
                   f"/healthz is alive; raw={str(raw)[:200]}")
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"[opt minima] optimizers_config at the exact inclusive bounds "
                   f"{minima} was refused with {st}; constraint "
                   f"qdrant_range_collections_create_004 declares deleted_threshold "
                   f"in [0,1], vacuum_min_vector_number>=100, max_segment_size>=1, "
                   f"memmap_threshold>=0, indexing_threshold>=0 - bounds are "
                   f"inclusive; raw={str(raw)[:250]}")
        b = jload(raw)
        if not isinstance(b, dict) or b.get("result") is not True:
            defect("Type4_StateLogicViolation",
                   f"[opt minima] 200 body must carry result=true (response_shape "
                   f"result:boolean); raw={str(raw)[:250]}")
        opt = describe_optimizer(name)
        print(f"[opt minima] persisted optimizer_config = {opt!r}")
        checks = [
            ("deleted_threshold", 0.0, "closed-interval lower endpoint"),
            ("vacuum_min_vector_number", 100, "distinguishable from default 1000"),
        ]
        for field, expected, note in checks:
            got = opt.get(field)
            if not isinstance(got, (int, float)) or isinstance(got, bool) \
                    or abs(float(got) - expected) > EPS:
                defect("Type4_StateLogicViolation",
                       f"[opt minima] expected result.config.optimizer_config.{field} "
                       f"== {expected} ({note}), got {got!r} (expected vs actual "
                       f"mismatch); optimizer_config={opt!r}")
            print(f"[opt minima] optimizer_config.{field} echo == {expected} (OK)")
        for field in ["max_segment_size", "memmap_threshold", "indexing_threshold"]:
            print(f"[opt minima] optimizer_config.{field} echo = {opt.get(field)!r} "
                  f"(recorded; threshold fields may be normalized by the resolved "
                  f"config)")

        # ---- create B: deleted_threshold upper endpoint ----
        name = mkn("ok_dt1")
        st, raw = create(name, {"deleted_threshold": 1.0})
        if st == 0:
            liveness("transport")
            script_error("transport failure on deleted_threshold=1.0 create; no defect conclusion")
        if 500 <= st <= 599:
            if liveness("5xx") != 200:
                script_error(f"deleted_threshold=1.0 create 5xx ({st}) and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"[dt 1.0] legal upper-endpoint create raised server error {st}; "
                   f"raw={str(raw)[:200]}")
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"[dt 1.0] deleted_threshold=1.0 (the CLOSED interval [0,1] "
                   f"includes 1.0) was refused with {st}; raw={str(raw)[:250]}")
        b = jload(raw)
        if not isinstance(b, dict) or b.get("result") is not True:
            defect("Type4_StateLogicViolation",
                   f"[dt 1.0] 200 body must carry result=true; raw={str(raw)[:250]}")
        opt = describe_optimizer(name)
        got = opt.get("deleted_threshold")
        print(f"[dt 1.0] persisted deleted_threshold echo = {got!r}")
        if not isinstance(got, (int, float)) or isinstance(got, bool) \
                or abs(float(got) - 1.0) > EPS:
            defect("Type4_StateLogicViolation",
                   f"[dt 1.0] expected optimizer_config.deleted_threshold == 1.0, "
                   f"got {got!r} (expected vs actual mismatch)")

        print("[summary] all-minima optimizers_config and the deleted_threshold "
              "upper endpoint accepted with exact echoes - inclusive-bounds "
              "promise holds per qdrant_range_collections_create_004")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
