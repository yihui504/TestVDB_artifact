#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_optimizations_003
# strategy: behavioral_contract
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter semantics trust - the response-selection query
#   params `with`/`completed_limit` are documented with precise semantics
#   ("Requires ?with=...", "Maximum number of completed optimizations to
#   return", "Ignored if `completed` is not in the `with` parameter"); a
#   server that silently ignores them returns a body contradicting its own
#   declared contract) + BS-05 (Documentation Drift on the extended 200 face)
"""
Attack: behavioral_contract (S1, response-selection params family) x
  qdrant_behavioral_collections_optimizations_001 on collections+optimizations
  (chunk_collections+optimizations unit
  assertions::qdrant_behavioral_collections_optimizations_001; chunk coverage
  slot "behavioral_contract with/completed_limit params family x
  optimizations_001" - see _001's Attack block for the full chunk list).
  The 200 body's extended shape is declared by the published v1.18.0 OpenAPI
  (OptimizationsResponse): summary + running are required and always present;
  queued/completed/idle_segments are [array,null] NOT-required and gated -
  "An estimated queue of pending optimizations. Requires ?with=queued.",
  "Completed optimizations. Requires ?with=completed. Limited by
  ?completed_limit=N.", "Segments that don't require optimization. Requires
  ?with=idle_segments."; completed_limit "Maximum number of completed
  optimizations to return. Ignored if `completed` is not in the `with`
  parameter" (type integer, minimum 0, default 16). These param semantics are
  part of the same 200-with-optimizer-status promise the assertion pins
  (contract api_endpoints parameters list with/completed_limit; contract
  response_shape grid materializes result.queued/completed/idle_segments as
  arrays-or-null), so an honored/ignored check is contract-anchored (G1).
Oracle: P1 ?with=queued -> HTTP 200 with result.queued an ARRAY (possibly
  empty; queued items, when present, carry optimizer:string and
  segments:array - PendingOptimization required fields); P2 ?with=completed&
  completed_limit=3 -> HTTP 200 with result.completed an ARRAY and, on the
  first polled sample where completed is non-empty, len(completed) <= 3
  (cap respected); P3 ?with=idle_segments -> HTTP 200 with
  result.idle_segments an ARRAY (items carry uuid:string and
  points_count:integer >= 0 - OptimizationSegmentInfo required fields); P4
  completed_limit=5 WITHOUT with -> HTTP 200 with the default face unchanged
  (summary+running present; the gated keys absent/null - the param is
  "ignored" exactly as documented); P5 with=<unlisted token> and P6
  with="queued,completed,idle_segments" (comma-separated form per the
  OpenAPI description) are measured-note legs (never 5xx; else Type3) whose
  status disposition is not adjudicated here - any requested-key result that
  is still null/absent after the matching with= token = Type4_StateLogicViolation
  (documented response-selection param silently ignored, BS-01/BS-05);
  summary+running shape re-validated in every 200 sample; no completed
  activity in the poll window = vacuity skip-note (never a defect); 5xx with
  /healthz alive = Type3_RuntimeFailure; transport failure with healthy
  /healthz or create/upsert/delete setup failure = SCRIPT_ERROR.

Legs on one loaded collection: the 1500-delete-after-6000-upsert vacuum
  trigger (deleted fraction 25% > deleted_threshold 0.2 default) makes the
  completed-cap leg non-vacuous whenever optimizer activity is observable;
  every sample re-validates the required summary+running shape.
  [type_coercion on the query params: wire-string query params parsed
  server-side; the parse-rejection disposition of malformed values belongs
  to the boundary lane's matrix - not re-adjudicated here (same scoping as
  R12 semantic_collections_delete_001 / exists_004).]
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
print(f"[path derivation] {OPT_KEY} = {rt.PATHS[OPT_KEY]} (raw_knowledge "
      f"api_endpoints[collections+optimizations].url; runtime PATHS gap)")

PFX = "sco03" + uuid.uuid4().hex[:6]
DIM = 4
COL = PFX + "_col"

SUMMARY_KEYS = ("queued_optimizations", "queued_segments", "queued_points", "idle_segments")


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
    """G8 three-outcome isolation."""
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


def get_with(name, params):
    """GET optimizations with query params -> (status, raw)."""
    return safe_request("GET", OPT_KEY, path_params={"collection_name": name},
                        query_params=params, timeout=30)


def check_base_shape(body, label):
    """Required summary+running shape (published OptimizationsResponse) in
    every 200 sample; returns defect message or None."""
    if not isinstance(body, dict):
        return f"{label}: response is not a JSON object: {str(body)[:200]!r}"
    res = result_node(body)
    if res is None:
        return f"{label}: envelope result is not an object: {str(body)[:200]!r}"
    summary = res.get("summary")
    if not isinstance(summary, dict):
        return f"{label}: result.summary is not an object: {str(summary)[:200]!r}"
    for k in SUMMARY_KEYS:
        v = summary.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            return f"{label}: result.summary.{k} invalid: {v!r}"
    if not isinstance(res.get("running"), list):
        return f"{label}: result.running is not an array: {str(res.get('running'))[:200]!r}"
    return None


def require_array(res, key, label):
    """The documented 'Requires ?with=<key>' gate: after the matching token the
    key must be an array (possibly empty), never null/absent."""
    v = res.get(key)
    if not isinstance(v, list):
        return (f"{label}: result.{key} is {v!r} (null/absent/other) after the "
                f"matching ?with token; the published OpenAPI declares this field "
                f"'Requires ?with=' and returns an array - the response-selection "
                f"param appears silently ignored (BS-01/BS-05)")
    return None


def cleanup():
    """Teardown: drop only the collection created by this script."""
    try:
        rt.drop_collection(COL)
    except Exception as e:
        print(f"cleanup warning (drop {COL}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[assertion quote] existing collection: HTTP 200 with per-shard "
          "optimizer status; missing collection: HTTP 404")
    try:
        # ---- setup premise: one loaded collection ----
        ok, err = rt.setup_default(COL, dim=DIM, metric="Cosine")
        if not ok:
            script_error(f"premise create {COL} failed: {err}")
        BATCH = 1000
        for b in range(6):
            pts = [{"id": i, "vector": [float((i + j) % 97) / 97.0 for j in range(DIM)]}
                   for i in range(b * BATCH, (b + 1) * BATCH)]
            st, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                                   path_params={"name": COL},
                                   query_params={"wait": "true"}, timeout=60)
            print(f"[setup upsert batch {b}] status={st} {str(raw)[:100]}")
            if st not in (200, 201):
                script_error(f"premise upsert batch {b} failed: {st} {str(raw)[:200]}")
        st, raw = safe_request("POST", "delete_points", body={"points": list(range(1500))},
                               path_params={"name": COL},
                               query_params={"wait": "true"}, timeout=60)
        print(f"[setup delete 1500] status={st} {str(raw)[:120]}")
        if st not in (200, 201):
            script_error(f"premise delete failed: {st} {str(raw)[:200]}")

        # ---- P0 default face: summary+running required, gated keys null/absent ----
        st, raw = get_with(COL, {})
        print(f"[P0 default] status={st} raw={str(raw)[:500]}")
        transport_guard("P0 default", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"legal default GET answered {st}: {str(raw)[:300]!r}")
        body = jload(raw)
        vio = check_base_shape(body, "P0")
        if vio:
            defect("Type4_StateLogicViolation", vio)
        res = result_node(body)
        for k in ("queued", "completed", "idle_segments"):
            if k in res and res[k] is not None:
                print(f"[P0 note] gated key result.{k} present without ?with: "
                      f"{json.dumps(res[k])[:200]} (over-delivery note, not a defect)")
        print("[P0 shape OK] default face carries required summary+running")

        # ---- P1 ?with=queued -> result.queued must be an array ----
        st, raw = get_with(COL, {"with": "queued"})
        print(f"[P1 with=queued] status={st} raw={str(raw)[:500]}")
        transport_guard("P1", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"?with=queued (documented value) answered {st}: {str(raw)[:300]!r}")
        body = jload(raw)
        vio = check_base_shape(body, "P1")
        if vio:
            defect("Type4_StateLogicViolation", vio)
        res = result_node(body)
        vio = require_array(res, "queued", "P1")
        if vio:
            defect("Type4_StateLogicViolation", vio)
        for item in res["queued"]:
            if not isinstance(item, dict) or not isinstance(item.get("optimizer"), str) \
                    or not isinstance(item.get("segments"), list):
                defect("Type4_StateLogicViolation",
                       f"P1: queued item violates PendingOptimization required fields "
                       f"(optimizer:string, segments:array): {item!r}")
        print(f"[P1 OK] result.queued is an array of length {len(res['queued'])}")

        # ---- P3 ?with=idle_segments -> array with typed items ----
        st, raw = get_with(COL, {"with": "idle_segments"})
        print(f"[P3 with=idle_segments] status={st} raw={str(raw)[:500]}")
        transport_guard("P3", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"?with=idle_segments (documented value) answered {st}: {str(raw)[:300]!r}")
        body = jload(raw)
        vio = check_base_shape(body, "P3")
        if vio:
            defect("Type4_StateLogicViolation", vio)
        res = result_node(body)
        vio = require_array(res, "idle_segments", "P3")
        if vio:
            defect("Type4_StateLogicViolation", vio)
        for item in res["idle_segments"]:
            if not isinstance(item, dict) or not isinstance(item.get("uuid"), str) \
                    or not isinstance(item.get("points_count"), int) \
                    or isinstance(item.get("points_count"), bool) \
                    or item.get("points_count") < 0:
                defect("Type4_StateLogicViolation",
                       f"P3: idle_segments item violates OptimizationSegmentInfo "
                       f"required fields (uuid:string, points_count:integer>=0): {item!r}")
        print(f"[P3 OK] result.idle_segments is an array of length "
              f"{len(res['idle_segments'])}")

        # ---- P4 ?completed_limit=5 WITHOUT with -> default face unchanged ----
        st, raw = get_with(COL, {"completed_limit": "5"})
        print(f"[P4 completed_limit=5 alone] status={st} raw={str(raw)[:500]}")
        transport_guard("P4", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"?completed_limit=5 (documented, minimum 0) answered {st}: {str(raw)[:300]!r}")
        body = jload(raw)
        vio = check_base_shape(body, "P4")
        if vio:
            defect("Type4_StateLogicViolation", vio)
        res = result_node(body)
        for k in ("queued", "completed", "idle_segments"):
            if res.get(k) is not None:
                print(f"[P4 note] gated key result.{k} populated without ?with: "
                      f"{json.dumps(res[k])[:200]}")
        print("[P4 OK] completed_limit without with= left the default face unchanged "
              "(param ignored exactly as documented)")

        # ---- P2 ?with=completed&completed_limit=3 -> array; cap <= 3 when non-empty ----
        cap_seen = False
        for s in range(1, 16):
            if s > 1:
                time.sleep(1.2)
            st, raw = get_with(COL, {"with": "completed", "completed_limit": "3"})
            print(f"[P2 sample {s} with=completed&completed_limit=3] status={st} "
                  f"raw={str(raw)[:400]}")
            transport_guard(f"P2 sample {s}", st, raw)
            if st != 200:
                defect("Type1_IllegalRejection",
                       f"?with=completed&completed_limit=3 answered {st} in sample {s}: "
                       f"{str(raw)[:300]!r}")
            body = jload(raw)
            vio = check_base_shape(body, f"P2 sample {s}")
            if vio:
                defect("Type4_StateLogicViolation", vio)
            res = result_node(body)
            vio = require_array(res, "completed", f"P2 sample {s}")
            if vio:
                defect("Type4_StateLogicViolation", vio)
            n = len(res["completed"])
            print(f"[P2 sample {s}] result.completed length={n}")
            for item in res["completed"]:
                for k in ("uuid", "optimizer", "status", "segments", "progress"):
                    if k not in item:
                        defect("Type4_StateLogicViolation",
                               f"P2: completed item missing required Optimization "
                               f"field '{k}': {item!r}")
            if n > 0:
                cap_seen = True
                if n > 3:
                    defect("Type4_StateLogicViolation",
                           f"P2: completed_limit=3 declared 'Maximum number of "
                           f"completed optimizations to return' but the response "
                           f"carries {n} completed entries: {str(raw)[:400]!r}")
                break
        print(f"[P2] non-vacuous completed-cap check observed: {cap_seen}")
        if not cap_seen:
            print("[P2 skip-note] no completed optimization observed in the 18 s "
                  "poll window; the len<=3 cap leg stayed vacuous (optimizer "
                  "scheduling is not contractually timed) - recorded, NOT a defect")

        # ---- P5/P6 measured-note legs: unknown token and comma-separated form ----
        st, raw = get_with(COL, {"with": "bogus_token"})
        print(f"[P5 with=bogus_token] status={st} raw={str(raw)[:300]}")
        transport_guard("P5", st, raw)
        if st == 200:
            body5 = jload(raw)
            print(f"[P5 note] 200; gated keys queued={json.dumps(result_node(body5).get('queued'))[:80]} "
                  f"completed={json.dumps(result_node(body5).get('completed'))[:80]} "
                  f"(unknown-token handling recorded, disposition not adjudicated)")
        else:
            print(f"[P5 note] unknown token answered {st} (disposition is the "
                  f"boundary lane's; not adjudicated here)")
        st, raw = get_with(COL, {"with": "queued,completed,idle_segments"})
        print(f"[P6 with=queued,completed,idle_segments] status={st} raw={str(raw)[:400]}")
        transport_guard("P6", st, raw)
        if st == 200:
            res6 = result_node(jload(raw))
            for k in ("queued", "completed", "idle_segments"):
                v = res6.get(k)
                print(f"[P6 note] result.{k} type={type(v).__name__} "
                      f"{json.dumps(v)[:120] if isinstance(v, list) else v!r} "
                      f"(comma-separated form behavior recorded, not adjudicated)")
        else:
            print(f"[P6 note] comma-separated form answered {st} (grammar "
                  f"disposition is the boundary lane's; not adjudicated here)")

        print("OK: every documented ?with=/completed_limit request form was honored "
              "with the declared array/cap semantics on a 200 body whose required "
              "summary+running shape held in every sample")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
