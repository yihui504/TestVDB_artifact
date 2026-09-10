#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_collection_update_007
# strategy: metamorphic
# endpoint: cluster+collection+update
# constraint_ids: qdrant_behavioral_cluster_collection_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - disposition consistency of the same invalid value across operation variants)
"""
Attack: metamorphic x qdrant_behavioral_cluster_collection_update_001 (chunk_cluster+collection+update; strategy 6 / G9 - the same invalid peer_id and the same invalid shard_id, submitted through every peer/shard-taking operation variant, must dispose identically: exactly HTTP 400)
Oracle: on an existing collection, all 8 probes - invalid peer 424242 via move_shard/replicate_shard/drop_replica/abort_transfer/restart_transfer, and invalid shard 987654 (peer live-derived) via move_shard/replicate_shard/drop_replica - return exactly HTTP 400; any 2xx is Type1_IllegalSuccess, any 5xx with /healthz alive is Type3, any non-400 rejection class (e.g. 404) is Type4 wrong-disposition, and a split verdict across the family (same invalid value, different disposition classes) is reported as the G9 inconsistency evidence in the defect message

Assertion qdrant_behavioral_cluster_collection_update_001 (evidence_tier=explicit):
  "invalid peer/shard returns 400". The metamorphic relation under test: the
  documented 400 disposition is a property of the INVALID VALUE (peer/shard),
  not of the operation variant that carries it - so every operation variant
  that takes a peer_id/to_peer_id or shard_id must reject the same invalid
  value with the same class. Operation variants and their body fields come
  from the contract cluster+collection+update parameter enum
  (move_shard|replicate_shard|abort_transfer|drop_replica|restart_transfer);
  the peer id used in valid positions is derived live from GET /cluster.

Why this matters (G9): a per-handler disposition split (e.g. drop_replica
404-ing on an invalid peer while move_shard 400-s) means clients cannot rely
on the documented error contract and typo'd peer ids get misclassified as
missing collections - a silent diagnostic divergence the doc round-trip
never surfaces.

All probes reference a peer/shard that cannot exist, so no state is mutated;
the collection under test is disposable and dropped in cleanup.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (collection_cluster = raw_knowledge url
/collections/{collection_name}/cluster; cluster_status / healthz); literal
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
PREFIX = f"s5cu7_{TS}_"
COL = PREFIX + "col"
BAD_PEER = 424242
BAD_SHARD = 987654


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception:
        pass


try:
    # ---- setup + live peer derivation ----
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

    # ---- probe matrix: same invalid value through every peer/shard-taking variant ----
    probes = [
        # family A: invalid peer 424242 (shard valid = 0)
        ("A1 move_shard/to_peer_id=424242", {
            "operation": "move_shard", "shard_id": 0,
            "from_peer_id": peer_id, "to_peer_id": BAD_PEER}),
        ("A2 replicate_shard/to_peer_id=424242", {
            "operation": "replicate_shard", "shard_id": 0,
            "to_peer_id": BAD_PEER}),
        ("A3 drop_replica/peer_id=424242", {
            "operation": "drop_replica", "shard_id": 0,
            "peer_id": BAD_PEER}),
        ("A4 abort_transfer/to_peer_id=424242", {
            "operation": "abort_transfer", "shard_id": 0,
            "from_peer_id": peer_id, "to_peer_id": BAD_PEER}),
        ("A5 restart_transfer/to_peer_id=424242", {
            "operation": "restart_transfer", "shard_id": 0,
            "from_peer_id": peer_id, "to_peer_id": BAD_PEER}),
        # family B: invalid shard 987654 (peer valid = live peer)
        ("B1 move_shard/shard_id=987654", {
            "operation": "move_shard", "shard_id": BAD_SHARD,
            "from_peer_id": peer_id, "to_peer_id": peer_id}),
        ("B2 replicate_shard/shard_id=987654", {
            "operation": "replicate_shard", "shard_id": BAD_SHARD,
            "to_peer_id": peer_id}),
        ("B3 drop_replica/shard_id=987654", {
            "operation": "drop_replica", "shard_id": BAD_SHARD,
            "peer_id": peer_id}),
    ]

    results = {}
    for name, body in probes:
        st, raw = safe_request("POST", "collection_cluster", body,
                               path_params={"name": COL})
        results[name] = st
        print(f"{name}: status={st} raw={raw[:250]}")
        if st == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
            script_error(f"transport failure on {name} (status=0, /healthz={hs}); no defect conclusion")
        if 500 <= st <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[5xx liveness] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                script_error(f"{name}: 5xx status {st} and /healthz not 200 (={hs}); no defect conclusion")
            defect("Type3_RuntimeFailure",
                   f"{name}: assertion documents 400 for invalid peer/shard; got server error {st} "
                   f"while /healthz is 200; raw={raw[:200]}")
        if 200 <= st < 300:
            defect("Type1_IllegalSuccess",
                   f"{name}: assertion promises HTTP 400 for an invalid peer/shard; the op was "
                   f"ACCEPTED with {st}; raw={raw[:200]}")

    # ---- per-probe exact-400 pin + G9 family consistency ----
    non400 = {n: s for n, s in results.items() if s != 400}
    if non400:
        defect("Type4_StateLogicViolation",
               f"assertion pins 400 for invalid peer/shard on every variant; non-400 dispositions: "
               f"{non400} (wrong rejection class / doc drift; family split evidence: statuses="
               f"{sorted(set(results.values()))}); see per-probe raw output above")
    classes = {s // 100 for s in results.values()}
    print(f"all {len(results)} variants disposed 400 uniformly (classes={classes})")

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
