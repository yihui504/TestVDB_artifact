#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_collection_info_004
# strategy: illegal_rejection
# endpoint: cluster+collection+info
# constraint_ids: qdrant_behavioral_cluster_collection_info_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - consistency of the documented 200 promise across collection lifecycle states)
"""
Attack: illegal_rejection x qdrant_behavioral_cluster_collection_info_001 (chunk_cluster+collection+info; strategy 3, legal-input matrix across lifecycle states)
Oracle: a GET of cluster info is legal for EVERY lifecycle state of an existing collection - (1) fresh collection read immediately (0s) after the create acknowledgment, (2) collection holding upserted points with payloads, (3) collection after a payload-field index creation - and every state answers HTTP 200 with a result object; any non-200 answer while /healthz is alive is Type1_IllegalRejection (legal input wrongly rejected) of the assertion's "existing collection: HTTP 200" promise

Assertion qdrant_behavioral_cluster_collection_info_001 (evidence_tier=explicit):
  "existing collection: HTTP 200 with cluster info; unknown collection: HTTP
  404". The 200 promise attaches to the collection's existence, not to a
  particular lifecycle phase - a server that answers 200 only for empty or
  only for settled collections violates the promise for the other states.

Why the immediate-after-create read matters (G6-style timing argument): the
create call has already been acknowledged (200 from PUT), so the collection
exists from the API's own point of view; if cluster-info bookkeeping lags and
the endpoint answers a transient non-200 for a just-acknowledged collection,
the caller cannot distinguish it from the documented 404 (unknown) - a
freshness hole in the 200 promise. State (2) exercises the data-bearing face
and state (3) the schema-mutated face (payload index via contract endpoint
index+create, body field_name/field_schema per contract parameters).

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (collection_cluster / setup_default / insert via
upsert_points / create_index / drop_collection / healthz); literal paths
forbidden; 2-tuple (status, raw).
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
PAYLOAD_KEY = "payload"        # qdrant point payload member (contract.data_types payload JSON)


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


def probe_state(state_label):
    """The shared oracle: cluster info of an existing collection must answer
    200 with a result object in EVERY lifecycle state (judge_200 face + result
    envelope check)."""
    st, raw = rt.request("GET", "collection_cluster", path_params={"name": COL})
    print(f"[{state_label}] cluster info: status={st} raw={raw[:400]}")
    v = rt.judge_200(st, raw, setup_ok=SETUP_OK)
    if v == "SCRIPT_ERROR":
        alive = liveness_ok()
        script_error(f"[{state_label}] cluster info unavailable (status={st}, server alive={alive}); no defect conclusion")
    if v == "DEFECT_FOUND":
        defect("Type1_IllegalRejection",
               f"[{state_label}] legal GET cluster info of existing collection '{COL}' answered {st} - "
               f"the assertion promises HTTP 200 for an existing collection in any lifecycle state; "
               f"raw={raw[:300]}")
    res = parse_result(raw)
    if not isinstance(res, dict):
        defect("Type4_StateLogicViolation",
               f"[{state_label}] 200 response must carry the CollectionClusterInfo object under the "
               f"result envelope; got: {raw[:300]}")
    return res


TS = str(int(time.time()))
PREFIX = f"s4ci4_{TS}_"
COL = PREFIX + "col"
INDEX_FIELD = PREFIX + "city"


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception:
        pass


try:
    # ---- state (1): fresh collection, read immediately after create ack ----
    ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL}: {err}")
    SETUP_OK = True
    r1 = probe_state("fresh-0s")

    # ---- state (2): collection holding points with payloads ----
    points = [
        {"id": 1, VECTOR_KEY: [0.1, 0.2, 0.3, 0.4], PAYLOAD_KEY: {INDEX_FIELD: "berlin"}},
        {"id": 2, VECTOR_KEY: [0.4, 0.3, 0.2, 0.1], PAYLOAD_KEY: {INDEX_FIELD: "lisbon"}},
        {"id": 3, VECTOR_KEY: [0.2, 0.2, 0.2, 0.2], PAYLOAD_KEY: {INDEX_FIELD: "osaka"}},
    ]
    ok, err = rt.insert_points(COL, points)
    if not ok:
        script_error(f"setup failed inserting points into {COL}: {err}")
    r2 = probe_state("with-points")

    # ---- state (3): collection after a payload-field index creation ----
    st, raw = rt.request("PUT", "create_index",
                         {"field_name": INDEX_FIELD, "field_schema": "keyword"},
                         path_params={"name": COL}, timeout=20)
    print(f"create payload index on '{INDEX_FIELD}': status={st} raw={raw[:200]}")
    if st == 0 or 500 <= st <= 599:
        alive = liveness_ok()
        script_error(f"index creation unavailable (status={st}, server alive={alive})")
    if st != 200:
        script_error(f"setup index creation failed: {st} {raw[:300]}")
    r3 = probe_state("with-payload-index")

    print(f"topology observed in all three states: "
          f"shard_count={r1.get('shard_count')}/{r2.get('shard_count')}/{r3.get('shard_count')}, "
          f"peer_id={r1.get('peer_id')}/{r2.get('peer_id')}/{r3.get('peer_id')} "
          f"(invariance itself is asserted by semantic_cluster_collection_info_006)")
    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
