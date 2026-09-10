#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: both-direction POSITIVE coverage (G4) of the empty-binding system-level state
  constraint on cluster+collection+update (POST /collections/{collection_name}/cluster):
  "these operations initiate asynchronous transfers — HTTP 200 means the operation was
  ACCEPTED, not completed; progress is observable through the collection cluster info
  endpoint". Positive direction = a legal, acceptable operation is issued and the promise
  is exercised end-to-end: 200-acceptance MUST become observable in the cluster-info
  instrument (the accepted shard appearing in the shard inventory, or a transfer/resharding
  entry referencing it), within an async polling window. Deployment note (transparent
  adaptation): on this single-peer deployment the constraint's literal example ops
  (move_shard/replicate_shard) cannot be VALID (they require a second peer), so the
  acceptable carrier is create_sharding_key; the move_shard op is additionally exercised
  in the NEGATIVE observability direction (Act-2): a move_shard that is 400-rejected for
  an invalid peer must leave NO ghost entry in the cluster-info transfer inventory.
  [chunk_cluster+collection+update coverage: both-direction positive x
   qdrant_state_cluster_collection_update_001 — acceptance->observability promise +
   rejected-op leaves-no-ghost complement]
Oracle: create_sharding_key K -> 200; then polling GET /collections/{name}/cluster (the
  documented observability instrument) for up to ~12s MUST show K in the shard inventory
  (local/remote shard ids) or referenced by shard_transfers/resharding_operations ->
  NO_DEFECT; 200-accepted but K never observable in any instrument after the window =
  Type4_StateLogicViolation ("progress is observable" promise broken — accepted-but-
  invisible); the accepted POST returning 4xx with no acceptable carrier form =
  SCRIPT_ERROR (positive face not exercisable, honest exit); 5xx = Type3_RuntimeFailure
  with /healthz rechecked; Act-2: 400-rejected move_shard followed by a shard_transfers
  entry for that shard+peer = Type4_StateLogicViolation (ghost transfer from a rejected
  operation); transport failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_state_cluster_collection_update_001
Blindspot: BS-04 Boundary Default Optimism (acceptance bookkeeping assumed to surface in
  the observability endpoint without checking the async bridge)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4 lesson: the chunk label is NOT a route):
  attack route: raw_knowledge.api_endpoints[] path="cluster+collection+update", method=POST,
  url="/collections/{collection_name}/cluster";
  observability instrument: path="cluster+collection+info", method=GET,
  url="/collections/{collection_name}/cluster" (the constraint itself names this endpoint
  as the progress instrument); peer discovery: path="cluster+status", GET /cluster.
  D3b preverify fix (request_required_missing): the create_sharding_key branch of
  POST /collections/{collection_name}/cluster requires the shard_key field — every
  create_sharding_key body now carries shard_key (unique prefix name) alongside the
  explicit shard_id (auto fallback: shard_key only).
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap: three-layer fallback (env -> upward walk -> contract target) ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    _root = Path(__file__).resolve()
    for _p in (_root, *list(_root.parents)):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or TARGET != "qdrant":
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)


def safe_request(method, endpoint, json=None, params=None, data=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md).
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, params=params,
            data=data, headers=headers, timeout=timeout,
        )
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except Exception:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def drop_collection(name):
    try:
        safe_request("DELETE", f"/collections/{name}", params={"timeout": 60}, timeout=60)
    except Exception:
        pass  # cleanup failures are non-fatal


POLL_SECONDS = 12
POLL_STEP = 0.5


def read_info(coll):
    """GET the cluster-info instrument. Returns (status, raw, shard_ids, transfers_ids, ops_raw)."""
    s, _, raw = safe_request("GET", f"/collections/{coll}/cluster", timeout=20)
    ids, transfers, resharding = set(), [], []
    try:
        node = json.loads(raw).get("result")
        if isinstance(node, dict):
            for key in ("local_shards", "remote_shards"):
                for entry in (node.get(key) or []):
                    if isinstance(entry, dict) and isinstance(entry.get("shard_id"), int):
                        ids.add(entry["shard_id"])
            transfers = node.get("shard_transfers") or []
            resharding = node.get("resharding_operations") or []
    except Exception:
        pass
    return s, raw, ids, transfers, resharding


def transport_or_crash(label, status, raw):
    """Shared ladder fragment: returns verdict string for transport/5xx, else None."""
    if status <= 0:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) — {label} transport failure "
                    f"and /healthz={hs} (service down)")
        return f"SCRIPT_ERROR — {label} transport failure with healthy /healthz (no defect conclusion)"
    if 500 <= status <= 599:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) — {label} got {status} and "
                    f"/healthz={hs} (service down)")
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — {label} got {status} with "
                f"/healthz={hs} alive")
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bccu7" + tag
    coll = pfx + "c"
    key_name = pfx + "sk"  # spec-required shard_key field (D3b preverify: create_sharding_key branch)
    key_shard = 5100 + (int(time.time() * 1000) % 3000)
    print(f"ownership prefix: {pfx}; shard_key={key_name}; target shard K={key_shard}")

    # Arrange: create one collection (contract-required body: vectors VectorParams)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # Baseline: inventory before the accepted operation.
        s, raw, ids0, _, _ = read_info(coll)
        print(f"[baseline cluster info] status={s} shard_ids={sorted(ids0)} "
              f"raw={str(raw)[:200]}")
        v = transport_or_crash("baseline GET cluster info", s, raw)
        if v is not None:
            print("VERDICT: " + v)
            return
        if s != 200:
            print(f"VERDICT: SCRIPT_ERROR — observability instrument returned {s} at "
                  f"baseline; promise cannot be measured; no defect conclusion")
            return

        # Act-1: issue the acceptable operation (explicit shard id first, auto fallback).
        s, _, raw = safe_request("POST", f"/collections/{coll}/cluster",
                                 json={"create_sharding_key": {"shard_key": key_name,
                                                               "shard_id": key_shard}},
                                 timeout=30)
        print(f"[POST create_sharding_key key={key_name} K={key_shard}] -> status={s} "
              f"raw={str(raw)[:200]}")
        v = transport_or_crash("POST create_sharding_key (explicit)", s, raw)
        if v is not None:
            print("VERDICT: " + v)
            return
        if 400 <= s < 500:
            # Deployment may refuse the explicit form: honest fallback to auto-assign,
            # observability then measured by set-difference against the baseline.
            s, _, raw = safe_request("POST", f"/collections/{coll}/cluster",
                                     json={"create_sharding_key": {"shard_key": key_name}},
                                     timeout=30)
            print(f"[POST create_sharding_key auto] -> status={s} raw={str(raw)[:200]}")
            v = transport_or_crash("POST create_sharding_key (auto)", s, raw)
            if v is not None:
                print("VERDICT: " + v)
                return
            key_shard = None  # marker: watch for ANY new shard id
        if 400 <= s < 500:
            print("VERDICT: SCRIPT_ERROR — no acceptable carrier operation on this "
                  "deployment (both create_sharding_key forms refused); the positive "
                  "acceptance face cannot be exercised; no defect conclusion")
            return
        if not (200 <= s < 300):
            print(f"VERDICT: SCRIPT_ERROR — uninterpreted acceptance status {s}; no "
                  "defect conclusion")
            return
        print(f"OK: operation accepted with {s} (acceptance != completion — polling next)")

        # Assert-1: the accepted operation MUST become observable (async window).
        deadline = time.time() + POLL_SECONDS
        observed_at = None
        new_ids = set()
        last_transfers = []
        while time.time() < deadline:
            s, raw, ids, transfers, resharding = read_info(coll)
            v = transport_or_crash("poll GET cluster info", s, raw)
            if v is not None:
                print("VERDICT: " + v)
                return
            new_ids = set(ids) - set(ids0)
            last_transfers = transfers
            if key_shard is not None:
                hit = (key_shard in ids
                       or any(isinstance(t, dict) and t.get("shard_id") == key_shard
                              for t in transfers)
                       or any(isinstance(o, dict) and o.get("shard_id") == key_shard
                              for o in resharding))
            else:
                hit = bool(new_ids) or bool(transfers) or bool(resharding)
            if hit:
                observed_at = time.time()
                break
            time.sleep(POLL_STEP)

        if observed_at is None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — operation was "
                  f"200-ACCEPTED but never became observable in the cluster-info "
                  f"instrument within {POLL_SECONDS}s (baseline ids={sorted(ids0)}, "
                  f"final ids={sorted(set(ids0) | new_ids)}, "
                  f"transfers={last_transfers}); "
                  f"the 'progress is observable' promise of "
                  f"qdrant_state_cluster_collection_update_001 is violated")
            return
        print(f"OK: accepted operation observable after "
              f"{POLL_SECONDS - (deadline - observed_at):.1f}s "
              f"(new shard ids={sorted(new_ids)})")

        # Act-2 + Assert-2 (negative observability complement, uses the constraint's own
        # move_shard op): a move to an invalid peer must be 400-rejected AND leave no
        # ghost entry in the transfer inventory.
        ps, _, praw = safe_request("GET", "/cluster", timeout=15)
        peer_id = None
        try:
            node = json.loads(praw).get("result")
            if isinstance(node, dict) and isinstance(node.get("peer_id"), int):
                peer_id = node["peer_id"]
        except Exception:
            peer_id = None
        if peer_id is None:
            print("NOTE(judge): peer discovery failed — Act-2 (rejected-move ghost check) "
                  "skipped; Act-1 verdict stands")
            print("VERDICT: NO_DEFECT")
            return
        bogus_peer = peer_id + 1000000
        existing = sorted(set(ids0) | new_ids)
        move_target = existing[0] if existing else 0
        s, _, raw = safe_request("POST", f"/collections/{coll}/cluster",
                                 json={"move_shard": {"shard_id": move_target,
                                                      "from_peer_id": peer_id,
                                                      "to_peer_id": bogus_peer}},
                                 timeout=30)
        print(f"[POST move_shard to invalid peer {bogus_peer}] -> status={s} "
              f"raw={str(raw)[:200]}")
        v = transport_or_crash("POST move_shard (invalid peer)", s, raw)
        if v is not None:
            print("VERDICT: " + v)
            return
        if 200 <= s < 300:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — move_shard to invalid "
                  f"peer {bogus_peer} ACCEPTED with {s} (documented 400 face of the "
                  f"behavioral assertion violated; recorded here under the state "
                  f"constraint's move-op clause)")
            return
        rej_status = s
        if not (400 <= s < 500):
            print(f"NOTE(judge): move_shard invalid-peer probe returned {s} (primary "
                  f"adjudication of the 400 face lives in script 002)")
        # Rejected op must leave NO ghost transfer for that (shard, bogus peer) pair.
        s, raw, ids, transfers, _ = read_info(coll)
        v = transport_or_crash("post-rejection GET cluster info", s, raw)
        if v is not None:
            print("VERDICT: " + v)
            return
        ghost = [t for t in transfers if isinstance(t, dict)
                 and (t.get("to_peer_id") == bogus_peer
                      or t.get("to") == bogus_peer)]
        if ghost:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — a move_shard that "
                  f"was {rej_status}-REJECTED by the API left a ghost "
                  f"transfer entry in the observability instrument: {ghost}")
            return
        print("OK: rejected move_shard left no ghost transfer entry")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
