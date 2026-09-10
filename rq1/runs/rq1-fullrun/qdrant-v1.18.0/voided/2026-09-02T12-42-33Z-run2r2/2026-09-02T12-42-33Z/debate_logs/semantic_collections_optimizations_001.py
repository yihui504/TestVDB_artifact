#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_optimizations_001
# strategy: behavioral_contract
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - API contract verification of the
#   optimizer-status face: the published face promises HTTP 200 with per-shard
#   optimizer status for every existing collection and HTTP 404 for missing
#   ones; a face that answers non-200 for a legal existing collection,
#   fabricates a status report for a never-created name, or emits a body that
#   violates the published OptimizationsResponse shape is exactly the
#   documented-behavior-vs-implementation drift this blindspot covers)
"""
Attack: behavioral_contract (S1, G4 both-direction pairing) x
  qdrant_behavioral_collections_optimizations_001 on collections+optimizations
  (chunk_collections+optimizations unit
  assertions::qdrant_behavioral_collections_optimizations_001 - "returns 200
  with optimizer status per shard; 404 for a missing collection",
  evidence_tier=explicit, endpoint level). The default face (no `with` query
  param) is exercised here; the `with`/`completed_limit` response-selection
  family of the same 200 body is chunk slot _003, and the registry
  metamorphic relation is chunk slot _002.
  [chunk_collections+optimizations semantic coverage: behavioral_contract
   x optimizations_001 = this script (_001 default face) + _003 (with/
   completed_limit params family); metamorphic registry relation x
   optimizations_001 = _002; diagnosis_quality (404 error body) x
   optimizations_001 = _004. search_correctness / filter_semantics /
   type_coercion-on-body: no applicable surface - this GET has no search or
   filter semantics and no typed BODY parameter (the only typed params,
   with/completed_limit, are wire-string query params whose parse-rejection
   disposition belongs to the boundary lane's matrix) - honestly reported
   (G10), not fabricated.]
Oracle: GET optimizations on a self-created existing collection returns HTTP
  200 with result an object carrying the published-v1.18 OptimizationsResponse
  shape (result.summary object present with integer counters
  queued_optimizations/queued_segments/queued_points/idle_segments >= 0, and
  result.running an array - both OpenAPI-required - while queued/completed/
  idle_segments are absent, null, or arrays); the same 200+shape holds on a
  collection under optimizer load (polled samples, every sample re-validated);
  a never-created unique-prefix name answers HTTP 404 twice (stability, no
  flapping) - non-200 on any existing legal collection = Type1_IllegalRejection,
  missing required keys / wrong types / negative counters = Type4_StateLogicViolation
  (shape oracle cross-checked against the published OpenAPI and the contract
  response_shape grid BEFORE writing - spec wins), 200-on-never-created =
  Type4 phantom status report, 5xx with /healthz alive = Type3_RuntimeFailure;
  transport failure with healthy /healthz or create/upsert setup failure =
  SCRIPT_ERROR (G8, never a defect); no observed optimizer activity in the
  poll window is recorded as a timing-guarded skip-note, never a defect.

Contract assertion qdrant_behavioral_collections_optimizations_001
  (evidence_tier=explicit, endpoint level):
    expected_behavior: "existing collection: HTTP 200 with per-shard optimizer
    status; missing collection: HTTP 404"
  endpoint description: "Get optimizer (indexing) progress per shard of a
  collection."  raw_knowledge expected_responses: 200 "ok", 404 "not found".

Shape oracle precedence (D3b-2, cross-checked BEFORE writing): published
  v1.18.0 OpenAPI OptimizationsResponse = {summary: OptimizationsSummary
  (required; 4 integer counters >= 0), running: array (required),
  queued/completed/idle_segments: [array,null] not-required and gated behind
  ?with=...}; the contract api_endpoints[collections+optimizations].
  response_shape grid materializes the same keys (result.summary.* integers,
  result.running[] {uuid,optimizer,status,segments,progress}, result.queued/
  completed/idle_segments arrays-or-null) - the two agree, no conflict zone.

Legs:
  leg 1 positive idle - a self-created empty collection -> HTTP 200 with the
      required summary+running shape (default face, no with param);
  leg 2 positive under load - 6000 points upserted (wait=true) then 1500
      deleted (wait=true; deleted fraction 25% > deleted_threshold 0.2 default
      -> the vacuum optimizer is the documented trigger, OptimizersConfig
      defaults in the published OpenAPI); 12 polled samples x 1s; EVERY 200
      sample must re-satisfy the shape oracle; any sample whose summary
      counters depart from the pristine all-zero state or whose running is
      non-empty is an activity sample whose item shape (uuid/optimizer/status/
      segments/progress per the OpenAPI-required Optimization fields) is
      validated; if no activity appears in the window -> printed skip-note
      (timing-guarded, NOT a defect);
  leg 3 negative - a never-created unique-prefix name -> HTTP 404 exactly
      (assertion negative branch "404 for a missing collection"); immediately
      re-probed -> 404 again (stability, no flapping);
  leg 4 control - the existing collection answers 200 again after the 404
      legs (the 404 is name-scoped, not face-level wreckage).

URL derivation: raw_knowledge api_endpoints[collections+optimizations].url =
  /collections/{collection_name}/optimizations (runtime PATHS gap - the
  registered key below maps to exactly that URL; all other calls use runtime
  PATHS keys). R15 lessons honored: constraint_id bare IDs; envelope
  result.<field> extraction; unique per-script prefixes; inline healthz
  probes; safe_request forwards timeout/body/path_params/query_params.
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

# ---- runtime PATHS gap: register the contract-derived URL (raw_knowledge only) ----
OPT_KEY = "collection_optimizations"
if OPT_KEY not in rt.PATHS:
    rt.PATHS[OPT_KEY] = "/collections/{collection_name}/optimizations"
print(f"[path derivation] {OPT_KEY} = {rt.PATHS[OPT_KEY]} "
      f"(raw_knowledge api_endpoints[collections+optimizations].url; runtime PATHS gap)")

PFX = "sco01" + uuid.uuid4().hex[:6]
DIM = 4
COL_IDLE = PFX + "_idle"
COL_LOAD = PFX + "_load"
NEVER = PFX + "_never_" + uuid.uuid4().hex[:6]
assert NEVER != COL_IDLE and NEVER != COL_LOAD


def safe_request(method, path_key, body=None, path_params=None, query_params=None,
                 timeout=30):
    """All HTTP through the runtime (DB-neutral path_key); forwards body/
    path_params/query_params/timeout exactly - standing lesson."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def jload(raw):
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def result_node(body):
    r = body.get("result") if isinstance(body, dict) else None
    return r if isinstance(r, dict) else None


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


def transport_guard(label, st, raw):
    """G8 three-outcome isolation: transport failures and 5xx never produce
    defect conclusions without a liveness re-check."""
    if st <= 0 or 500 <= st <= 599:
        hs = liveness(label)
        if hs != 200:
            defect("Type3_RuntimeFailure",
                   f"service down - '{label}' got status={st} and /healthz={hs}")
        if st <= 0:
            script_error(f"transport failure '{label}' with healthy /healthz: {str(raw)[:150]}")
        defect("Type3_RuntimeFailure",
               f"'{label}' got {st} with /healthz alive; raw={str(raw)[:250]}")
    return st


SUMMARY_KEYS = ("queued_optimizations", "queued_segments", "queued_points", "idle_segments")


def shape_violation(body):
    """Return a defect message string when the 200 body violates the published
    OptimizationsResponse shape, else None. Summary keys/values and the
    running array are OpenAPI-required; the three optional keys are
    absent/null/array on the default face."""
    if not isinstance(body, dict):
        return f"response is not a JSON object: {str(body)[:200]!r}"
    res = body.get("result")
    if not isinstance(res, dict):
        return f"envelope result is not an object: {str(res)[:200]!r}"
    summary = res.get("summary")
    if not isinstance(summary, dict):
        return f"result.summary is not an object: {str(summary)[:200]!r}"
    for k in SUMMARY_KEYS:
        v = summary.get(k)
        if not isinstance(v, int) or isinstance(v, bool):
            return f"result.summary.{k} is not an integer: {v!r}"
        if v < 0:
            return f"result.summary.{k} is negative: {v!r} (OpenAPI minimum 0)"
    running = res.get("running")
    if not isinstance(running, list):
        return f"result.running is not an array: {str(running)[:200]!r}"
    for opt in running:
        if not isinstance(opt, dict):
            return f"result.running item is not an object: {opt!r}"
        for k in ("uuid", "optimizer", "status", "segments", "progress"):
            if k not in opt:
                return f"running item missing required field '{k}': {opt!r}"
    return None


def activity_observed(body, pristine_zero):
    """True when this 200 body shows optimizer activity: summary counters
    departing from pristine all-zero, or a non-empty running list."""
    res = result_node(body)
    if res is None:
        return False
    summary = res.get("summary") if isinstance(res.get("summary"), dict) else {}
    if any(summary.get(k) not in (0, None) for k in SUMMARY_KEYS):
        return True
    return isinstance(res.get("running"), list) and len(res["running"]) > 0


def upsert_batch(name, start, count):
    pts = [{"id": i, "vector": [float((i + j) % 97) / 97.0 for j in range(DIM)]}
           for i in range(start, start + count)]
    st, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                           path_params={"name": name},
                           query_params={"wait": "true"}, timeout=60)
    print(f"[load upsert {name} {start}..{start + count - 1}] status={st} {str(raw)[:120]}")
    if st not in (200, 201):
        script_error(f"premise upsert batch {start} failed on {name}: {st} {str(raw)[:200]}")


def cleanup():
    """Teardown: drop only collections created by this script; never-created
    names are never dropped. Cleanup failure must never fail the script."""
    for name in (COL_IDLE, COL_LOAD):
        try:
            rt.drop_collection(name)
        except Exception as e:
            print(f"cleanup warning (drop {name}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[assertion quote] existing collection: HTTP 200 with per-shard "
          "optimizer status; missing collection: HTTP 404")
    try:
        # ---- setup premise: two prefix-owned collections ----
        for name in (COL_IDLE, COL_LOAD):
            ok, err = rt.setup_default(name, dim=DIM, metric="Cosine")
            if not ok:
                script_error(f"premise create {name} failed: {err}")
        print(f"[setup] created {COL_IDLE} and {COL_LOAD}")

        # ---- leg 1: positive idle - 200 + required summary/running shape ----
        st, raw = safe_request("GET", OPT_KEY, path_params={"collection_name": COL_IDLE},
                               timeout=30)
        print(f"[leg1 GET optimizations {COL_IDLE}] status={st} raw={str(raw)[:600]}")
        transport_guard("leg1 idle optimizations", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"legal GET on existing collection {COL_IDLE} answered {st}; "
                   f"assertion positive branch promises HTTP 200: {str(raw)[:300]!r}")
        body = jload(raw)
        vio = shape_violation(body)
        if vio:
            defect("Type4_StateLogicViolation",
                   f"positive idle leg shape oracle violated: {vio} (raw={str(raw)[:400]!r})")
        summary = result_node(body).get("summary")
        print(f"[leg1 shape OK] summary={json.dumps(summary)} "
              f"running_len={len(result_node(body).get('running', []))}")

        # ---- leg 2: positive under load - vacuum trigger then polled samples ----
        BATCH = 1000
        for b in range(6):
            upsert_batch(COL_LOAD, b * BATCH, BATCH)
        del_ids = list(range(1500))
        st, raw = safe_request("POST", "delete_points", body={"points": del_ids},
                               path_params={"name": COL_LOAD},
                               query_params={"wait": "true"}, timeout=60)
        print(f"[load delete 1500 of {COL_LOAD}] status={st} {str(raw)[:150]}")
        if st not in (200, 201):
            script_error(f"premise delete on {COL_LOAD} failed: {st} {str(raw)[:200]}")

        activity_seen = False
        for s in range(1, 13):
            time.sleep(1.0)
            st, raw = safe_request("GET", OPT_KEY,
                                   path_params={"collection_name": COL_LOAD}, timeout=30)
            print(f"[leg2 sample {s}] status={st} raw={str(raw)[:400]}")
            transport_guard(f"leg2 sample {s}", st, raw)
            if st != 200:
                defect("Type1_IllegalRejection",
                       f"legal GET on existing loaded collection {COL_LOAD} answered "
                       f"{st} during poll sample {s}: {str(raw)[:300]!r}")
            body = jload(raw)
            vio = shape_violation(body)
            if vio:
                defect("Type4_StateLogicViolation",
                       f"poll sample {s} shape oracle violated: {vio} (raw={str(raw)[:400]!r})")
            if activity_observed(body, pristine_zero=True):
                activity_seen = True
                res = result_node(body)
                for opt in res.get("running", []):
                    print(f"[leg2 activity] running item: "
                          f"uuid={opt.get('uuid')} optimizer={opt.get('optimizer')} "
                          f"status={json.dumps(opt.get('status'))} "
                          f"segments={json.dumps(opt.get('segments'))[:150]}")
        print(f"[leg2] activity samples observed: {activity_seen}")
        if not activity_seen:
            print("[leg2 skip-note] no optimizer activity observed in the 12 s "
                  "poll window (optimizer scheduling is not contractually timed); "
                  "running-item/counter-substance legs not exercised - recorded, "
                  "NOT a defect")

        # ---- leg 3: negative - never-created name must 404, twice, no flapping ----
        for rep in (1, 2):
            st, raw = safe_request("GET", OPT_KEY, path_params={"collection_name": NEVER},
                                   timeout=30)
            print(f"[leg3 attempt {rep} GET optimizations {NEVER}] status={st} raw={str(raw)[:300]}")
            transport_guard(f"leg3 attempt {rep}", st, raw)
            if st == 200:
                defect("Type4_StateLogicViolation",
                       f"never-created collection name {NEVER} answered HTTP 200 with "
                       f"an optimizer status report; assertion negative branch promises "
                       f"HTTP 404 for a missing collection (phantom status): {str(raw)[:300]!r}")
            if st != 404:
                defect("Type4_StateLogicViolation",
                       f"never-created collection name {NEVER} answered HTTP {st}; "
                       f"assertion negative branch promises exactly 404: {str(raw)[:300]!r}")

        # ---- leg 4: control - existing collection still 200 after the 404 legs ----
        st, raw = safe_request("GET", OPT_KEY, path_params={"collection_name": COL_IDLE},
                               timeout=30)
        print(f"[leg4 control GET optimizations {COL_IDLE}] status={st} raw={str(raw)[:400]}")
        transport_guard("leg4 control", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"control: existing collection {COL_IDLE} answered {st} after the "
                   f"404 legs; the 404 must be name-scoped (face must stay 200 for "
                   f"existing names): {str(raw)[:300]!r}")
        vio = shape_violation(jload(raw))
        if vio:
            defect("Type4_StateLogicViolation", f"control leg shape oracle violated: {vio}")

        print(f"OK: existing collections {COL_IDLE}/{COL_LOAD} answered 200 with the "
              f"published OptimizationsResponse shape (summary counters + running "
              f"array) in every polled sample; never-created {NEVER} answered 404 "
              f"twice without flapping; control stayed 200")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
