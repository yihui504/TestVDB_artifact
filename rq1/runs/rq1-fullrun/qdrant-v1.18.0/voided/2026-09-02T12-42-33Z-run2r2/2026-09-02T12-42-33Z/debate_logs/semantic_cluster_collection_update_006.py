#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_collection_update_006
# strategy: metamorphic
# endpoint: cluster+collection+update
# constraint_ids: qdrant_state_cluster_collection_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness - async-accepted drop vs effective state reconciliation)
"""
Attack: metamorphic x qdrant_state_cluster_collection_update_001 (chunk_cluster+collection+update; strategy 6 - create -> drop -> recreate round trip forces the async-acceptance/effective-state invariant to reconcile)
Oracle: on a custom-sharded collection, after create_sharding_key(K)=200 and drop_sharding_key(K)=200 (both async-accepted), the cluster info body stops mentioning K within a 30s bounded poll, and recreating the SAME key K is then accepted with HTTP 200 - if K never disappears from cluster info after an accepted drop, or the recreate is rejected with an already-exists-class 4xx after K was observed gone, the async-accepted state never reconciled with observable state, which is Type4_StateLogicViolation

Constraint qdrant_state_cluster_collection_update_001 (state_constraint,
evidence_tier=explicit): "these operations initiate asynchronous transfers -
HTTP 200 means the operation was accepted, not completed; progress is
observable through the collection cluster info endpoint."

G6 mutation justification (why THIS sequence breaks the invariant most easily):
the mutation point is the acceptance-vs-effectiveness gap of the DROP - the
async window is the only place where a stale in-memory shard map can keep
advertising a dropped key; forcing the SAME key to be re-created immediately
after the drop converts invisible async lag into a user-visible contradiction
(a legal recreate rejected as 'already exists', or an accepted drop whose key
never leaves the info body). Duplication of the key (create, drop, re-create
the same identifier) is the cheapest state-reconciliation trip wire on a
single-peer deployment.

Face ownership (avoid double-claiming): the create-time observability claim
(key must appear in info after accepted create) is owned by script 002 - here
it is only a PRECONDITION (SCRIPT_ERROR if the channel is unavailable, not a
defect claim); the load-bearing oracle of this script is the drop-side
reconciliation + recreate acceptance.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (collection_cluster GET/POST = raw_knowledge url
/collections/{collection_name}/cluster; create_collection / healthz); literal
paths forbidden; 2-tuple (status, raw). Transport-failure branches re-check
liveness via an inline safe_request("GET","healthz") probe with a printed
status.
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


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def cluster_info_or_die(context):
    """One cluster info poll with transport/5xx inline triage (visible healthz probes)."""
    st, raw = safe_request("GET", "collection_cluster", path_params={"name": COL})
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure on cluster info during {context} (status=0, /healthz={hs}); no defect conclusion")
    if 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[5xx liveness] /healthz probe status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            script_error(f"cluster info answered 5xx ({st}) during {context} and /healthz not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"cluster info endpoint failed with {st} during {context} while /healthz is 200; raw={raw[:200]}")
    if st != 200:
        script_error(f"cluster info status {st} during {context}: {raw[:300]}")
    return raw


TS = str(int(time.time()))
PREFIX = f"s5cu6_{TS}_"
COL = PREFIX + "col_custom"
KEY = PREFIX + "sk_roundtrip"
DEADLINE_S = 30.0
POLL_S = 0.5


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception:
        pass


try:
    # ---- setup: custom-sharded collection ----
    st, raw = safe_request("PUT", "create_collection", {
        "vectors": {"size": 4, "distance": "Cosine"},
        "sharding_method": "custom",   # contract collections+create param: enum auto|custom
    }, path_params={"name": COL})
    print(f"create custom-sharded collection '{COL}': status={st} raw={raw[:300]}")
    if st not in (200, 201):
        script_error(f"setup failed creating custom-sharded {COL}: {st} {raw[:300]}")
    SETUP_OK = True

    # ---- step 1: create key K -> must be accepted 200 ----
    st, raw = safe_request("POST", "collection_cluster", {
        "operation": "create_sharding_key",
        "shard_key": KEY,
    }, path_params={"name": COL})
    print(f"step1 create_sharding_key '{KEY}': status={st} raw={raw[:300]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure on step1 create (status=0, /healthz={hs}); no defect conclusion")
    if st != 200:
        script_error(f"step1 create_sharding_key not accepted ({st}) - precondition failed "
                     f"(rejection claim owned by semantic_cluster_collection_update_005); raw={raw[:300]}")

    # ---- step 2 (precondition only, claim owned by 002): K must become observable ----
    t0 = time.time()
    visible = False
    while time.time() - t0 < DEADLINE_S:
        raw = cluster_info_or_die("create-observability precondition")
        if KEY in raw:
            visible = True
            break
        time.sleep(POLL_S)
    if not visible:
        script_error(f"observability channel unavailable: '{KEY}' never appeared in cluster info "
                     f"after accepted create within {DEADLINE_S:.0f}s - create-side claim owned by "
                     f"semantic_cluster_collection_update_002; cannot run the drop round trip")
    print(f"step2 precondition: '{KEY}' observable in cluster info after {time.time() - t0:.1f}s")

    # ---- step 3: drop key K -> must be accepted 200 (async) ----
    st, raw = safe_request("POST", "collection_cluster", {
        "operation": "drop_sharding_key",
        "shard_key": KEY,
    }, path_params={"name": COL})
    print(f"step3 drop_sharding_key '{KEY}': status={st} raw={raw[:300]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure on step3 drop (status=0, /healthz={hs}); no defect conclusion")
    if 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[5xx liveness] /healthz probe status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            script_error(f"step3 drop answered 5xx ({st}) and /healthz not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"drop_sharding_key of an existing key answered server error {st} while /healthz is 200; raw={raw[:200]}")
    if st != 200:
        script_error(f"step3 drop_sharding_key not accepted ({st}) - precondition failed "
                     f"(rejection claim owned by semantic_cluster_collection_update_005); raw={raw[:300]}")

    # ---- step 4 (load-bearing): K must stop being observable within the deadline ----
    t1 = time.time()
    gone_at = None
    last_raw = ""
    while time.time() - t1 < DEADLINE_S:
        last_raw = cluster_info_or_die("drop-observability poll")
        if KEY not in last_raw:
            gone_at = time.time() - t1
            break
        time.sleep(POLL_S)
    print(f"step4 poll finished: elapsed={time.time() - t1:.1f}s gone={gone_at is not None}")
    if gone_at is None:
        defect("Type4_StateLogicViolation",
               f"drop_sharding_key('{KEY}') was accepted with HTTP 200 but the key is STILL observable "
               f"in the collection cluster info body after {DEADLINE_S:.0f}s - the async-accepted drop "
               f"never reconciled with observable state, violating constraint 'progress is observable "
               f"through the collection cluster info endpoint'; last info: {last_raw[:300]}")
    print(f"step4: '{KEY}' left cluster info after {gone_at:.1f}s (drop became effective/observable)")

    # ---- step 5 (load-bearing): recreate the SAME key must be accepted 200 ----
    st, raw = safe_request("POST", "collection_cluster", {
        "operation": "create_sharding_key",
        "shard_key": KEY,
    }, path_params={"name": COL})
    print(f"step5 recreate_sharding_key '{KEY}': status={st} raw={raw[:300]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure on step5 recreate (status=0, /healthz={hs}); no defect conclusion")
    if 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[5xx liveness] /healthz probe status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            script_error(f"step5 recreate answered 5xx ({st}) and /healthz not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"recreating a legally dropped shard key answered server error {st} while /healthz is 200; "
               f"raw={raw[:200]}")
    if st != 200:
        defect("Type4_StateLogicViolation",
               f"create -> accepted-drop -> observable-gone round trip breaks at recreate: the SAME key "
               f"'{KEY}' that was accepted-dropped and confirmed gone from cluster info is rejected on "
               f"recreation with status {st} - async-accepted state never reconciled with the effective "
               f"shard map (stale 'already exists' bookkeeping); raw={raw[:300]}")

    print("round trip reconciled: create accepted -> drop accepted -> key gone -> recreate accepted")
    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
