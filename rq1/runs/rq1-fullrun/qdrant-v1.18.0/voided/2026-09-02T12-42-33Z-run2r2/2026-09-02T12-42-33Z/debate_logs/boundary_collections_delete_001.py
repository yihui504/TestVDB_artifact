#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_delete_001
# strategy: boundary (behavioral both-direction, positive closure leg)
# endpoint: collections+delete
# constraint_ids: qdrant_behavioral_collections_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 Boundary Default Optimism (assuming the 200-ok envelope is
#   always well-formed for the success face; the response grid result:boolean
#   is checked, not just the status line)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral-positive x qdrant_behavioral_collections_delete_001 on collections+delete (chunk_collections+delete unit assertions::qdrant_behavioral_collections_delete_001)
Oracle: DELETE /collections/{c} on an existing (self-created, unique-prefix)
  collection -> exactly 200 with envelope result being boolean true
  (response_shape grid: result:boolean); a 4xx on this documented-legal delete =
  Type4 disposition conflict; 200 without result:true = Type4_StateLogicViolation;
  5xx/OOM/panic or /healthz death = Type3_RuntimeFailure; transport failure with
  healthy /healthz = SCRIPT_ERROR. Setup premise (create + describe 200) failure
  is a setup failure, never a defect conclusion (G8).
Unit detail: DELETE /collections/{collection_name} (URL verbatim from raw_knowledge
  api_endpoints[collections+delete].url). The assertion's expected_behavior,
  quoted verbatim:
    "DELETE on an existing collection returns HTTP 200; DELETE on a non-existent
     collection returns 404, not 200"
  This script is the positive leg (existing -> 200); the 404 leg is
  boundary_collections_delete_002, the stateful double-delete face is _003, the
  malformed-name face is _004, and the post-delete invisibility contract is
  boundary_collections_delete_005 (unit qdrant_bc_delete_invisibility_001).
[chunk_collections+delete coverage: behavioral-positive x qdrant_behavioral_collections_delete_001
  (this script); behavioral-negative-404 x same assertion = _002; stateful
  double-delete x same assertion = _003; strategy4+7 malformed-names x same
  assertion = _004; invisibility-chain x qdrant_bc_delete_invisibility_001 = _005]
Constraint: qdrant_behavioral_collections_delete_001
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R11-lesson spec-grid cross-check (BEFORE oracle): raw_knowledge
api_endpoints[collections+delete] declares expected_responses {"200": "ok",
"404": "not found"} and the state constraint "deleting an existing collection is
asynchronous-ish but confirmed 200 (runtime verified 200 on real delete)";
contract response_shape declares the success grid {status:string, time:number,
result:boolean}. So the positive oracle is 200 + result:boolean true; 2xx other
than 200 (e.g. 202) is a measured conflict zone printed for the judge.
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

PFX = "bcd1" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4
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


def envelope_result_true(raw):
    try:
        env = json.loads(raw) if raw else {}
    except Exception:
        return False
    return isinstance(env, dict) and isinstance(env.get("result"), bool) and env["result"]


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: DELETE on existing self-created collection returned 200 with "
          "envelope result:boolean=true (positive leg of the 200/404 assertion)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[assertion quote] {ASSERT}")
    findings = []
    name = PFX + "pos"
    try:
        # ---- setup premise: create + describe 200 (failure = setup failure, G8) ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": name}, timeout=60)
        print(f"[create {name}] status={st} raw={str(raw)[:300]}")
        if not transport_gate(f"create {name}", st, raw, findings):
            finish(findings)
            return
        if st not in (200, 201):
            findings.append((3, f"SCRIPT-ERROR-setup: create returned {st}: {str(raw)[:150]}"))
            finish(findings)
            return
        dst, draw = safe_request("GET", "describe_collection",
                                 path_params={"name": name}, timeout=30)
        print(f"[describe {name}] status={dst} raw={str(draw)[:200]}")
        if dst != 200:
            findings.append((3, f"SCRIPT-ERROR-setup: describe returned {dst} after a "
                                f"200 create: {str(draw)[:150]}"))
            finish(findings)
            return

        # ---- act: DELETE an existing collection (documented-legal) ----
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": name}, timeout=60)
        print(f"[delete {name}] status={st} raw={str(raw)[:300]}")

        # ---- assert: declare expectation first, then compare (D3a) ----
        if not transport_gate(f"delete {name}", st, raw, findings):
            finish(findings)
            return
        if st == 200:
            if envelope_result_true(raw):
                print("[conform] existing-collection DELETE -> 200 with result:true "
                      "(assertion positive leg)")
            else:
                findings.append((2, "Type4_StateLogicViolation: existing-collection "
                                    f"DELETE -> 200 but envelope violates the "
                                    f"result:boolean=true grid; raw: {str(raw)[:200]}"))
        elif 200 < st <= 299:
            # measured conflict zone: expected_responses declare only 200/404
            findings.append((2, f"Type4 disposition: existing-collection DELETE -> "
                                f"{st}, not the declared 200; raw: {str(raw)[:200]}"))
        else:
            v = rt.judge_200(st, raw, setup_ok=True)
            if v == "DEFECT_FOUND":
                findings.append((2, f"Type4 disposition conflict: documented-legal "
                                    f"delete of an existing collection rejected with "
                                    f"{st}; raw: {str(raw)[:200]}"))
            else:
                findings.append((3, f"SCRIPT-ERROR: delete judge={v} status={st} "
                                    f"raw={str(raw)[:150]}"))
        finish(findings)
    finally:
        # deletes are destructive: this collection is ours - drop best-effort
        # (idempotent even if the leg under test already deleted it)
        try:
            rt.drop_collection(name)
        except Exception as e:
            print(f"cleanup warning (drop {name}): {e}")


if __name__ == "__main__":
    main()
