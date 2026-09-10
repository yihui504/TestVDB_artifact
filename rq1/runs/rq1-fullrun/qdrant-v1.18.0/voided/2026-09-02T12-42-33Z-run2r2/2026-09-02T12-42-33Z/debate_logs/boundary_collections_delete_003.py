#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_delete_003
# strategy: boundary (behavioral, stateful double-delete replay)
# endpoint: collections+delete
# constraint_ids: qdrant_behavioral_collections_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 Boundary Default Optimism (the replayed delete hits whatever
#   existence view the handler consults - a stale routing/metadata cache answers
#   200-ok from the pre-delete state)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral-stateful x qdrant_behavioral_collections_delete_001 on collections+delete (chunk_collections+delete unit assertions::qdrant_behavioral_collections_delete_001)
Oracle: create (setup premise) -> DELETE #1 -> 200 with envelope result:true ->
  immediate DELETE #2 (identical replay against mutated state) -> exactly 404;
  DELETE #2 returning 2xx = Type1_IllegalSuccess (assertion: "returns 404, not
  200"); DELETE #2 400/422 = conform-with-note; 5xx with /healthz alive/dead =
  Type3; transport failure with healthy /healthz = SCRIPT_ERROR. If DELETE #1
  itself is not 200, the leg is adjudicated as the _001 oracle (documented-legal
  delete rejected = Type4 disposition conflict) and the replay is skipped.
Unit detail: DELETE /collections/{collection_name}. The assertion's
  expected_behavior, quoted verbatim:
    "DELETE on an existing collection returns HTTP 200; DELETE on a non-existent
     collection returns 404, not 200"
G6 mutation justification (why THIS mutation): the first 200 delete is the
  state-flip mutation; replaying the byte-identical request immediately after
  probes whether the handler's existence check consults live state or a stale
  view (routing table / metadata cache / async tombstone lag). Duplicating a
  request against freshly-mutated state is the classic way to surface
  read-after-write staleness on the control plane, which a never-existed probe
  (_002) cannot reach: never-existed names have no cache entry to go stale.
G3 avoidance note: threat_model by-design entry "Idempotent DELETE returns 200
  even if point doesn't exist" is scoped to POINTS delete; the collections+delete
  spec declares 404 for non-existent collections - after a real delete the
  collection IS non-existent, so 200 on the replay is adjudicated, not excused.
[chunk_collections+delete coverage: behavioral-positive x qdrant_behavioral_collections_delete_001
  = _001; behavioral-negative-404 x same assertion = _002; stateful double-delete
  x same assertion (this script); strategy4+7 malformed-names x same assertion
  = _004; invisibility-chain x qdrant_bc_delete_invisibility_001 = _005]
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

PFX = "bcd3" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
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


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[assertion quote] {ASSERT}")
    findings = []
    name = PFX + "dbl"
    try:
        # ---- setup premise: create (failure = setup failure, G8) ----
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

        # ---- mutation: DELETE #1 (must be the 200 leg of the assertion) ----
        st1, raw1 = safe_request("DELETE", "drop_collection",
                                 path_params={"name": name}, timeout=60)
        print(f"[delete #1 {name}] status={st1} raw={str(raw1)[:300]}")
        if not transport_gate("delete #1", st1, raw1, findings):
            finish(findings)
            return
        if st1 != 200 or not envelope_result_true(raw1):
            findings.append((2, f"Type4 disposition: DELETE #1 on existing collection "
                                f"returned {st1} (envelope ok={envelope_result_true(raw1)}); "
                                f"expected the declared 200 + result:true; raw: {str(raw1)[:200]}"))
            finish(findings)
            return

        # ---- replay: DELETE #2, byte-identical, immediately after the state flip ----
        st2, raw2 = safe_request("DELETE", "drop_collection",
                                 path_params={"name": name}, timeout=60)
        print(f"[delete #2 replay {name}] status={st2} raw={str(raw2)[:300]}")

        # ---- assert: declare expectation first, then compare (D3a) ----
        if not transport_gate("delete #2", st2, raw2, findings):
            pass
        elif st2 == 404:
            named = name in str(raw2)
            print(f"[conform] replayed DELETE -> 404 (collection is non-existent after "
                  f"the 200 delete); body names the collection: {named} (observe-only)")
        elif 200 <= st2 <= 299:
            findings.append((0, f"Type1_IllegalSuccess: replayed DELETE after a 200 "
                                f"delete returned {st2} - the deleted '{name}' is "
                                f"non-existent and the assertion demands 404, not 200; "
                                f"raw: {str(raw2)[:200]}"))
        elif 400 <= st2 <= 499:
            print(f"[conform-with-note] replayed DELETE -> {st2} (rejected, but not "
                  f"the declared 404 - measured conflict zone, judge to weigh; "
                  f"raw: {str(raw2)[:150]})")
        else:
            findings.append((3, f"SCRIPT-ERROR: unexpected status {st2}: {str(raw2)[:150]}"))
        finish(findings)
    finally:
        # deletes are destructive: this collection is ours - drop best-effort
        # (no-op if delete #1/#2 already removed it)
        try:
            rt.drop_collection(name)
        except Exception as e:
            print(f"cleanup warning (drop {name}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: DELETE #1 -> 200 result:true; immediate identical replay -> 404 "
          "(existence state flipped by the first delete)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
