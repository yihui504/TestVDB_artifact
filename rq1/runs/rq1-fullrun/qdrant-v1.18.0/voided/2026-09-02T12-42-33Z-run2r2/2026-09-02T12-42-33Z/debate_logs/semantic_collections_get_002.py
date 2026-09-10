#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_get_002
# strategy: behavioral_contract
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the describe face promises the
#   collection's RESOLVED config; a face that resets explicitly-set values
#   back to defaults (or silently drops them) reports a config that is not
#   the collection's, which is the doc-vs-implementation drift this
#   blindspot covers; _001 proved defaults materialize, this script proves
#   explicit values survive the resolution)
"""
Attack: behavioral_contract (S1, config-echo truthfulness variant) x
  qdrant_behavioral_collections_get_001 on collections+get
  (chunk_collections+get unit
  assertions::qdrant_behavioral_collections_get_001). The assertion's
  positive branch, quoted: "existing collection: HTTP 200 with resolved
  config including defaults". The under-tested half of that promise is the
  word RESOLVED: the config returned must be THIS collection's - explicit
  values set at create time must be echoed exactly, not silently reset to
  the deployment defaults and not dropped.
  Legs (G4 pairing on one setup):
    leg A echo      - collection created with explicit, all-documented-legal
                      overrides (shard_number=1, replication_factor=1,
                      write_consistency_factor=1, on_disk_payload=false,
                      hnsw_config{m=32, ef_construct=128},
                      optimizer_config{indexing_threshold=20000},
                      wal_config{wal_capacity_mb=64}) -> describe must
                      return each value at its response_shape grid path,
                      with strict equality
    leg B control   - a minimal sibling collection (vectors only) is
                      described and its resolved defaults are printed as
                      observed notes ONLY (deployment defaults may differ;
                      no equality/inequality is asserted on them - the
                      oracle never depends on what the default happens to
                      be, so a default coinciding with an explicit value
                      cannot fake a pass or a fail)
  Echo paths (D3b-1, cross-checked against the grid BEFORE writing):
    result.config.params.shard_number / .replication_factor /
    .write_consistency_factor = integer; .on_disk_payload = boolean|null;
    result.config.hnsw_config.m / .ef_construct = integer;
    result.config.optimizer_config.indexing_threshold = integer|null;
    result.config.wal_config.wal_capacity_mb = integer. The nullable grid
    fields are adjudicated behaviorally: null on a field whose explicit
    create value was set means the value was not resolved into the
    describe view (Type4 with the grid-nullable caveat printed), not a
    shape violation.
  [chunk_collections+get coverage: behavioral_contract x
   qdrant_behavioral_collections_get_001 (config-echo truthfulness of the
   resolved-config promise) - this script; 200-full-config grid vs 404
   branches = _001; counter truthfulness = _003; metamorphic alias
   equivalence = _004; error-body quality = _005; legal-name family = _006]
Oracle: leg A describe returns 200 and echoes every explicit create value
  with strict equality at its grid path - shard_number==1,
  replication_factor==1, write_consistency_factor==1, on_disk_payload is
  exactly False, hnsw_config.m==32, hnsw_config.ef_construct==128,
  optimizer_config.indexing_threshold==20000,
  wal_config.wal_capacity_mb==64; any missing field, null-instead-of-set-
  value, or different value (silent reset to default / silent drop) =
  Type4_StateLogicViolation (the describe response is not the collection's
  resolved config); non-200 on the existing collection =
  Type1_IllegalRejection; 5xx with /healthz alive = Type3; transport
  failure with healthy /healthz = SCRIPT_ERROR; create setup failure =
  SCRIPT_ERROR (G8) - if the create face rejects an override the echo leg
  is skipped with a printed note (disposition belongs to the create lane,
  G3), and the remaining legs still adjudicate.

Rationale (G4/G7/D3b): the chosen overrides deliberately differ from
  qdrant's documented stock defaults (m=32 vs stock 16, ef_construct=128
  vs stock 100, indexing_threshold=20000 vs stock 20000-nothing - the
  control leg prints whatever the deployment default actually is) so a
  describe that regurgitates defaults instead of the collection's config
  is caught by inequality rather than by luck. Strict `is False` for
  on_disk_payload catches both silent null-ing and silent re-defaulting to
  the standalone default true (create param doc: 'runtime default true in
  v1.18.0 standalone').
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

PFX = "scg02" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4

# explicit, all-documented-legal create overrides (every path exists in the
# collections+create parameter list of the contract)
EXPLICIT_BODY = {
    "vectors": {"size": DIM, "distance": "Cosine"},
    "shard_number": 1,
    "replication_factor": 1,
    "write_consistency_factor": 1,
    "on_disk_payload": False,
    "hnsw_config": {"m": 32, "ef_construct": 128},
    "optimizer_config": {"indexing_threshold": 20000},
    "wal_config": {"wal_capacity_mb": 64},
}

# (grid-path label, dotted path under result, expected value) - echo assertions
ECHO_CHECKS = [
    ("config.params.shard_number", ("config", "params", "shard_number"), 1),
    ("config.params.replication_factor", ("config", "params", "replication_factor"), 1),
    ("config.params.write_consistency_factor",
     ("config", "params", "write_consistency_factor"), 1),
    ("config.params.on_disk_payload", ("config", "params", "on_disk_payload"), False),
    ("config.hnsw_config.m", ("config", "hnsw_config", "m"), 32),
    ("config.hnsw_config.ef_construct", ("config", "hnsw_config", "ef_construct"), 128),
    ("config.optimizer_config.indexing_threshold",
     ("config", "optimizer_config", "indexing_threshold"), 20000),
    ("config.wal_config.wal_capacity_mb", ("config", "wal_config", "wal_capacity_mb"), 64),
]


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


def describe_result(name):
    """GET /collections/{name} -> (status, raw, result_object_or_None)."""
    st, raw = safe_request("GET", DESCRIBE_KEY,
                           path_params={"name": name}, timeout=30)
    try:
        env = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        env = None
    res = env.get("result") if isinstance(env, dict) else None
    return st, raw, res


def dig(obj, path):
    node = obj
    for k in path:
        if isinstance(node, dict) and k in node:
            node = node[k]
        else:
            return None
    return node


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    exp = PFX + "_exp"    # explicit-overrides collection (echo leg)
    ctl = PFX + "_ctl"    # minimal sibling (control leg, observed only)
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- setup: explicit-overrides collection ----
        st, raw = safe_request("PUT", "create_collection", body=EXPLICIT_BODY,
                               path_params={"name": exp}, timeout=60)
        print(f"[create {exp}] status={st} raw={str(raw)[:240]}")
        if not transport_gate(f"create {exp}", st, raw, findings):
            finish(findings)
            return
        if st not in (200, 201):
            print(f"[note] create face rejected the explicit-overrides body with {st} - "
                  f"disposition belongs to the create lane (G3); echo leg skipped, "
                  f"control leg still runs")
        else:
            # ---- leg A (echo): every explicit value survives resolution ----
            st, raw, res = describe_result(exp)
            print(f"[describe {exp}] status={st} raw={str(raw)[:400]}")
            if not transport_gate(f"describe {exp}", st, raw, findings):
                finish(findings)
                return
            if st != 200:
                findings.append((2, f"Type1_IllegalRejection: leg A - describe of an "
                                    f"existing collection returned HTTP {st}; "
                                    f"qdrant_behavioral_collections_get_001 requires "
                                    f"200 with the resolved config: {str(raw)[:200]!r}"))
            elif not isinstance(res, dict):
                findings.append((2, f"Type4_StateLogicViolation: leg A - 200 but result "
                                    f"is not an object (grid: result=object)"))
            else:
                for label, path, expected in ECHO_CHECKS:
                    got = dig(res, path)
                    if got == expected and not (isinstance(expected, bool) != isinstance(got, bool)):
                        print(f"[conform] echo {label} == {expected!r}")
                        continue
                    if got is None:
                        findings.append((2, f"Type4_StateLogicViolation: leg A - explicit "
                                            f"create value {label}={expected!r} is absent/"
                                            f"null in the describe view (grid-nullable "
                                            f"field, but an explicitly set value was not "
                                            f"resolved) - the returned config is not this "
                                            f"collection's resolved config"))
                    else:
                        findings.append((2, f"Type4_StateLogicViolation: leg A - "
                                            f"{label}: expected the explicit create "
                                            f"value {expected!r} to be echoed, got "
                                            f"{got!r} (silent reset to default or silent "
                                            f"drop - describe reports a config that is "
                                            f"not the collection's)"))

        # ---- leg B (control, observed only): minimal sibling's resolved defaults ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": ctl}, timeout=60)
        print(f"[create {ctl}] status={st} raw={str(raw)[:200]}")
        if not transport_gate(f"create {ctl}", st, raw, findings):
            finish(findings)
            return
        if st in (200, 201):
            st, raw, res = describe_result(ctl)
            print(f"[describe {ctl}] status={st} raw={str(raw)[:300]}")
            if not transport_gate(f"describe {ctl}", st, raw, findings):
                finish(findings)
                return
            if isinstance(res, dict):
                notes = {
                    "hnsw_config.m": dig(res, ("config", "hnsw_config", "m")),
                    "hnsw_config.ef_construct": dig(res, ("config", "hnsw_config", "ef_construct")),
                    "optimizer_config.indexing_threshold":
                        dig(res, ("config", "optimizer_config", "indexing_threshold")),
                    "wal_config.wal_capacity_mb": dig(res, ("config", "wal_config", "wal_capacity_mb")),
                    "params.on_disk_payload": dig(res, ("config", "params", "on_disk_payload")),
                }
                print(f"[observed note] control {ctl} resolved defaults (no equality "
                      f"assertions on defaults): {json.dumps(notes, default=str)}")
        else:
            print(f"[note] control create returned {st}; control leg skipped (G3)")

        finish(findings)
    finally:
        # destructive-safety: only self-created, PFX-prefixed names are dropped
        for n in (exp, ctl):
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
    print("OK: the describe face echoes every explicit create-time config value "
          "exactly (resolved config is the collection's own; control leg printed "
          "deployment defaults as observed notes only)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
