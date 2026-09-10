#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_collection_update_005
# strategy: illegal_rejection
# endpoint: cluster+collection+update
# constraint_ids: qdrant_behavioral_cluster_collection_update_001, qdrant_state_cluster_collection_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the documented-valid acceptance face and the timeout>=1 boundary must not be wrongly rejected)
"""
Attack: illegal_rejection x qdrant_behavioral_cluster_collection_update_001 + qdrant_state_cluster_collection_update_001 (chunk_cluster+collection+update; strategy 3 - legal faces: valid create_sharding_key / drop_sharding_key must be accepted 200, and the legal timeout query boundary (min 1) must not turn acceptance into rejection)
Oracle: on a custom-sharded collection, create_sharding_key (no timeout), create_sharding_key with query timeout=1 (the documented min boundary itself) and timeout=30, and drop_sharding_key of a just-accepted key each return HTTP 200 via judge_200 - any 4xx on these legal requests is Type1_IllegalRejection (a legal operation wrongly refused), a 5xx with /healthz alive is Type3

Constraint anchors (both evidence_tier=explicit):
  - assertion qdrant_behavioral_cluster_collection_update_001: "valid cluster
    operation returns HTTP 200 (accepted)" - the acceptance face of the
    endpoint, exercised with a single-node-feasible member of the documented
    operation enum (create_sharding_key / drop_sharding_key, contract
    cluster+collection+update parameters);
  - state constraint qdrant_state_cluster_collection_update_001: "these
    operations initiate asynchronous transfers - HTTP 200 means the operation
    was accepted" - so acceptance (200) is the promise; synchronous completion
    is NOT asserted here (async-observability is owned by script 002/006).

timeout query parameter (contract parameter: "query: min 1"): the boundary
value 1 itself is legal (G4 boundary closure - min/max themselves must be
accepted); it is sent as a URL query parameter, never in the body (v34 R1 S1
lesson: body-side timeout is silently dropped and the probe goes blind).

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (collection_cluster = raw_knowledge url
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


def run_legal_face(face_name, body, query_params=None):
    """One legal face: pre-triage transport/5xx inline, then judge_200 for the
    acceptance oracle (200 -> NO_DEFECT; 4xx -> Type1_IllegalRejection)."""
    st, raw = safe_request("POST", "collection_cluster", body,
                           path_params={"name": COL}, query_params=query_params)
    qp = f" query_params={query_params}" if query_params else ""
    print(f"{face_name}{qp}: status={st} raw={raw[:300]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure on {face_name} (status=0, /healthz={hs}); no defect conclusion")
    if 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[5xx liveness] /healthz probe status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            script_error(f"{face_name}: 5xx status {st} and /healthz not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"{face_name}: legal cluster operation answered server error {st} while /healthz is 200; "
               f"raw={raw[:200]}")
    v = rt.judge_200(st, raw, setup_ok=SETUP_OK)
    if v == "DEFECT_FOUND":
        defect("Type1_IllegalRejection",
               f"{face_name}: legal cluster operation wrongly rejected with status {st} - assertion "
               f"qdrant_behavioral_cluster_collection_update_001 promises HTTP 200 (accepted) for a "
               f"valid operation; raw={raw[:300]}")
    if v == "SCRIPT_ERROR":
        script_error(f"{face_name}: unexpected status class {st}; cannot adjudicate; raw={raw[:200]}")
    print(f"{face_name}: accepted (200)")


TS = str(int(time.time()))
PREFIX = f"s5cu5_{TS}_"
COL = PREFIX + "col_custom"
KEY_PLAIN = PREFIX + "sk_plain"
KEY_T1 = PREFIX + "sk_t1"
KEY_T30 = PREFIX + "sk_t30"


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception:
        pass


try:
    # ---- setup: custom-sharded collection (sharding-key ops require it) ----
    st, raw = safe_request("PUT", "create_collection", {
        "vectors": {"size": 4, "distance": "Cosine"},
        "sharding_method": "custom",   # contract collections+create param: enum auto|custom
    }, path_params={"name": COL})
    print(f"create custom-sharded collection '{COL}': status={st} raw={raw[:300]}")
    if st not in (200, 201):
        script_error(f"setup failed creating custom-sharded {COL}: {st} {raw[:300]}")
    SETUP_OK = True

    # ---- face 1: valid create_sharding_key, no timeout -> 200 accepted ----
    run_legal_face("face1 create_sharding_key (plain)", {
        "operation": "create_sharding_key",
        "shard_key": KEY_PLAIN,
    })

    # ---- face 2: same op with timeout=1 (documented min boundary, query param) -> 200 ----
    run_legal_face("face2 create_sharding_key (timeout=1 min boundary)", {
        "operation": "create_sharding_key",
        "shard_key": KEY_T1,
    }, query_params={"timeout": 1})

    # ---- face 3: same op with timeout=30 (ordinary legal value) -> 200 ----
    run_legal_face("face3 create_sharding_key (timeout=30)", {
        "operation": "create_sharding_key",
        "shard_key": KEY_T30,
    }, query_params={"timeout": 30})

    # ---- face 4: drop_sharding_key of a just-accepted key -> 200 accepted ----
    run_legal_face("face4 drop_sharding_key (just-accepted key)", {
        "operation": "drop_sharding_key",
        "shard_key": KEY_PLAIN,
    })

    print("all legal faces accepted (200)")
    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
