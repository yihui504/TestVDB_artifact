#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_collection_info_005
# strategy: metamorphic
# endpoint: cluster+collection+info
# constraint_ids: qdrant_type_cluster_collection_info_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - cross-face consistency of the documented topology fields)
"""
Attack: metamorphic x qdrant_type_cluster_collection_info_001 (chunk_cluster+collection+info; strategy 6, cross-face + repeat-consistency relations of the typed topology fields)
Oracle: for one unchanged collection, (R1) two consecutive cluster-info reads return identical (peer_id, shard_count); (R2) cluster-info shard_count equals describe_collection's result.config.params.shard_number (both documented integer topology fields of the same collection); (R3) cluster-info peer_id equals cluster_status's result.peer_id (this-peer identity on both cluster faces); any relation mismatch is Type4_StateLogicViolation (constraint qdrant_type_cluster_collection_info_001)

Metamorphic relations (each anchored on the constraint's typed members):

  R1 repeat-stability: GET cluster info is a pure read; nothing changes between
     two consecutive reads, so peer_id/shard_count (both documented members of
     CollectionClusterInfo) must be identical. A flap means the typed fields
     are being recomputed non-deterministically.

  R2 cross-endpoint shard agreement: collections+get's response_shape
     (contract api_endpoints) declares result.config.params.shard_number as an
     integer; cluster+collection+info declares shard_count as the total number
     of shards. Two documented views of the SAME quantity for the SAME
     collection must agree - a disagreement means at least one face misreports
     the collection's topology (Type4).

  R3 cross-endpoint peer agreement: cluster+status (contract description)
     exposes peer_id of the answering peer; CollectionClusterInfo.peer_id is
     documented as "ID of this peer". Equality is required when the
     cluster-status face is readable; if that face is unavailable the sub-check
     is skipped with a printed note (no claim pinned on a foreign chunk's
     availability).

Both reads happen with no state mutation in between, so every relation is
deterministic; setup failures are SCRIPT_ERROR, never defect conclusions (G8).

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (collection_cluster / describe_collection / cluster_status
/ setup_default / drop_collection / healthz); literal paths forbidden.
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
def parse_result(raw):
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    if isinstance(b, dict):
        return b.get("result")
    return None


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


TS = str(int(time.time()))
PREFIX = f"s4ci5_{TS}_"
COL = PREFIX + "col"


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception:
        pass


try:
    # ---- setup: one unchanged collection ----
    ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL}: {err}")
    SETUP_OK = True

    # ---- R1: repeat-stability of the typed topology fields ----
    st1, raw1 = rt.request("GET", "collection_cluster", path_params={"name": COL})
    st2, raw2 = rt.request("GET", "collection_cluster", path_params={"name": COL})
    print(f"cluster info read#1: status={st1} raw={raw1[:400]}")
    print(f"cluster info read#2: status={st2} raw={raw2[:200]}")
    for label, (st, raw) in (("read#1", (st1, raw1)), ("read#2", (st2, raw2))):
        v = rt.judge_200(st, raw, setup_ok=SETUP_OK)
        if v == "SCRIPT_ERROR":
            alive = liveness_ok()
            script_error(f"{label} unavailable (status={st}, server alive={alive}); no defect conclusion")
        if v == "DEFECT_FOUND":
            defect("Type1_IllegalRejection",
                   f"{label}: legal cluster-info GET of existing collection '{COL}' answered {st}; raw={raw[:300]}")
    res1, res2 = parse_result(raw1), parse_result(raw2)
    if not isinstance(res1, dict) or not isinstance(res2, dict):
        defect("Type4_StateLogicViolation",
               f"both reads must carry CollectionClusterInfo under the result envelope; "
               f"read#1={type(res1).__name__} read#2={type(res2).__name__}; raw1={raw1[:200]}")
    t1 = (res1.get("peer_id"), res1.get("shard_count"))
    t2 = (res2.get("peer_id"), res2.get("shard_count"))
    print(f"R1 tuples: read#1={t1} read#2={t2}")
    if t1 != t2:
        defect("Type4_StateLogicViolation",
               f"R1 repeat-stability violated: two consecutive reads of the unchanged collection "
               f"'{COL}' returned different (peer_id, shard_count): {t1} vs {t2}")

    # ---- R2: cluster shard_count == describe shard_number (same quantity, two faces) ----
    std, draw = rt.request("GET", "describe_collection", path_params={"name": COL})
    print(f"describe collection: status={std} raw={draw[:200]}")
    if std == 0 or 500 <= std <= 599:
        alive = liveness_ok()
        script_error(f"describe unavailable (status={std}, server alive={alive}); R2 cannot be evaluated")
    if std != 200:
        script_error(f"describe of existing collection '{COL}' failed: {std} {draw[:300]}")
    dres = parse_result(draw)
    shard_number = None
    if isinstance(dres, dict):
        params = dres.get("config")
        if isinstance(params, dict):
            params = params.get("params")
        if isinstance(params, dict):
            shard_number = params.get("shard_number")
    if not isinstance(shard_number, int):
        script_error(f"describe result lacks the contract-declared integer result.config.params.shard_number: "
                     f"{draw[:300]}")
    print(f"R2 comparison: cluster shard_count={res1.get('shard_count')} vs describe shard_number={shard_number}")
    if res1.get("shard_count") != shard_number:
        defect("Type4_StateLogicViolation",
               f"R2 cross-face agreement violated: cluster+collection+info reports shard_count="
               f"{res1.get('shard_count')} while collections+get reports config.params.shard_number="
               f"{shard_number} for the same collection '{COL}' - two documented views of the same "
               f"topology quantity disagree")

    # ---- R3: cluster-info peer_id == cluster_status peer_id (this-peer identity) ----
    stc, craw = rt.request("GET", "cluster_status", timeout=15)
    print(f"cluster status: status={stc} raw={craw[:300]}")
    if stc == 200:
        cres = parse_result(craw)
        status_peer = cres.get("peer_id") if isinstance(cres, dict) else None
        if status_peer is None:
            print("R3 note: cluster-status face readable but carries no peer_id; sub-check skipped")
        else:
            print(f"R3 comparison: cluster-info peer_id={res1.get('peer_id')} vs cluster-status peer_id={status_peer}")
            if res1.get("peer_id") != status_peer:
                defect("Type4_StateLogicViolation",
                       f"R3 cross-face agreement violated: cluster+collection+info reports peer_id="
                       f"{res1.get('peer_id')} while cluster+status reports peer_id={status_peer} - "
                       f"the same answering peer must have one identity on both cluster faces")
    else:
        print(f"R3 note: cluster-status face unavailable (status={stc}); sub-check skipped without a claim")

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
