#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_get_003
# strategy: behavioral_contract
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift / behavioral consistency - the
#   assertion lists points_count and indexed_vectors_count as part of the
#   promised 200 body; a counter that lags or ignores committed mutations
#   makes the describe face report state that is not the collection's
#   state - drift between the documented observability contract and the
#   implementation)
"""
Attack: behavioral_contract (S1, counter-truthfulness variant) x
  qdrant_behavioral_collections_get_001 on collections+get
  (chunk_collections+get unit
  assertions::qdrant_behavioral_collections_get_001). The assertion's
  description lists the counters as first-class promised content: "returns
  200 with full config (params, hnsw_config, optimizer_config, wal_config,
  quantization_config), status (green|yellow|red), points_count,
  indexed_vectors_counts". This script holds the counter half of that
  promise against the collection's actual committed state:
    leg A baseline   - fresh empty collection -> describe's points_count
                       must be present and, when non-null, exactly 0
    leg B after-add  - upsert of 5 points with wait=true (the synchronous
                       commit mode) -> points_count must be integer 5
    leg C after-del  - waited delete of 2 of those points -> points_count
                       must be integer 3
  Grid note (D3b-1): result.points_count is grid-typed integer|null. On
  leg A (no mutation has ever been committed) a null is tolerated with a
  printed note; on legs B/C a wait=true mutation HAS been acknowledged
  with 200, so the collection's committed state is exactly 5 (resp. 3)
  points and a null/absent counter there is state that fails to reconcile
  (Type4), not a legal shape.
  Observed-only (never asserted): indexed_vectors_count - the HNSW build
  is asynchronous and optimizer-timing dependent, so its value is printed
  at each leg as a note only (G3: no nondeterministic oracle).
  G6 mutation justification: the committed-counter reconciliation point
  after each SYNCHRONOUS (wait=true) mutation is where a cached/deferred
  counter most easily desyncs - the write is acknowledged before the read,
  leaving no eventual-consistency window to hide a lagging counter.
  [chunk_collections+get coverage: behavioral_contract x
   qdrant_behavioral_collections_get_001 (points_count truthfulness across
   committed mutations) - this script; 200-full-config grid vs 404 = _001;
   config-echo = _002; metamorphic alias equivalence = _004; error-body
   quality = _005; legal-name family = _006]
Oracle: leg A describe returns 200 with points_count present and either
  null (tolerated, printed) or integer 0 - any other integer =
  Type4_StateLogicViolation (fresh collection cannot hold points); leg B
  after a 200-acknowledged wait=true upsert of 5 points returns
  points_count integer exactly 5; leg C after a 200-acknowledged wait=true
  delete of 2 points returns points_count integer exactly 3 - in legs B/C
  a null/absent/non-integer counter = Type4 (committed state not
  reflected), a different integer = Type4 (untruthful counter); non-200
  describe on the existing collection = Type1_IllegalRejection; upsert/
  delete mutation failures = SCRIPT_ERROR (setup premise, never a defect);
  5xx with /healthz alive = Type3; transport failure with healthy
  /healthz = SCRIPT_ERROR (G8).

Rationale (G4/G6/G7): both directions of the counter promise are probed
  (up increases, delete decreases) on one setup so a counter that only
  moves one way is caught; every mutation is synchronous (wait=true as a
  URL query param, never body - v34 R1 S1 lesson) so the oracle has no
  race window to blame. is_int() excludes bool so a true/false leaking
  into the counter fails loudly.
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

# describe face: runtime PATHS key describe_collection, cross-checked against
# raw_knowledge api_endpoints[path=collections+get].url = /collections/{collection_name}
DESCRIBE_KEY = "describe_collection"
print(f"[path derivation] {DESCRIBE_KEY} = {rt.PATHS[DESCRIBE_KEY]} "
      f"(runtime PATHS; matches raw_knowledge api_endpoints[collections+get].url "
      f"/collections/{{collection_name}})")

PFX = "scg03" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4
N_ADD, N_DEL = 5, 2


def safe_request(method, path_key, **kw):
    """Thin delegation to rt.request (DB-neutral path_key; forwards body/
    path_params/query_params/timeout exactly - standing lesson)."""
    return rt.request(method, path_key, **kw)


def healthz_ladder(label, attempts=3, delay=2):
    """G8 liveness re-check: inline safe_request('GET','healthz') probes."""
    for i in range(attempts):
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"Type3_RuntimeFailure(service-down) - '{label}': /healthz unreachable "
            f"after {attempts} attempts")


def transport_gate(label, st, raw, findings):
    """Three-outcome isolation (G8): True if adjudicable, False after recording."""
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


def is_int(v):
    """Grid-typed integer: bool excluded (Python bool is an int subclass)."""
    return isinstance(v, int) and not isinstance(v, bool)


def describe_counters(name):
    """GET /collections/{name} -> (status, raw, points_count, indexed_vectors_count,
    result_present). Counters left as None when absent/not parseable."""
    st, raw = safe_request("GET", DESCRIBE_KEY,
                           path_params={"name": name}, timeout=30)
    pc = ivc = None
    res_present = False
    try:
        env = json.loads(raw) if raw else None
        if isinstance(env, dict) and isinstance(env.get("result"), dict):
            res_present = True
            pc = env["result"].get("points_count")
            ivc = env["result"].get("indexed_vectors_count")
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return st, raw, pc, ivc, res_present


def judge_counter(label, st, raw, pc, ivc, res_present, expected, null_ok, findings):
    """Declare-then-compare for one counter leg. null_ok: leg A tolerates a
    null counter (grid-nullable, nothing committed yet)."""
    print(f"[{label}] status={st} points_count={pc!r} indexed_vectors_count={ivc!r} "
          f"(observed only) raw={str(raw)[:240]}")
    if st != 200:
        findings.append((2, f"Type1_IllegalRejection: {label} - describe of an existing "
                            f"collection returned HTTP {st}; "
                            f"qdrant_behavioral_collections_get_001 requires 200 "
                            f"(with points_count in the body): {str(raw)[:200]!r}"))
        return
    if not res_present:
        findings.append((2, f"Type4_StateLogicViolation: {label} - 200 but result is "
                            f"missing/not an object (grid: result=object)"))
        return
    if pc is None:
        if null_ok:
            print(f"[note] {label}: points_count is null - grid-tolerated on a leg "
                  f"with no committed mutation (D3b-1)")
            return
        findings.append((2, f"Type4_StateLogicViolation: {label} - points_count is "
                            f"null/absent although a wait=true mutation was "
                            f"acknowledged with 200; the describe face fails to "
                            f"reconcile committed state (expected {expected})"))
        return
    if not is_int(pc):
        findings.append((2, f"Type4_StateLogicViolation: {label} - points_count={pc!r} "
                            f"is neither integer nor null (grid: integer|null)"))
        return
    if pc != expected:
        findings.append((2, f"Type4_StateLogicViolation: {label} - points_count={pc} "
                            f"but the collection's committed state is {expected} "
                            f"points (wait=true mutations acknowledged with 200): "
                            f"untruthful counter"))
        return
    print(f"[conform] {label}: points_count == {expected}")


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    col = PFX + "_cnt"   # self-created collection under test
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- setup: create the collection ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": col}, timeout=60)
        print(f"[create {col}] status={st} raw={str(raw)[:200]}")
        if not transport_gate("create", st, raw, findings):
            finish(findings)
            return
        if st not in (200, 201):
            findings.append((3, f"SCRIPT-ERROR-setup: create returned {st}: {str(raw)[:150]}"))
            finish(findings)
            return

        # ---- leg A (baseline): fresh collection -> 0 (null tolerated) ----
        st, raw, pc, ivc, rp = describe_counters(col)
        if not transport_gate("describe leg A", st, raw, findings):
            finish(findings)
            return
        judge_counter("leg A fresh collection", st, raw, pc, ivc, rp, 0, True, findings)

        # ---- mutation 1: upsert 5 points, wait=true (synchronous commit) ----
        pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM, "payload": {"i": i}}
               for i in range(1, N_ADD + 1)]
        st, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                               path_params={"name": col},
                               query_params={"wait": "true"}, timeout=60)
        print(f"[upsert {N_ADD} points wait=true] status={st} raw={str(raw)[:200]}")
        if not transport_gate("upsert leg B", st, raw, findings):
            finish(findings)
            return
        if st != 200:
            findings.append((3, f"SCRIPT-ERROR-setup: upsert returned {st} "
                                f"(leg B premise): {str(raw)[:150]}"))
            finish(findings)
            return

        # ---- leg B: committed state is exactly 5 ----
        st, raw, pc, ivc, rp = describe_counters(col)
        if not transport_gate("describe leg B", st, raw, findings):
            finish(findings)
            return
        judge_counter("leg B after waited upsert of 5", st, raw, pc, ivc, rp,
                      N_ADD, False, findings)

        # ---- mutation 2: delete 2 points, wait=true ----
        st, raw = safe_request("POST", "delete_points",
                               body={"points": list(range(N_ADD - N_DEL + 1, N_ADD + 1))},
                               path_params={"name": col},
                               query_params={"wait": "true"}, timeout=60)
        print(f"[delete {N_DEL} points wait=true] status={st} raw={str(raw)[:200]}")
        if not transport_gate("delete leg C", st, raw, findings):
            finish(findings)
            return
        if st != 200:
            findings.append((3, f"SCRIPT-ERROR-setup: delete returned {st} "
                                f"(leg C premise): {str(raw)[:150]}"))
            finish(findings)
            return

        # ---- leg C: committed state is exactly 3 ----
        st, raw, pc, ivc, rp = describe_counters(col)
        if not transport_gate("describe leg C", st, raw, findings):
            finish(findings)
            return
        judge_counter("leg C after waited delete of 2", st, raw, pc, ivc, rp,
                      N_ADD - N_DEL, False, findings)

        finish(findings)
    finally:
        # destructive-safety: only the self-created, PFX-prefixed name is dropped
        try:
            rt.drop_collection(col)
        except Exception as e:
            print(f"cleanup warning (drop {col}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: describe's points_count tracks the committed state exactly - "
          "0/null on a fresh collection, 5 after a waited upsert of 5, 3 after "
          "a waited delete of 2 (indexed_vectors_count observed only)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
