#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_collection_update_004
# strategy: type_coercion
# endpoint: cluster+collection+update
# constraint_ids: qdrant_behavioral_cluster_collection_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust - nested cluster-op body types assumed validated by serde)
"""
Attack: type_coercion x qdrant_behavioral_cluster_collection_update_001 (chunk_cluster+collection+update; strategy 4 - wrong-typed peer_id/shard_id and wrong-form operation enum must be rejected 400, never silently coerced into acceptance)
Oracle: on an existing collection, each malformed probe - to_peer_id as string "424242" / float 424242.0 / boolean true, shard_id as string "0", operation as CamelCase "MoveShard" / kebab-case "move-shard" / unknown "teleport_shard", plus the int baseline 424242 - returns HTTP 400/422 via expect_rejected; any probe answered 2xx is Type1_IllegalSuccess (silent type coercion or undocumented enum alias accepted), a 5xx with /healthz alive is Type3

Constraint anchor: assertion qdrant_behavioral_cluster_collection_update_001
(evidence_tier=explicit) - "invalid peer/shard returns 400". The operation
parameter's documented wire enum (contract cluster+collection+update
parameters) is the snake_case set {move_shard, replicate_shard, abort_transfer,
drop_replica, create_sharding_key, drop_sharding_key, restart_transfer,
start_resharding, abort_resharding, replicate_states}; peer_id/shard_id are
integers.

Probes (BS-01: trust that the framework validates nested cluster bodies is the
blindspot - each probe mutates exactly ONE field; every other peer position
holds the live-derived peer id, so acceptance of a mutated probe can only be
explained by coercion/lenient parsing):
  baseline: to_peer_id = 424242 (int, cannot exist in a single-peer deployment) -> 400
  v1: to_peer_id = "424242" (string)         -> 400 expected; 200 = coercion
  v2: to_peer_id = 424242.0 (float)          -> 400 expected; 200 = coercion
  v3: to_peer_id = true (boolean)            -> 400 expected; 200 = coercion
  v4: shard_id   = "0" (string, valid int value as string; to_peer_id = live peer) -> 400 expected
  v5: operation  = "MoveShard" (CamelCase)   -> 400 expected; 200 = undocumented alias
  v6: operation  = "move-shard" (kebab)      -> 400 expected
  v7: operation  = "teleport_shard" (unknown enum member) -> 400 expected

Adjudication: expect_rejected (judge_4xx: 400/422 -> NO_DEFECT, 200 ->
DEFECT_FOUND); transport/5xx branches pre-triaged with inline
safe_request("GET","healthz") probes (R4 lesson), so the helper's
SCRIPT_ERROR branch only fires for odd 4xx classes, which are printed raw.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (collection_cluster = raw_knowledge url
/collections/{collection_name}/cluster; healthz); literal paths forbidden;
2-tuple (status, raw).
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


def run_probe(probe_name, body):
    """One malformed-body probe: pre-triage transport/5xx inline, then
    expect_rejected for the accept/reject oracle."""
    st, raw = safe_request("POST", "collection_cluster", body,
                           path_params={"name": COL})
    print(f"{probe_name}: status={st} raw={raw[:300]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure on {probe_name} (status=0, /healthz={hs}); no defect conclusion")
    if 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[5xx liveness] /healthz probe status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            script_error(f"{probe_name}: 5xx status {st} and /healthz not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"{probe_name}: malformed input answered server error {st} while /healthz is 200; raw={raw[:200]}")
    v = rt.expect_rejected(st, raw, setup_ok=SETUP_OK)
    if v == "DEFECT_FOUND":
        defect("Type1_IllegalSuccess",
               f"{probe_name}: malformed cluster-op body was ACCEPTED with status {st} - silent type "
               f"coercion / undocumented enum alias accepted (assertion: invalid peer/shard returns 400); "
               f"raw={raw[:200]}")
    if v == "SCRIPT_ERROR":
        script_error(f"{probe_name}: unexpected status class {st} (neither a clean rejection nor "
                     f"acceptance); cannot adjudicate; raw={raw[:200]}")
    print(f"{probe_name}: correctly rejected (status={st})")


TS = str(int(time.time()))
PREFIX = f"s5cu4_{TS}_"
COL = PREFIX + "col"
BAD_PEER = 424242


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception:
        pass


try:
    # ---- setup ----
    ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL}: {err}")
    SETUP_OK = True

    st, raw = safe_request("GET", "cluster_status")
    res = parse_result(raw)
    peer_id = res.get("peer_id") if isinstance(res, dict) else None
    if st != 200 or peer_id is None:
        script_error(f"cannot derive live peer_id from cluster status (status={st}); raw={raw[:200]}")
    print(f"derived live peer_id={peer_id}")

    # ---- baseline: int invalid peer -> must be a clean 400 rejection ----
    run_probe("baseline int to_peer_id=424242", {
        "operation": "move_shard",
        "shard_id": 0,
        "from_peer_id": peer_id,
        "to_peer_id": BAD_PEER,
    })

    # ---- wrong-typed peer_id variants (BS-01) ----
    run_probe("v1 string to_peer_id='424242'", {
        "operation": "move_shard",
        "shard_id": 0,
        "from_peer_id": peer_id,
        "to_peer_id": str(BAD_PEER),
    })
    run_probe("v2 float to_peer_id=424242.0", {
        "operation": "move_shard",
        "shard_id": 0,
        "from_peer_id": peer_id,
        "to_peer_id": float(BAD_PEER),
    })
    run_probe("v3 boolean to_peer_id=true", {
        "operation": "move_shard",
        "shard_id": 0,
        "from_peer_id": peer_id,
        "to_peer_id": True,
    })

    # ---- wrong-typed shard_id ----
    run_probe("v4 string shard_id='0'", {
        "operation": "replicate_shard",
        "shard_id": "0",
        "to_peer_id": peer_id,
    })

    # ---- wrong-form operation enum ----
    run_probe("v5 operation='MoveShard' (CamelCase)", {
        "operation": "MoveShard",
        "shard_id": 0,
        "from_peer_id": peer_id,
        "to_peer_id": BAD_PEER,
    })
    run_probe("v6 operation='move-shard' (kebab)", {
        "operation": "move-shard",
        "shard_id": 0,
        "from_peer_id": peer_id,
        "to_peer_id": BAD_PEER,
    })
    run_probe("v7 operation='teleport_shard' (unknown member)", {
        "operation": "teleport_shard",
        "shard_id": 0,
        "from_peer_id": peer_id,
        "to_peer_id": BAD_PEER,
    })

    print("all malformed probes rejected without coercion")
    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
