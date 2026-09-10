#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_017
# strategy: special_value (documented storage-transformation readback)
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_004
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: special_value x qdrant_behavioral_collections_create_004 on collections+create (chunk_collections+create-2of2 unit assertions::qdrant_behavioral_collections_create_004)
Oracle: upsert [3,4,0,0] (norm 5) into a Cosine collection -> scroll with_vector=true
  readback has L2 norm 1.0 +/- 1e-3 with direction preserved ([0.6,0.8,0,0] +/- 1e-3)
  - a NON-normalized readback (norm ~5) violates the documented storage behavior =
  Type4_StateLogicViolation; the Euclid control collection readback must stay
  [3,4,0,0] (norm ~5, delta <= 1e-6) - normalization there would be a
  Type4_StateLogicViolation too (the doc scopes normalization to Cosine);
  setup failures (create/upsert/scroll non-200) = SCRIPT_ERROR, never a defect;
  5xx with /healthz alive/dead = Type3; transport failure with healthy /healthz =
  SCRIPT_ERROR.
Unit detail: PUT /collections/{collection_name}; category=state_check, level=system,
  evidence_tier=explicit. The assertion's expected_behavior, quoted verbatim:
    "with distance Cosine, uploaded vectors are normalized on storage; by-design
     behavior - stored norm-1 vectors are not a defect"

G3 note (threat-model consumption): normalized stored vectors ARE the documented
  by-design behavior - this script verifies the promise positively in both directions
  (Cosine must normalize; Euclid must not) and only flags a violation when the
  documented behavior demonstrably does not happen (or happens where not scoped).
Legs:
  setup A: create Cosine collection (dim 4) -> judge_200;
  setup B: create Euclid control collection (dim 4) -> judge_200;
  act: PUT upsert_points {"points":[{"id":1,"vector":[3,4,0,0]}]} into each -> judge_200;
  measure: POST scroll {"limit":1,"with_vector":true,"with_payload":false} -> parse
  result.points[0].vector -> norm/direction comparison per the oracle above.
[chunk_collections+create-2of2 coverage: strategy6+1 x qdrant_resource_shard_number_001 =
  boundary_collections_create_013; envelope-positive x qdrant_behavioral_collections_create_001 =
  _014; duplicate-family x _002 = _015; enum/malformed x _003 = _016;
  cosine-normalization x qdrant_behavioral_collections_create_004 (this script);
  timeout-query x _005 = _018; visibility chain x qdrant_bc_create_visibility_001 = _019]
Constraint: qdrant_behavioral_collections_create_004
source_url: https://qdrant.tech/documentation/manage-data/collections/
doc_version: current (site latest; no version archive)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
(.sourcedeps local shard openapi.json) declares scroll's 200 grid as
{status:string, time:number, result:object with result.points[].vector:any} and the
scroll params limit (min 1) / with_vector / with_payload; upsert 200 is the standard
{result,status,time} envelope (contract response_shape for points+upsert is empty, so
the upsert envelope is observed-only; the norm oracle lives on the scroll readback).
The [3,4,0,0] probe is chosen for exact analytic normalization [0.6,0.8,0,0]
(norm-5 -> norm-1, 3-4-5 triangle) so the tolerance comparison is arithmetic, not
eyeballed.
"""
import os
import sys
import json
import math
import time
import uuid
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

PFX = "bcc17" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
CREATED = []  # every attempted collection name; cleanup drops all (no list.remove)
DIM = 4
PROBE = [3.0, 4.0, 0.0, 0.0]      # norm-5 probe; analytic normalization [0.6, 0.8, 0, 0]
TOL_NORM = 1e-3
TOL_EUCLID = 1e-6
ASSERT = ("with distance Cosine, uploaded vectors are normalized on storage; "
          "by-design behavior - stored norm-1 vectors are not a defect")


def safe_request(method, path_key, **kw):
    """Thin delegation to rt.request (DB-neutral path_key; forwards body/path_params/
    query_params/timeout exactly - qdrant runtime protocol v2.3)."""
    return rt.request(method, path_key, **kw)


def healthz_ladder(label, attempts=3, delay=2):
    """G8 liveness re-check: inline safe_request('GET','healthz') probes, 3 attempts
    2s apart. Returns a bare Type3 message if the service is down, else None."""
    for i in range(attempts):
        hs, hraw = safe_request("GET", "healthz")
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"Type3_RuntimeFailure(service-down) - '{label}': /healthz unreachable "
            f"after {attempts} attempts")


def transport_gate(label, st, raw, findings):
    """Three-outcome isolation (G8): returns True if the leg is adjudicable,
    False after recording a transport/5xx finding. Setup legs record rank 3
    (setup failure must not produce a defect conclusion)."""
    if st <= 0:
        v = healthz_ladder(label)
        if v:
            findings.append((1, v))
        else:
            findings.append((3, f"SCRIPT-ERROR-transport: '{label}' failed with healthy /healthz: {str(raw)[:150]}"))
        return False
    if 500 <= st <= 599:
        v = healthz_ladder(label)
        findings.append((1, v if v else
                         f"Type3_RuntimeFailure: '{label}' got {st} with /healthz alive; body: {str(raw)[:200]}"))
        return False
    return True


def create(name, distance):
    return safe_request("PUT", "create_collection",
                        body={"vectors": {"size": DIM, "distance": distance}},
                        path_params={"name": name}, timeout=60)


def upsert(name):
    return safe_request("PUT", "upsert_points",
                        body={"points": [{"id": 1, "vector": PROBE}]},
                        path_params={"name": name}, timeout=60)


def scroll_vector(name):
    """Returns (vector_or_None, note). Declared extraction path:
    result.points[0].vector (scroll 200 grid)."""
    st, raw = safe_request("POST", "scroll",
                           body={"limit": 1, "with_vector": True, "with_payload": False},
                           path_params={"name": name}, timeout=60)
    print(f"[scroll {name}] status={st} raw={str(raw)[:300]}")
    if st != 200:
        return None, f"scroll status={st}: {str(raw)[:150]}"
    try:
        res = json.loads(raw).get("result")
        pts = res.get("points") if isinstance(res, dict) else None
        if isinstance(pts, list) and pts and isinstance(pts[0].get("vector"), list):
            return [float(x) for x in pts[0]["vector"]], ""
        return None, f"no vector at result.points[0].vector: {str(raw)[:150]}"
    except Exception as e:
        return None, f"envelope parse: {e}"


def setup_leg(label, coll, distance, findings):
    st, raw = create(coll, distance)
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return False
    v = rt.judge_200(st, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        findings.append((3, f"SCRIPT-ERROR-setup: '{label}' legal create rejected with "
                            f"{st}: {str(raw)[:200]}"))
        return False
    return True


def upsert_leg(label, coll, findings):
    st, raw = upsert(coll)
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return False
    v = rt.judge_200(st, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        findings.append((3, f"SCRIPT-ERROR-setup: '{label}' legal upsert rejected with "
                            f"{st}: {str(raw)[:200]}"))
        return False
    return True


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[assertion quote] {ASSERT}")
    findings = []
    coll_cos = PFX + "cos"
    coll_euc = PFX + "euc"
    CREATED.extend([coll_cos, coll_euc])
    try:
        if not setup_leg(f"create Cosine collection {coll_cos}", coll_cos, "Cosine", findings):
            finish(findings)
            return
        if not setup_leg(f"create Euclid control collection {coll_euc}", coll_euc, "Euclid", findings):
            finish(findings)
            return
        if not upsert_leg(f"upsert norm-5 probe into {coll_cos}", coll_cos, findings):
            finish(findings)
            return
        if not upsert_leg(f"upsert norm-5 probe into {coll_euc}", coll_euc, findings):
            finish(findings)
            return

        # measurement leg A: Cosine readback must be normalized
        vec, note = scroll_vector(coll_cos)
        if vec is None:
            findings.append((3, f"SCRIPT-ERROR-measure: Cosine scroll readback failed ({note})"))
        else:
            norm = math.sqrt(sum(x * x for x in vec))
            d0, d1 = abs(vec[0] - 0.6), abs(vec[1] - 0.8)
            print(f"[cosine readback] vector={vec} norm={norm:.6f} "
                  f"|v0-0.6|={d0:.2e} |v1-0.8|={d1:.2e}")
            if abs(norm - 1.0) <= TOL_NORM and d0 <= TOL_NORM and d1 <= TOL_NORM:
                print("[conform] Cosine stored vector is normalized (documented "
                      "by-design storage behavior confirmed)")
            else:
                findings.append((2, f"Type4_StateLogicViolation: Cosine collection stored "
                                    f"vector {vec} (norm {norm:.6f}) is NOT normalized - the "
                                    f"documented 'normalized on storage' behavior is violated"))

        # measurement leg B: Euclid control readback must NOT be normalized
        vec, note = scroll_vector(coll_euc)
        if vec is None:
            findings.append((3, f"SCRIPT-ERROR-measure: Euclid control scroll readback failed ({note})"))
        else:
            drift = max(abs(a - b) for a, b in zip(vec, PROBE))
            print(f"[euclid control readback] vector={vec} max|delta-sent|={drift:.2e}")
            if drift <= TOL_EUCLID:
                print("[conform] Euclid control stored vector unchanged (normalization "
                      "is scoped to Cosine)")
            else:
                norm = math.sqrt(sum(x * x for x in vec))
                findings.append((2, f"Type4_StateLogicViolation: Euclid control stored vector "
                                    f"{vec} (norm {norm:.6f}) differs from sent {PROBE} - "
                                    f"normalization is documented for Cosine only"))

        finish(findings)
    finally:
        # data-bearing create endpoint: these collections are ours - drop best-effort
        for n in list(CREATED):
            try:
                rt.drop_collection(n)
            except Exception as e:
                print(f"cleanup warning (drop {n}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: Cosine stored vectors normalized (norm 1) and Euclid control unchanged")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
