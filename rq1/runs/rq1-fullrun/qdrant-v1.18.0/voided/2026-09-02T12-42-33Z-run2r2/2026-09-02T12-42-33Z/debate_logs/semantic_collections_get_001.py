#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_get_001
# strategy: behavioral_contract
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift / behavioral-contract verification -
#   the describe face promises a 200 with the FULL resolved config for an
#   existing collection and a 404-with-message (never 200) for a missing one;
#   a face that returns 200 shells out config sections, or answers unknown
#   names with 200, is exactly the documented-behavior-vs-implementation
#   drift this blindspot covers)
"""
Attack: behavioral_contract (S1) x qdrant_behavioral_collections_get_001
  on collections+get (chunk_collections+get unit
  assertions::qdrant_behavioral_collections_get_001; R14 dispatch: "GET
  describe face: existing -> 200 full config; unknown -> 404; only delete
  collections you create; never-created names for 404 legs"). The assertion,
  quoted:
    "existing collection: HTTP 200 with resolved config including defaults;
     missing collection: HTTP 404 with an error message (runtime verified:
     'Not found: Collection ... doesn't exist!'), never 200 with config"
  plus its description: "returns 200 with full config (params, hnsw_config,
  optimizer_config, wal_config, quantization_config), status
  (green|yellow|red), points_count, indexed_vectors_counts".
  Legs (G4 positive/negative pairing on one setup):
    leg A positive   - minimal self-created collection (vectors only, no
                       config overrides) -> 200 whose result carries the
                       FULL config grid: status enum string, config.params/
                       hnsw_config/optimizer_config/wal_config all present
                       as objects with concrete integer defaults (the
                       "resolved defaults" promise), counters and
                       payload_schema per the response_shape grid
    leg B negative   - never-created unique-prefix name -> 404 carrying a
                       non-empty error message; 200-with-config here is the
                       assertion's own defect_type_if_violated
                       (Type1_IllegalSuccess)
    leg C transition - after a 200 drop of leg A's collection, describe must
                       answer 404 (never a stale 200)
  Shape oracle (D3b-1, cross-checked against the endpoint response_shape
  grid BEFORE writing): result=object, result.status=string,
  result.points_count/indexed_vectors_count=integer|null,
  result.segments_count=integer, result.payload_schema=object,
  result.config.params.vectors=object, .shard_number/.replication_factor/
  .write_consistency_factor=integer, hnsw_config.m/.ef_construct/
  .full_scan_threshold=integer, optimizer_config.default_segment_number=
  integer, wal_config.wal_capacity_mb/.wal_segments_ahead=integer.
  quantization_config is grid-typed "any" (its sub-keys are conditional on
  a quantization being configured): absence on a quantization-free
  collection is printed as an observed note, NOT adjudicated (D3b-2:
  spec-derived grid wins over the prose enumeration).
  [chunk_collections+get coverage: behavioral_contract x
   qdrant_behavioral_collections_get_001 (200-full-config grid vs 404
   branches) - this script; config-echo truthfulness = _002; counter
   truthfulness = _003; metamorphic alias equivalence = _004; error-body
   quality = _005; legal-name family = _006]
Oracle: leg A returns 200 with result an object whose status is a string in
  {green,yellow,red} and whose config params/hnsw_config/optimizer_config/
  wal_config sections are objects with grid-typed integer fields (missing
  section, wrong enum, or non-integer where the grid says integer =
  Type4_StateLogicViolation; non-200 on the existing collection =
  Type1_IllegalRejection); legs B/C return 404 with a non-empty error
  message - 200-with-config on a never-created/just-dropped name =
  Type1_IllegalSuccess (assertion's never-200 clause), a non-404 status on
  them = Type4, a 404 with empty/missing error text = Type4 (the
  with-an-error-message clause); 5xx with /healthz alive = Type3; transport
  failure with healthy /healthz = SCRIPT_ERROR; create/drop setup failures
  = SCRIPT_ERROR (G8, never a defect).

Rationale (G4/G7/D3b): expectation declared per leg before measurement.
  The positive leg proves the face can materialize resolved defaults for a
  collection created with none (so a missing section cannot be excused as
  "nothing was configured"), and the negative leg proves the miss branch is
  a 404-with-message rather than a fabricated 200 - the two halves of the
  assertion. Integer checks use is_int() (bool excluded) so true/false
  leaking into numeric fields fails loudly instead of passing via Python's
  bool<int coercion.
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
# (same path modulo template placeholder naming - R13 dispatch lesson)
DESCRIBE_KEY = "describe_collection"
print(f"[path derivation] {DESCRIBE_KEY} = {rt.PATHS[DESCRIBE_KEY]} "
      f"(runtime PATHS; matches raw_knowledge api_endpoints[collections+get].url "
      f"/collections/{{collection_name}})")

PFX = "scg01" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4
ASSERT = ("existing collection: HTTP 200 with resolved config including defaults; "
          "missing collection: HTTP 404 with an error message (runtime verified: "
          "'Not found: Collection ... doesn't exist!'), never 200 with config")


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


def describe_face(name):
    """GET /collections/{name} -> (status, raw, envelope, result_object)."""
    st, raw = safe_request("GET", DESCRIBE_KEY,
                           path_params={"name": name}, timeout=30)
    try:
        env = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        env = None
    res = env.get("result") if isinstance(env, dict) else None
    return st, raw, env, res


def extract_error(env):
    """Pull the error text out of a qdrant error envelope
    ({'status': {'error': ...}} per the runtime-verified 404 body)."""
    if not isinstance(env, dict):
        return None
    st = env.get("status")
    if isinstance(st, dict) and isinstance(st.get("error"), str) and st.get("error"):
        return st["error"]
    for k in ("err", "error", "message", "detail"):
        v = env.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def dig(obj, path):
    """Walk a dotted config path; None when any hop is missing/not a dict."""
    node = obj
    for k in path:
        if isinstance(node, dict) and k in node:
            node = node[k]
        else:
            return None
    return node


def judge_miss_branch(label, name, st, raw, env, findings):
    """Declare-then-compare for a describe miss leg (404-with-message)."""
    err = extract_error(env)
    print(f"[{label}] name={name!r} status={st} error={err!r} raw={str(raw)[:260]}")
    if st == 200:
        findings.append((2, f"Type1_IllegalSuccess: {label} - describe returned HTTP 200 "
                            f"with a config body for collection_name={name!r} that was "
                            f"never created / was just dropped; "
                            f"qdrant_behavioral_collections_get_001 requires 404 "
                            f"(never 200 with config): {str(raw)[:200]!r}"))
        return
    if st != 404:
        findings.append((2, f"Type4_StateLogicViolation: {label} - documented miss answer "
                            f"for collections+get is HTTP 404, got {st} for {name!r}: "
                            f"{str(raw)[:200]!r}"))
        return
    if not err:
        findings.append((2, f"Type4_StateLogicViolation: {label} - HTTP 404 arrived with "
                            f"no error message; the assertion requires '404 with an error "
                            f"message': raw={str(raw)[:200]!r}"))
        return
    print(f"[conform] {label}: 404 with non-empty error message")


def judge_full_config(label, name, st, raw, env, res, findings):
    """Leg A: 200 + full resolved-config grid (D3b-1 field list)."""
    print(f"[{label}] name={name!r} status={st} raw={str(raw)[:400]}")
    if st != 200:
        findings.append((2, f"Type1_IllegalRejection: {label} - describe of an existing "
                            f"(self-created) collection returned HTTP {st} for {name!r}; "
                            f"qdrant_behavioral_collections_get_001 requires 200 with the "
                            f"full config: {str(raw)[:200]!r}"))
        return
    if not isinstance(res, dict):
        findings.append((2, f"Type4_StateLogicViolation: {label} - 200 but result is not "
                            f"an object (grid: result=object): {type(res).__name__}"))
        return
    rst = res.get("status")
    if not isinstance(rst, str) or rst not in ("green", "yellow", "red"):
        findings.append((2, f"Type4_StateLogicViolation: {label} - result.status={rst!r} "
                            f"is not a string in the documented enum "
                            f"green|yellow|red"))
    cfg = res.get("config")
    if not isinstance(cfg, dict):
        findings.append((2, f"Type4_StateLogicViolation: {label} - 200 but result.config "
                            f"is missing/not an object (assertion: 'full config ... "
                            f"including defaults')"))
        return
    # section presence + concrete typed defaults (collection created with NONE of
    # these set -> the resolved-defaults promise means each must be materialized)
    section_ints = [
        ("config.params", ("params",), [("vectors", "object"),
                                         ("shard_number", "int"),
                                         ("replication_factor", "int"),
                                         ("write_consistency_factor", "int")]),
        ("config.hnsw_config", ("hnsw_config",), [("m", "int"),
                                                  ("ef_construct", "int"),
                                                  ("full_scan_threshold", "int")]),
        ("config.optimizer_config", ("optimizer_config",),
         [("default_segment_number", "int"),
          ("deleted_threshold", "number")]),
        ("config.wal_config", ("wal_config",), [("wal_capacity_mb", "int"),
                                                ("wal_segments_ahead", "int")]),
    ]
    for sec_label, sec_path, fields in section_ints:
        sec = dig(res, ("config",) + sec_path)
        if not isinstance(sec, dict):
            findings.append((2, f"Type4_StateLogicViolation: {label} - resolved config "
                                f"section {sec_label} missing/not an object "
                                f"(assertion: '200 with resolved config including "
                                f"defaults'); got {sec!r}"))
            continue
        for fname, ftype in fields:
            v = sec.get(fname)
            ok = (is_int(v) if ftype == "int"
                  else (isinstance(v, (int, float)) and not isinstance(v, bool))
                  if ftype == "number"
                  else isinstance(v, dict))
            if not ok or v is None:
                findings.append((2, f"Type4_StateLogicViolation: {label} - "
                                    f"{sec_label}.{fname}={v!r} violates the "
                                    f"response-shape grid (expected {ftype}); the "
                                    f"resolved-defaults promise is broken for a field "
                                    f"the create request left unset"))
    # scalar/grid counters (points_count & indexed_vectors_count are grid-nullable)
    pc, ivc = res.get("points_count"), res.get("indexed_vectors_count")
    if not (pc is None or is_int(pc)):
        findings.append((2, f"Type4_StateLogicViolation: {label} - result.points_count="
                            f"{pc!r} is neither integer nor null (grid)"))
    if not (ivc is None or is_int(ivc)):
        findings.append((2, f"Type4_StateLogicViolation: {label} - "
                            f"result.indexed_vectors_count={ivc!r} is neither integer "
                            f"nor null (grid)"))
    if not is_int(res.get("segments_count")):
        findings.append((2, f"Type4_StateLogicViolation: {label} - result.segments_count="
                            f"{res.get('segments_count')!r} is not an integer (grid)"))
    if not isinstance(res.get("payload_schema"), dict):
        findings.append((2, f"Type4_StateLogicViolation: {label} - result.payload_schema="
                            f"{res.get('payload_schema')!r} is not an object (grid)"))
    qc = dig(res, ("config", "quantization_config"))
    print(f"[observed note] {label}: config.quantization_config={qc!r} "
          f"(grid type any - absence on a quantization-free collection is not "
          f"adjudicated, D3b-2)")
    print(f"[observed note] {label}: points_count={pc!r} indexed_vectors_count={ivc!r} "
          f"segments_count={res.get('segments_count')!r}")
    if not any(r == 2 for r, _ in findings):
        print(f"[conform] {label}: 200 with full resolved-config grid")


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[assertion quote] {ASSERT}")
    findings = []
    live = PFX + "_live"        # created by this script (positive leg)
    never = PFX + "_never"      # never created (negative leg; unique prefix)
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- setup: create the minimal positive-leg collection ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": live}, timeout=60)
        print(f"[create {live}] status={st} raw={str(raw)[:200]}")
        if not transport_gate("create live", st, raw, findings):
            finish(findings)
            return
        if st not in (200, 201):
            findings.append((3, f"SCRIPT-ERROR-setup: create returned {st}: {str(raw)[:150]}"))
            finish(findings)
            return

        # ---- leg A (positive): existing -> 200 with full config grid ----
        st, raw, env, res = describe_face(live)
        if not transport_gate(f"describe {live}", st, raw, findings):
            finish(findings)
            return
        judge_full_config("leg A existing collection", live, st, raw, env, res, findings)

        # ---- leg B (negative): never-created name -> 404 with message ----
        st, raw, env, _res = describe_face(never)
        if not transport_gate(f"describe {never}", st, raw, findings):
            finish(findings)
            return
        judge_miss_branch("leg B never-created", never, st, raw, env, findings)

        # ---- leg C (transition): after a 200 drop, describe answers 404 ----
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": live}, timeout=120)
        print(f"[drop {live}] status={st} raw={str(raw)[:200]}")
        if not transport_gate("drop live", st, raw, findings):
            finish(findings)
            return
        if st != 200:
            findings.append((3, f"SCRIPT-ERROR-setup: drop returned {st} "
                                f"(transition premise): {str(raw)[:150]}"))
            finish(findings)
            return
        st, raw, env, _res = describe_face(live)
        if not transport_gate(f"describe {live} post-drop", st, raw, findings):
            finish(findings)
            return
        judge_miss_branch("leg C post-drop", live, st, raw, env, findings)

        finish(findings)
    finally:
        # destructive-safety: only self-created, PFX-prefixed names are dropped
        try:
            rt.drop_collection(live)
        except Exception as e:
            print(f"cleanup warning (drop {live}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: describe answers 200 with the full resolved-config grid for an "
          "existing collection, and 404 with a non-empty error message for "
          "never-created and just-dropped names (never 200 with config)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
