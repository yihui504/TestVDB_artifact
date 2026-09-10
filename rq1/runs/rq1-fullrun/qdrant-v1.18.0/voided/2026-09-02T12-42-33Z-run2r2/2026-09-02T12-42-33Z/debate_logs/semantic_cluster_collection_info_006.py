#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_collection_info_006
# strategy: metamorphic
# endpoint: cluster+collection+info
# constraint_ids: qdrant_behavioral_cluster_collection_info_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness - structural info stability under data-plane mutations)
"""
Attack: metamorphic x qdrant_behavioral_cluster_collection_info_001 (chunk_cluster+collection+info; strategy 6, topology invariance under non-structural mutations)
Oracle: the structural topology tuple (peer_id, shard_count, sorted local shard_id set, remote_shards length, shard_transfers length) returned with HTTP 200 is IDENTICAL before and after non-structural data-plane mutations - a waited upsert of points and a waited point deletion; any topology difference caused by a data write is Type4_StateLogicViolation, and any non-200 answer after the mutations is Type1_IllegalRejection of the "existing collection: HTTP 200" promise (assertion qdrant_behavioral_cluster_collection_info_001)

Mutation justification (G6): point upsert/delete is the dominant concurrent
activity against a live collection, and cluster info is the topology face
operators poll during it. Shard placement is a structural property decided at
collection create/update time; a mere data write carries no shard-management
operation, so the topology tuple must not move. The reads are taken
immediately after each waited mutation (wait=true makes the write
acknowledged-completed), which is exactly the timing where a racy shard
bookkeeping recomputation would surface a flap; points_count inside
local_shards entries is deliberately EXCLUDED from the tuple (it is expected
to move with the data and its visibility timing is not pinned by this chunk's
assertion).

Face closure: each post-mutation read must still answer 200 (the assertion's
positive promise holds in every data state), keeping this script consistent
with semantic_cluster_collection_info_004's lifecycle matrix.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (collection_cluster / upsert_points / delete_points /
setup_default / drop_collection / healthz); qdrant wait is a URL query
parameter, never a body member (silent-drop lesson); 2-tuple (status, raw).
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

VECTOR_KEY = "vector"          # qdrant point vector member (contract.data_types dense vector)


# ---------------- helpers ----------------
def parse_result(raw):
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    if isinstance(b, dict):
        return b.get("result")
    return None


def topology_tuple(res):
    """Structural topology projection of CollectionClusterInfo.

    points_count is deliberately excluded: it legitimately moves with data
    writes (that movement is not pinned by this chunk's assertion)."""
    local_ids = sorted(
        e.get("shard_id") for e in (res.get("local_shards") or [])
        if isinstance(e, dict)
    )
    remote_len = len(res.get("remote_shards") or [])
    transfers_len = len(res.get("shard_transfers") or [])
    return (res.get("peer_id"), res.get("shard_count"),
            tuple(local_ids), remote_len, transfers_len)


def liveness_ok():
    try:
        st, _ = rt.request("GET", "healthz", timeout=5)
        return st == 200
    except Exception:
        return False


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def read_topology(label):
    """GET cluster info; must be 200 with a result object (judge_200 face)."""
    st, raw = rt.request("GET", "collection_cluster", path_params={"name": COL})
    print(f"[{label}] cluster info: status={st} raw={raw[:400]}")
    v = rt.judge_200(st, raw, setup_ok=SETUP_OK)
    if v == "SCRIPT_ERROR":
        alive = liveness_ok()
        script_error(f"[{label}] cluster info unavailable (status={st}, server alive={alive}); no defect conclusion")
    if v == "DEFECT_FOUND":
        defect("Type1_IllegalRejection",
               f"[{label}] after a data-plane mutation, legal GET cluster info of existing collection "
               f"'{COL}' answered {st} - the assertion promises HTTP 200 for an existing collection; "
               f"raw={raw[:300]}")
    res = parse_result(raw)
    if not isinstance(res, dict):
        defect("Type4_StateLogicViolation",
               f"[{label}] 200 response must carry CollectionClusterInfo under the result envelope; "
               f"got: {raw[:300]}")
    tup = topology_tuple(res)
    print(f"[{label}] topology tuple: {tup}")
    return tup


TS = str(int(time.time()))
PREFIX = f"s4ci6_{TS}_"
COL = PREFIX + "col"


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception:
        pass


try:
    # ---- baseline: topology before any data ----
    ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL}: {err}")
    SETUP_OK = True
    T0 = read_topology("baseline")

    # ---- mutation 1: waited upsert of 3 points ----
    points = [
        {"id": 1, VECTOR_KEY: [0.1, 0.2, 0.3, 0.4]},
        {"id": 2, VECTOR_KEY: [0.4, 0.3, 0.2, 0.1]},
        {"id": 3, VECTOR_KEY: [0.2, 0.2, 0.2, 0.2]},
    ]
    st, raw = rt.request("PUT", "upsert_points", {"points": points},
                         path_params={"name": COL}, query_params={"wait": "true"}, timeout=30)
    print(f"mutation upsert(wait=true): status={st} raw={raw[:200]}")
    if st == 0 or 500 <= st <= 599:
        alive = liveness_ok()
        script_error(f"mutation upsert unavailable (status={st}, server alive={alive})")
    if st != 200:
        script_error(f"mutation upsert failed: {st} {raw[:300]}")
    T1 = read_topology("after-upsert")
    if T1 != T0:
        defect("Type4_StateLogicViolation",
               f"topology changed under a pure data write: baseline {T0} vs after-upsert {T1} "
               f"(upsert carries no shard-management operation; peer_id/shard_count/shard ids "
               f"must be invariant under data-plane mutations)")

    # ---- mutation 2: waited deletion of one point ----
    st, raw = rt.request("POST", "delete_points", {"points": [2]},
                         path_params={"name": COL}, query_params={"wait": "true"}, timeout=30)
    print(f"mutation delete point 2 (wait=true): status={st} raw={raw[:200]}")
    if st == 0 or 500 <= st <= 599:
        alive = liveness_ok()
        script_error(f"mutation delete unavailable (status={st}, server alive={alive})")
    if st != 200:
        script_error(f"mutation delete failed: {st} {raw[:300]}")
    T2 = read_topology("after-delete")
    if T2 != T0:
        defect("Type4_StateLogicViolation",
               f"topology changed under a pure data delete: baseline {T0} vs after-delete {T2} "
               f"(point deletion carries no shard-management operation; the structural tuple "
               f"must be invariant under data-plane mutations)")

    print(f"topology invariant across baseline -> upsert -> delete: {T0}")
    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
