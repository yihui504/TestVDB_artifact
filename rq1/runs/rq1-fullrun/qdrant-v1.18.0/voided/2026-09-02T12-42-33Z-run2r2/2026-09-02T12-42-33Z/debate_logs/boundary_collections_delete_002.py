#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_delete_002
# strategy: boundary (behavioral both-direction, negative 404 leg)
# endpoint: collections+delete
# constraint_ids: qdrant_behavioral_collections_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 Boundary Default Optimism (a delete handler that always
#   answers 200-ok without consulting existence state is exactly this blindspot)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral-negative x qdrant_behavioral_collections_delete_001 on collections+delete (chunk_collections+delete unit assertions::qdrant_behavioral_collections_delete_001)
Oracle: DELETE /collections/{c} on a NEVER-created name (unique prefix, so it
  cannot exist) -> exactly 404 (raw_knowledge expected_responses declare
  {"200": "ok", "404": "not found"}); any 2xx = Type1_IllegalSuccess (assertion
  says "returns 404, not 200" and defect_type_if_violated=Type1_IllegalSuccess);
  400/422 = conform-with-note (rejected, but not the declared 404 - measured
  conflict zone for the judge, not adjudicated); 5xx with /healthz alive/dead =
  Type3; transport failure with healthy /healthz = SCRIPT_ERROR.
Unit detail: DELETE /collections/{collection_name}. The assertion's
  expected_behavior, quoted verbatim:
    "DELETE on an existing collection returns HTTP 200; DELETE on a non-existent
     collection returns 404, not 200"
  This script is the negative leg (non-existent -> 404).
G3 avoidance note: the threat_model by-design entry "Idempotent DELETE returns
  200 even if point doesn't exist" is scoped to POINTS delete
  (collections+points delete face); the collections+delete spec explicitly
  declares 404 for a non-existent collection, so this leg is NOT the by-design
  scenario and is fully adjudicated.
Adjudication note (D3a rule 2): hand-written expected-vs-actual, because the
  runtime helper rt.expect_rejected classifies 404 as SCRIPT_ERROR
  (environment error) - but here 404 IS the declared expectation, so the
  helper is unsuitable and the comparison is written out explicitly.
Type-2 observe-only: on the conforming 404, the error body is checked (observe
  only) for naming the missing collection (runtime-verified message shape
  "Not found: Collection `...` doesn't exist!"); absence is recorded for the
  judge, never adjudicated as a defect.
[chunk_collections+delete coverage: behavioral-positive x qdrant_behavioral_collections_delete_001
  = _001; behavioral-negative-404 x same assertion (this script); stateful
  double-delete = _003; strategy4+7 malformed-names = _004; invisibility-chain
  x qdrant_bc_delete_invisibility_001 = _005]
Constraint: qdrant_behavioral_collections_delete_001
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
import os
import sys
import json
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

PFX = "bcd2" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
ASSERT = ("DELETE on an existing collection returns HTTP 200; DELETE on a "
          "non-existent collection returns 404, not 200")


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
    False after recording a transport/5xx finding."""
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


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[assertion quote] {ASSERT}")
    findings = []
    # never-created leg: unique ownership prefix means this name cannot exist
    # (dispatch instruction: use never-created names for 404 legs - no state is
    # created, so nothing of ours or anyone else's can be destroyed)
    never = PFX + "never404"
    try:
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": never}, timeout=60)
        print(f"[delete never-created {never}] status={st} raw={str(raw)[:300]}")

        # ---- assert: declare expectation first, then compare (D3a) ----
        if not transport_gate(f"delete {never}", st, raw, findings):
            pass
        elif st == 404:
            # Type-2 observe-only: does the error body name the missing collection?
            named = never in str(raw)
            print(f"[conform] never-collection DELETE -> 404 (declared expectation); "
                  f"body names the collection: {named} (Type-2 observe-only)")
        elif 200 <= st <= 299:
            findings.append((0, f"Type1_IllegalSuccess: DELETE on never-created "
                                f"'{never}' returned {st} - assertion demands 404, "
                                f"not 200; raw: {str(raw)[:200]}"))
        elif 400 <= st <= 499:
            print(f"[conform-with-note] never-collection DELETE -> {st} (rejected, "
                  f"but not the declared 404 - measured conflict zone, judge to "
                  f"weigh; raw: {str(raw)[:150]})")
        else:
            findings.append((3, f"SCRIPT-ERROR: unexpected status {st}: {str(raw)[:150]}"))

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: DELETE on a never-created collection returned the declared 404")
        print("VERDICT: NO_DEFECT")
        sys.exit(0)
    finally:
        # nothing was created by this script; defensive best-effort drop of the
        # never-name is a no-op if adjudication is correct and is wrapped anyway
        try:
            rt.drop_collection(never)
        except Exception as e:
            print(f"cleanup warning (drop {never}): {e}")


if __name__ == "__main__":
    main()
