#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_024
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_resource_shard_number_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-07 (resource exhaustion - spec-legal-but-extreme values in a
#   uint32 domain with no documented max; the R10 wal_retain_closed=0 panic
#   showed this endpoint's unwrap-on-allocated-resource family)
"""
Attack: resource_bound both-direction coverage (G-new-class, empty
  binding -> general principles) x qdrant_resource_shard_number_001
  (chunk_collections+create-2of2; PUT /collections/{name} via runtime
  path_key create_collection). The constraint (resource_bound, level=
  system, inferred): shard_number is documented minimum 1 with NO upper
  bound (uint32 domain); any spec-legal shard_number (>=1) must be
  completed, rejected with an error, or fail with a documented service
  error - crashing, panicking or service death is not allowed.
  Positive direction (promise exercised): shard_number=1 and 8 create
  fine and describe echoes result.config.params.shard_number
  (response_shape: integer) - proves the echo oracle works before the
  extremes are trusted. Resource-extreme direction (promise challenged,
  spec-legal values): shard_number=4294967295 (uint32 max) and
  shard_number=1000 (1000x the default) on fresh names with generous
  client timeouts. Acceptance matrix per extreme leg: (a) 200 completed
  (+ echo, then cleanup); (b) 4xx rejected; (c) 5xx WITH a descriptive
  error body = documented service error - all NO_DEFECT outcomes; the
  forbidden outcomes: 5xx with panic/unwrap markers (crash-flavored,
  the R10 wal panic family) = Type3; transport timeout with /healthz
  dead = Type3 service death; transport timeout with /healthz alive but
  NO resolution (neither created nor rejected) within the stated
  observation window = Type3 (unbounded operation, not handled
  gracefully). Post-condition: /healthz 200 AND a fresh plain create
  succeeds - a degraded or dead service after the legs = Type3.
  Boundary round covered the ILLEGAL values (0, -1); the spec-legal
  extremes here are the untested direction.
  [chunk_collections+create-2of2 coverage: resource_bound both-direction
   x qdrant_resource_shard_number_001 (legal 1/8 positive + uint32-max
   and 1000x extremes + service-alive post-condition)]
Oracle: shard_number=1 and 8 creates return 200 and describe echoes
  result.config.params.shard_number == the set value (mismatch echo on a
  positive leg = Type4_StateLogicViolation); each extreme leg resolves
  as 200-completed / 4xx-rejected / descriptive-5xx while /healthz stays
  200 and a fresh create still succeeds - panic-marker 5xx, /healthz
  death, or an unresolved request beyond its observation window
  (extreme-A: 35s client + 16s poll; extreme-B: 75s client + 16s poll)
  = DEFECT_FOUND (Type3_RuntimeFailure); a degraded post-condition =
  Type3 - constraint qdrant_resource_shard_number_001.

Rationale (G4/G5/G8/D3b-3): the destructive power of the mutation is the
  allocation family this endpoint already panicked on (R10: NonZeroUsize
  unwrap on a legal minimum); uint32-max probes the same unwrap path at
  the top of the domain while 1000x-default probes sustained resource
  pressure. Every transport-timeout branch re-checks /healthz before any
  Type3 conclusion, and the observation windows are stated up front so
  the hang judgment is falsifiable rather than open-ended.
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

PREFIX = "scc024_"
RUN = str(int(time.time()))
CREATED = []

PANIC_MARKERS = ["panic", "unwrap", "assertion failed", "stack overflow",
                 "called `option::unwrap`", "called `result::unwrap`"]


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


def create_sharded(name, shard_number, client_timeout):
    body = {"vectors": {"size": 4, "distance": "Cosine"},
            "shard_number": shard_number}
    t0 = time.time()
    st, raw = safe_request("PUT", "create_collection", body,
                           path_params={"name": name}, timeout=client_timeout)
    dt = time.time() - t0
    print(f"[create {name} shard_number={shard_number}] status={st} "
          f"elapsed={dt:.1f}s raw={str(raw)[:300]}")
    return st, raw, dt


def describe_shards(name):
    st, raw = safe_request("GET", "describe_collection",
                           path_params={"name": name}, timeout=20)
    print(f"[describe {name}] status={st} raw={str(raw)[:250]}")
    if st != 200:
        return st, None
    res = jload(raw).get("result")
    params = ((res or {}).get("config") or {}).get("params") if isinstance(res, dict) else None
    sh = params.get("shard_number") if isinstance(params, dict) else None
    return st, sh


def drop_hard(name):
    """Cleanup for possibly-heavy collections; failure is non-fatal."""
    try:
        st, raw = safe_request("DELETE", "drop_collection", None,
                               path_params={"name": name}, timeout=60)
        print(f"[drop {name}] status={st} raw={str(raw)[:150]}")
        if st not in (200, 201):
            st, raw = safe_request("DELETE", "drop_collection", None,
                                   path_params={"name": name},
                                   query_params={"timeout": 50}, timeout=55)
            print(f"[drop {name} retry] status={st} raw={str(raw)[:150]}")
    except Exception as e:
        print(f"[drop {name}] cleanup exception (non-fatal): {e}")


def adjudicate_extreme(tag, name, shard_number, client_timeout, poll_tries, poll_gap):
    """One resource-extreme leg. Returns True if the leg was created (cleanup needed)."""
    st, raw, dt = create_sharded(name, shard_number, client_timeout)

    if st == 0:
        # transport failure -> liveness re-check FIRST (G8/D3b-3)
        if liveness(f"transport-{tag}") != 200:
            defect("Type3_RuntimeFailure",
                   f"{tag}: shard_number={shard_number} (spec-legal, >=1, no documented "
                   f"max) made the service UNREACHABLE - /healthz dead after the "
                   f"request; service death is the exact forbidden outcome of "
                   f"qdrant_resource_shard_number_001; last raw={str(raw)[:200]}")
        # alive: poll for resolution within the stated observation window
        window = client_timeout + poll_tries * poll_gap
        for i in range(poll_tries):
            time.sleep(poll_gap)
            dst, sh = describe_shards(name)
            if dst == 200:
                print(f"[{tag}] late completion observed on poll {i+1} - created "
                      f"(shard_number echo={sh!r}); slow but handled")
                CREATED.append(name)
                return True
            if dst == 404:
                continue
            print(f"[{tag}] poll {i+1} describe={dst} (recorded)")
        defect("Type3_RuntimeFailure",
               f"{tag}: shard_number={shard_number} request did NOT resolve within "
               f"its observation window ({window:.0f}s: {client_timeout}s client "
               f"timeout + {poll_tries}x{poll_gap}s polls) while /healthz stays 200 - "
               f"neither completed (describe 404 throughout) nor rejected nor "
               f"errored; an unbounded operation is not graceful handling "
               f"(constraint qdrant_resource_shard_number_001)")

    if 500 <= st <= 599:
        if liveness(f"5xx-{tag}") != 200:
            defect("Type3_RuntimeFailure",
                   f"{tag}: shard_number={shard_number} produced {st} AND the service "
                   f"is dead/healthz failing afterwards - service death is forbidden; "
                   f"raw={str(raw)[:200]}")
        low = str(raw).lower()
        if any(m in low for m in PANIC_MARKERS):
            defect("Type3_RuntimeFailure",
                   f"{tag}: shard_number={shard_number} (spec-legal) triggered a "
                   f"crash-flavored {st} with panic markers while /healthz is alive - "
                   f"same unwrap/panic family as the R10 wal_retain_closed=0 defect; "
                   f"raw={str(raw)[:300]}")
        if str(raw).strip():
            print(f"[{tag}] {st} with a descriptive error body = documented service "
                  f"error (allowed outcome); recorded")
            return False
        # empty 5xx: one retry before judging
        retry_name = mkn(f"{tag}_r")
        st2, raw2, _ = create_sharded(retry_name, shard_number, min(client_timeout, 30))
        if st2 in (200, 201):
            CREATED.append(retry_name)
        if 500 <= st2 <= 599 and not str(raw2).strip():
            defect("Type3_RuntimeFailure",
                   f"{tag}: shard_number={shard_number} yields empty {st}/{st2} twice "
                   f"while /healthz is alive - an undocumented opaque failure is not "
                   f"a documented service error; raw={str(raw2)[:200]}")
        print(f"[{tag}] retry status {st2} (recorded); treating first {st} as a "
              f"documented service error occurrence")
        return False

    if st in (200, 201):
        CREATED.append(name)
        dst, sh = describe_shards(name)
        if dst == 200 and sh != shard_number:
            defect("Type4_StateLogicViolation",
                   f"{tag}: create with shard_number={shard_number} returned 200 but "
                   f"describe echoes shard_number={sh!r} (expected vs actual: "
                   f"{shard_number} vs {sh!r}) - the completed state does not match "
                   f"the requested resource allocation")
        print(f"[{tag}] completed with 200 (echo={sh!r}) - graceful completion "
              f"(allowed outcome); cleanup follows")
        return True

    if 400 <= st <= 499:
        print(f"[{tag}] rejected with {st} - graceful rejection (allowed outcome)")
        return False

    script_error(f"{tag}: unexpected status {st}; raw={str(raw)[:200]}")


def cleanup():
    for n in list(CREATED):
        drop_hard(n)


def main():
    hs, hraw = safe_request("GET", "healthz", timeout=15)
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")

    try:
        # ---- positive direction: legal small shard counts + echo oracle proof ----
        for legal in (1, 8):
            name = mkn(f"legal_{legal}")
            st, raw, _ = create_sharded(name, legal, 45)
            if st not in (200, 201):
                if st == 0 and liveness(f"transport-legal{legal}") != 200:
                    script_error(f"legal shard_number={legal} transport failure and /healthz down")
                if 500 <= st <= 599:
                    if liveness(f"5xx-legal{legal}") != 200:
                        script_error(f"legal shard_number={legal} 5xx ({st}) and /healthz not 200")
                    defect("Type3_RuntimeFailure",
                           f"legal shard_number={legal} raised {st} while /healthz "
                           f"alive; raw={str(raw)[:200]}")
                script_error(f"legal shard_number={legal} returned {st}; raw={str(raw)[:200]}")
            CREATED.append(name)
            dst, sh = describe_shards(name)
            if dst != 200 or sh != legal:
                defect("Type4_StateLogicViolation",
                       f"legal shard_number={legal}: describe after 200 gives "
                       f"status={dst} echo={sh!r} (expected vs actual: {legal} vs "
                       f"{sh!r}) - echo oracle broken or allocation ignored")
            print(f"[legal {legal}] created and echoed - echo oracle proven")

        # ---- resource-extreme direction (spec-legal, no documented max) ----
        # extreme A: uint32 maximum - probes allocation unwrap at the domain top
        adjudicate_extreme("extremeA_uint32max", mkn("ext_uint32max"),
                           4294967295, client_timeout=35, poll_tries=2, poll_gap=8)
        # extreme B: 1000x the default - sustained resource pressure
        adjudicate_extreme("extremeB_1000x", mkn("ext_1000x"),
                           1000, client_timeout=75, poll_tries=2, poll_gap=8)

        # ---- post-condition: the service must be undamaged ----
        phs = liveness("post")
        if phs != 200:
            defect("Type3_RuntimeFailure",
                   f"/healthz returned {phs} AFTER the spec-legal shard_number legs - "
                   f"the service was left degraded/dead by a spec-legal value "
                   f"(forbidden outcome of qdrant_resource_shard_number_001)")
        post = mkn("post_create")
        ok, err = rt.setup_default(post, 4, "Cosine")
        if not ok:
            defect("Type3_RuntimeFailure",
                   f"a fresh plain create FAILED after the spec-legal shard_number "
                   f"legs ({err[:200]}) - the service no longer serves its core "
                   f"operation; resource-extreme spec-legal values left it degraded")
        CREATED.append(post)
        print("[post] /healthz 200 and a fresh create succeeds - service undamaged")

        print("[summary] legal shard counts complete with exact echo; the uint32-max "
              "and 1000x spec-legal extremes resolved gracefully (completed/rejected/"
              "documented error) with the service alive and serving afterwards - "
              "constraint qdrant_resource_shard_number_001 holds")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
