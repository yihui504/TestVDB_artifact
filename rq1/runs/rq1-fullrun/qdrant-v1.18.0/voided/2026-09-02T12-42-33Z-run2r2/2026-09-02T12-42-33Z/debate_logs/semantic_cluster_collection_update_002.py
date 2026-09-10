#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_collection_update_002
# strategy: behavioral_contract
# endpoint: cluster+collection+update
# constraint_ids: qdrant_state_cluster_collection_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness - async acceptance vs observable completion)
"""
Attack: behavioral_contract x qdrant_state_cluster_collection_update_001 (chunk_cluster+collection+update; strategy 1 - async acceptance vs observability: 200 means accepted, progress/completion observable via collection cluster info)
Oracle: after create_sharding_key is accepted with HTTP 200 on a custom-sharded collection, the GET collection cluster info endpoint keeps answering 200, carries a shard_transfers key in its result envelope (the constraint's named observability surface), and the new shard key becomes observable in the info body within a 30s bounded poll - a 200-accepted op whose effect is never observable in cluster info, or a missing shard_transfers surface, is Type4_StateLogicViolation (constraint qdrant_state_cluster_collection_update_001)

Constraint qdrant_state_cluster_collection_update_001 (state_constraint, level=system,
evidence_tier=explicit):
  assertion: "shard move/replicate operations return 200 on acceptance; completion is
  asynchronous and observable via cluster info (shard_transfers)"
  description: "these operations initiate asynchronous transfers - HTTP 200 means
  the operation was accepted, not completed; progress is observable through the
  collection cluster info endpoint"

What is tested here (single-node feasible member of the endpoint's operation
enum, from the contract parameter list):
  1. acceptance face: create_sharding_key returns 200 = ACCEPTED (async) - not a
     synchronous completion claim, so no immediate-effect assertion is made at
     t=0 (that would over-claim against the async promise);
  2. observability face: within a bounded 30s window the cluster info body must
     mention the new shard key (shape-tolerant: the key string appears anywhere
     in the result envelope - local_shards[].shard_key or the shards map) AND
     every info poll during the window must answer 200 (serviceability under an
     in-flight async op);
  3. surface face: the cluster info result envelope must contain a
     "shard_transfers" key - the constraint names it as the progress channel; an
     absent key breaks the observability promise outright (same missing-field
     family as R4's resharding_operations finding on the sibling info endpoint).

G3 avoidance note: transfer-based ops (move_shard/replicate_shard) cannot be
legitimately accepted on a single-peer deployment (no second peer), so their
acceptance face is NOT claimed here; the sharding-key member exercises the same
acceptance-vs-observability contract on this endpoint. Cross-ref: script 005
owns the "valid op must be accepted" claim, script 001 owns dispositions.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (collection_cluster GET/POST = raw_knowledge
api_endpoints[].url /collections/{collection_name}/cluster; create_collection /
healthz); literal paths forbidden; 2-tuple (status, raw). Transport-failure
branches re-check liveness via an inline safe_request("GET","healthz") probe
with a printed status.
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

SETUP_OK = False


# ---------------- helpers ----------------
def safe_request(method, path_key, body=None, path_params=None, query_params=None):
    """All HTTP exits through this visible wrapper (R4 lesson); thin delegation, 2-tuple."""
    return rt.request(method, path_key, body=body, path_params=path_params,
                      query_params=query_params)


def parse_result(raw):
    """Extract the result object from a qdrant envelope (lesson: result.<field>)."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    if isinstance(b, dict):
        return b.get("result")
    return None


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


TS = str(int(time.time()))
PREFIX = f"s5cu2_{TS}_"
COL_C = PREFIX + "col_custom"
SHARD_KEY = PREFIX + "sk_obs"
DEADLINE_S = 30.0
POLL_S = 0.5


def cleanup():
    try:
        rt.drop_collection(COL_C)
    except Exception:
        pass


try:
    # ---- setup: custom-sharded collection (create_sharding_key requires it) ----
    st, raw = safe_request("PUT", "create_collection", {
        "vectors": {"size": 4, "distance": "Cosine"},
        "sharding_method": "custom",   # contract collections+create param: enum auto|custom
    }, path_params={"name": COL_C})
    print(f"create custom-sharded collection '{COL_C}': status={st} raw={raw[:300]}")
    if st not in (200, 201):
        script_error(f"setup failed creating custom-sharded {COL_C}: {st} {raw[:300]}")
    SETUP_OK = True

    # ---- baseline: info 200, shard_transfers surface present, key not yet observable ----
    st, raw = safe_request("GET", "collection_cluster", path_params={"name": COL_C})
    print(f"baseline cluster info '{COL_C}': status={st} raw={raw[:400]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure on baseline cluster info (status=0, /healthz={hs}); no defect conclusion")
    if st != 200:
        script_error(f"baseline cluster info unavailable (status={st}): {raw[:300]}")
    res = parse_result(raw)
    if not isinstance(res, dict):
        script_error(f"baseline cluster info must carry a result envelope; got: {raw[:300]}")
    if "shard_transfers" not in res:
        defect("Type4_StateLogicViolation",
               f"constraint qdrant_state_cluster_collection_update_001 names shard_transfers as the "
               f"progress channel of collection cluster info, but the result envelope has no "
               f"'shard_transfers' key - the observability surface itself is missing "
               f"(same missing-field family as R4 resharding_operations); raw={raw[:300]}")
    if SHARD_KEY in raw:
        script_error(f"baseline contamination: shard key '{SHARD_KEY}' already observable before creation")
    print("baseline OK: info 200 + shard_transfers surface present + key absent")

    # ---- acceptance face: create_sharding_key -> 200 means ACCEPTED (async) ----
    t_accept = time.time()
    st, raw = safe_request("POST", "collection_cluster", {
        "operation": "create_sharding_key",
        "shard_key": SHARD_KEY,
    }, path_params={"name": COL_C})
    print(f"create_sharding_key '{SHARD_KEY}': status={st} raw={raw[:300]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure submitting create_sharding_key (status=0, /healthz={hs}); no defect conclusion")
    if 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[5xx liveness] /healthz probe status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            script_error(f"create_sharding_key answered 5xx ({st}) and /healthz not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"valid create_sharding_key answered server error {st} while /healthz is 200; raw={raw[:200]}")
    if st != 200:
        # rejection claim is owned by script 005 (illegal_rejection); here it blocks the observability probe
        script_error(f"create_sharding_key not accepted ({st}) - cannot probe async observability; "
                     f"rejection claim owned by semantic_cluster_collection_update_005; raw={raw[:300]}")

    # ---- observability face: bounded poll until the shard key appears in cluster info ----
    observed_at = None
    polls = 0
    while time.time() - t_accept < DEADLINE_S:
        st, raw = safe_request("GET", "collection_cluster", path_params={"name": COL_C})
        polls += 1
        if st == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
            script_error(f"transport failure polling cluster info during async op (status=0, /healthz={hs}); no defect conclusion")
        if 500 <= st <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[5xx liveness] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                script_error(f"cluster info answered 5xx ({st}) during async op and /healthz not 200 (={hs}); no defect conclusion")
            defect("Type3_RuntimeFailure",
                   f"cluster info endpoint failed with {st} while an accepted async op was in flight "
                   f"(progress channel broken); raw={raw[:200]}")
        if st != 200:
            defect("Type4_StateLogicViolation",
                   f"progress channel broken: cluster info answered {st} (not 200) while the op was "
                   f"accepted with 200 - the constraint's observability endpoint is not serviceable; "
                   f"raw={raw[:200]}")
        if SHARD_KEY in raw:
            observed_at = time.time() - t_accept
            break
        time.sleep(POLL_S)

    print(f"poll finished: polls={polls} elapsed={time.time() - t_accept:.1f}s")
    if observed_at is None:
        defect("Type4_StateLogicViolation",
               f"create_sharding_key was accepted with HTTP 200 but its effect never became observable "
               f"in the collection cluster info body within {DEADLINE_S:.0f}s "
               f"({polls} polls) - violates constraint 'progress is observable through the collection "
               f"cluster info endpoint' (accepted-but-unobservable async op); last info: {raw[:300]}")
    print(f"shard key observable in cluster info after {observed_at:.1f}s (async acceptance -> observable completion)")

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
