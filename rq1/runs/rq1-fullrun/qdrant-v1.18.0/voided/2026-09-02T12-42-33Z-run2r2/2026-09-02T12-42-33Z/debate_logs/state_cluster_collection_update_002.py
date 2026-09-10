#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_collection_update_002
# strategy: count_consistency
# endpoint: cluster+collection+update
# constraint_ids: qdrant_behavioral_cluster_collection_update_001, qdrant_state_cluster_collection_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Invalid peer/shard rejection matrix on POST
  /collections/{name}/cluster (cluster+collection+update; URL from
  raw_knowledge api_endpoints[].url). The behavioral assertion promises
  "400 on an invalid peer/shard"; the state constraint promises that only
  accepted (200) operations surface in collection cluster info
  (shard_transfers). Mutation justification (G6): ghost peer/shard ids are
  the strongest breaker of the 400 promise — a 2xx would mean the transfer
  queue accepted an operation that can never execute (state pollution),
  directly observable as a non-empty shard_transfers afterwards. Battery
  covers the operation enum's transfer-shaped members: move_shard (ghost
  to_peer / ghost shard_id), replicate_shard (ghost peer), drop_replica
  (ghost peer), abort_transfer / restart_transfer (unknown transfer),
  start_resharding (ghost peer), abort_resharding (ghost shard).
  Reconciliation: after the battery, cluster info must still be 200, the
  documented CollectionClusterInfo shape, shard_count unchanged and
  shard_transfers empty (no pollution from rejected ops).
  [chunk_cluster+collection+update coverage: count_consistency x
   qdrant_behavioral_cluster_collection_update_001 (400 leg, op matrix) +
   qdrant_state_cluster_collection_update_001 (negative observability:
   rejected ops must not appear in shard_transfers)]
Oracle: every ghost-peer/ghost-shard op -> 4xx rejection (400 documented;
  2xx = Type1_IllegalSuccess, 5xx = Type3 only after /healthz liveness);
  afterwards GET /collections/{name}/cluster -> 200 with the six documented
  fields, shard_count == pre-battery value and shard_transfers == []
  (non-empty/polluted or missing info = Type4_StateLogicViolation)
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

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
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

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

REQUIRED_FIELDS = ("peer_id", "shard_count", "local_shards", "remote_shards",
                   "shard_transfers", "resharding_operations")


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; kept in this exact call form so the
    inline liveness probes (GET healthz) stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def jload(raw):
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def result_node(raw):
    b = jload(raw)
    r = b.get("result") if isinstance(b, dict) else None
    return r if isinstance(r, dict) else None


def discover_ids():
    """Derive local peer id + peers map from GET /cluster (URL from
    raw_knowledge cluster+status); ghost ids stay outside the map."""
    s, raw = safe_request("GET", "cluster_status")
    if s != 200:
        return None, None, None
    res = result_node(raw)
    if res is None:
        return None, None, None
    peers = res.get("peers")
    ids = set()
    if isinstance(peers, dict):
        for k in peers.keys():
            if str(k).lstrip("-").isdigit():
                ids.add(int(k))
    elif isinstance(peers, list):
        for p in peers:
            if isinstance(p, dict) and isinstance(p.get("peer_id"), int):
                ids.add(p["peer_id"])
    local = res.get("peer_id") if isinstance(res.get("peer_id"), int) else None
    if local is None and ids:
        local = max(ids)
    ghost = (max(ids) + 1000) if ids else 987654
    return local, ids, ghost


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccu2_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    try:
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"

        local_peer, peer_ids, ghost_peer = discover_ids()
        if local_peer is None:
            local_peer, ghost_peer = 987655, 987654
            print(f"[ids] cluster_status unparseable — fallback local={local_peer} "
                  f"ghost={ghost_peer}")
        else:
            print(f"[ids] local_peer={local_peer} peers={sorted(peer_ids)} "
                  f"ghost={ghost_peer}")
        if ghost_peer == local_peer:
            ghost_peer = local_peer + 1000

        # local shard id from cluster info (default 0 on empty local_shards)
        ls, lraw = safe_request("GET", "collection_cluster",
                                path_params={"name": C})
        if ls != 200:
            print(f"SETUP_ERROR: baseline cluster info status={ls} raw={lraw[:200]}")
            return "SCRIPT_ERROR"
        node = result_node(lraw)
        missing = [f for f in REQUIRED_FIELDS if not isinstance(node, dict)
                   or f not in node] if isinstance(node, dict) else list(REQUIRED_FIELDS)
        if missing:
            DEFECTS.append(
                f"(baseline) 200 but CollectionClusterInfo fields missing: "
                f"{missing} — Type4_StateLogicViolation — raw={lraw[:200]}"
            )
        local_shard = 0
        try:
            shards_l = node.get("local_shards") or []
            if shards_l and isinstance(shards_l[0], dict) \
                    and isinstance(shards_l[0].get("shard_id"), int):
                local_shard = shards_l[0]["shard_id"]
        except Exception:
            pass
        ghost_shard = local_shard + 9000
        base_count = node.get("shard_count") if isinstance(node, dict) else None
        print(f"[baseline] local_shard={local_shard} ghost_shard={ghost_shard} "
              f"shard_count={base_count}")

        battery = [
            ("move_shard:ghost_to_peer",
             {"move_shard": {"shard_id": local_shard, "to_peer_id": ghost_peer,
                             "from_peer_id": local_peer}}),
            ("move_shard:ghost_shard",
             {"move_shard": {"shard_id": ghost_shard, "to_peer_id": local_peer,
                             "from_peer_id": local_peer}}),
            ("replicate_shard:ghost_peer",
             {"replicate_shard": {"shard_id": local_shard,
                                  "to_peer_id": ghost_peer,
                                  "from_peer_id": local_peer}}),
            ("drop_replica:ghost_peer",
             {"drop_replica": {"shard_id": local_shard, "peer_id": ghost_peer}}),
            ("abort_transfer:unknown",
             {"abort_transfer": {"shard_id": ghost_shard,
                                 "to_peer_id": ghost_peer,
                                 "from_peer_id": local_peer}}),
            ("restart_transfer:unknown",
             {"restart_transfer": {"shard_id": ghost_shard,
                                   "to_peer_id": ghost_peer,
                                   "from_peer_id": local_peer}}),
            ("start_resharding:ghost_peer",
             {"start_resharding": {"peer_id": ghost_peer,
                                   "shard_id": ghost_shard}}),
            ("abort_resharding:ghost_shard",
             {"abort_resharding": {"shard_id": ghost_shard}}),
        ]

        any_accepted = False
        for label, op in battery:
            s, raw = safe_request("POST", "collection_cluster",
                                  path_params={"name": C}, body=op)
            print(f"[op {label}] status={s} raw={raw[:240]}")
            if 200 <= s < 300:
                any_accepted = True
                DEFECTS.append(
                    f"(op {label}) returned {s} (2xx) — assertion promises 400 "
                    f"for invalid peer/shard — unachievable operation accepted — "
                    f"Type1_IllegalSuccess — raw={raw[:200]}"
                )
            elif 500 <= s <= 599:
                hs, hraw = safe_request("GET", "healthz")
                print(f"[op {label} liveness] healthz status={hs} "
                      f"raw={str(hraw)[:120]}")
                if hs != 200:
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(op {label}) returned {s} (5xx; 400 expected, service "
                    f"alive per /healthz) — Type3_RuntimeFailure — "
                    f"raw={raw[:200]}"
                )
            elif s == 0:
                hs, hraw = safe_request("GET", "healthz")
                print(f"[op {label} transport] healthz status={hs} "
                      f"raw={str(hraw)[:120]}")
                if hs != 200:
                    return "SCRIPT_ERROR"
                print(f"ENV_ISSUE: transport failure on op {label} — skipped")
            # 4xx = documented rejection (400 expected; other 4xx recorded only)
            elif s != 400:
                print(f"OBSERVATION (op {label}): rejected with {s} "
                      f"(documented code is 400) — clear rejection, not judged")

        # ---- reconciliation: rejected ops must leave cluster info clean ----
        time.sleep(1.0)
        s, raw = safe_request("GET", "collection_cluster",
                              path_params={"name": C})
        print(f"[reconcile] status={s} raw={raw[:400]}")
        if s == 404:
            DEFECTS.append(
                f"(reconcile) cluster info 404 on live collection '{C}' after "
                f"rejected-op battery — collection state lost — "
                f"Type4_StateLogicViolation — raw={raw[:200]}"
            )
        elif 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[reconcile liveness] healthz status={hs} "
                  f"raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(reconcile) cluster info {s} (5xx; 200 expected, service "
                f"alive per /healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
            )
        elif s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[reconcile transport] healthz status={hs} "
                  f"raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on reconcile — skipped")
        elif s == 200:
            node2 = result_node(raw)
            if not isinstance(node2, dict):
                DEFECTS.append(
                    f"(reconcile) 200 but result envelope is not "
                    f"CollectionClusterInfo — raw={raw[:200]} — "
                    f"Type4_StateLogicViolation"
                )
            else:
                transfers = node2.get("shard_transfers")
                if not isinstance(transfers, list) or transfers:
                    DEFECTS.append(
                        f"(reconcile) shard_transfers polluted after battery: "
                        f"{transfers!r} (accepted={any_accepted}) — "
                        f"Type4_StateLogicViolation"
                    )
                cnt = node2.get("shard_count")
                if isinstance(base_count, int) and isinstance(cnt, int) \
                        and cnt != base_count:
                    DEFECTS.append(
                        f"(reconcile) shard_count changed from {base_count} to "
                        f"{cnt} although every op was rejected — "
                        f"Type4_StateLogicViolation"
                    )

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
