#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_collection_info_002
# strategy: count_consistency
# endpoint: cluster+collection+info
# constraint_ids: qdrant_type_cluster_collection_info_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 (CRUD-then-COUNT consistency, cross-face variant) on the
  CollectionClusterInfo report of GET /collections/{name}/cluster. The type
  constraint promises the 200 body carries peer_id, shard_count (>= 0),
  local_shards, remote_shards, shard_transfers, resharding_operations. A
  state-consistency report is only useful if it RECONCILES with the state it
  reports on, so three reconciliations are checked: (1) shard_count must
  equal the configured shard number on the describe face
  (result.config.params.shard_number) of the same collection; (2) every
  shard must be observable in the report — shard_count must equal the count
  of distinct shard ids across local_shards+remote_shards (a shard that
  exists per config but appears in neither list is an unreported shard);
  (3) the point-count face: after inserting N points with wait=true, sum of
  points_count over local_shards entries must equal N and equal the count
  endpoint's exact count; after deleting all points, both faces must report
  0. Shape completeness is re-checked after each mutation (positive =
  plain 200 shape; negative = state churn must not degrade the shape).
  peer_id is cross-checked against GET /cluster.
  [chunk_cluster+collection+info coverage: count_consistency x
   qdrant_type_cluster_collection_info_001]
Oracle: cluster info shard_count == describe config.params.shard_number ==
  distinct shard ids across local_shards+remote_shards; sum(local_shards
  points_count) == exact count == N after insert and == 0 after delete-all;
  all six fields present and well-typed on every 200 (mismatch or missing =
  Type4_StateLogicViolation)
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
N_POINTS = 25
DIM = 4
REQ_SHARDS = 3


def alive():
    hs, hraw = rt.request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def get_info(name):
    """GET cluster info -> (status, info_dict_or_None, missing, type_bad, raw)."""
    s, raw = rt.request("GET", "collection_cluster", path_params={"name": name})
    if s != 200:
        return s, None, [], [], raw
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, [], ["unparseable-200-body"], raw
    node = b.get("result") if isinstance(b, dict) else None
    if not isinstance(node, dict):
        return s, None, [], ["result-not-object"], raw
    missing = [f for f in REQUIRED_FIELDS if f not in node]
    bad = []
    if not isinstance(node.get("peer_id"), int) or isinstance(node.get("peer_id"), bool):
        bad.append("peer_id not int")
    sc = node.get("shard_count")
    if not isinstance(sc, int) or isinstance(sc, bool) or sc < 0:
        bad.append(f"shard_count not int>=0: {sc!r}")
    for f in ("local_shards", "remote_shards", "shard_transfers",
              "resharding_operations"):
        if not isinstance(node.get(f), list):
            bad.append(f"{f} not list")
    return s, node, missing, bad, raw


def shard_ids(node):
    """Distinct shard ids observable in the report (local + remote faces)."""
    ids = set()
    for f in ("local_shards", "remote_shards"):
        for e in node.get(f, []) or []:
            if isinstance(e, dict) and "shard_id" in e:
                ids.add(e["shard_id"])
    return ids


def local_points_sum(node):
    """Sum per-local-shard point counts; (None, reason) if field not observable."""
    total, seen = 0, 0
    for e in node.get("local_shards", []) or []:
        if isinstance(e, dict) and "points_count" in e:
            v = e["points_count"]
            if isinstance(v, int) and not isinstance(v, bool):
                total += v
                seen += 1
    if not node.get("local_shards") or seen == 0:
        return None, "no local_shards entry exposes points_count"
    return total, ""


def count_face(name):
    """Exact count via the count endpoint -> (status, count_or_None, raw)."""
    s, raw = rt.request("POST", "count", {"exact": True},
                        path_params={"name": name})
    if s != 200:
        return s, None, raw
    try:
        b = json.loads(raw)
        c = b.get("result", {}).get("count")
        return s, c, raw
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return s, None, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scci2_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    try:
        # ---- setup: explicit multi-shard collection ----
        s, raw = rt.request("PUT", "create_collection", {
            "vectors": {"size": DIM, "distance": "Cosine"},
            "shard_number": REQ_SHARDS,
        }, path_params={"name": C})
        print(f"[create sharded] status={s} raw={raw[:200]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"

        # ---- (1)+(2) shard topology reconciliation ----
        ds, draw = rt.request("GET", "describe_collection", path_params={"name": C})
        cfg_shards = None
        if ds == 200:
            try:
                b = json.loads(draw)
                cfg_shards = b["result"]["config"]["params"]["shard_number"]
            except (json.JSONDecodeError, ValueError, TypeError, KeyError,
                    AttributeError, IndexError):
                cfg_shards = None
        print(f"[describe] status={ds} config.params.shard_number={cfg_shards}")

        s, node, missing, bad, raw = get_info(C)
        print(f"[info] status={s} raw={raw[:400]}")
        if s != 200 or node is None:
            if s == 0 or 500 <= s <= 599:
                if not alive():
                    return "SCRIPT_ERROR"
            return "SCRIPT_ERROR"
        if missing:
            DEFECTS.append(f"documented fields missing: {missing} — Type4_StateLogicViolation")
        if bad:
            DEFECTS.append(f"field type violations: {bad} — Type4_StateLogicViolation")

        sc = node.get("shard_count")
        obs_ids = shard_ids(node)
        print(f"[topology] shard_count={sc} observed shard ids={sorted(obs_ids)} "
              f"local={len(node.get('local_shards') or [])} "
              f"remote={len(node.get('remote_shards') or [])}")
        if isinstance(sc, int):
            if cfg_shards is not None and sc != cfg_shards:
                DEFECTS.append(
                    f"shard_count={sc} disagrees with describe face "
                    f"config.params.shard_number={cfg_shards} — Type4_StateLogicViolation"
                )
            if sc != len(obs_ids):
                DEFECTS.append(
                    f"shard_count={sc} but only {len(obs_ids)} distinct shard ids "
                    f"observable across local+remote shards {sorted(obs_ids)} — "
                    f"unreported/unallocated shards — Type4_StateLogicViolation"
                )

        # ---- peer_id cross-face vs GET /cluster ----
        ks, kraw = rt.request("GET", "cluster_status")
        if ks == 200:
            try:
                kb = json.loads(kraw)
                kpeer = kb.get("result", {}).get("peer_id")
                if isinstance(kpeer, int) and node.get("peer_id") != kpeer:
                    DEFECTS.append(
                        f"collection cluster info peer_id={node.get('peer_id')!r} "
                        f"disagrees with /cluster peer_id={kpeer!r} — "
                        f"Type4_StateLogicViolation"
                    )
            except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
                print("OBSERVATION: /cluster body unparseable — peer cross-check skipped")
        else:
            print(f"OBSERVATION: /cluster status={ks} — peer cross-check skipped")

        # ---- (3) points-count reconciliation: insert N ----
        pts = [{"id": i, "vector": [0.1 * (i % 5) + 0.01, 0.2, 0.3, 0.4]}
               for i in range(N_POINTS)]
        us, uraw = rt.request("PUT", "upsert_points", {"points": pts},
                              path_params={"name": C}, query_params={"wait": "true"})
        print(f"[upsert {N_POINTS}] status={us} raw={uraw[:200]}")
        if us not in (200, 201):
            return "SCRIPT_ERROR"
        cs, cval, craw = count_face(C)
        print(f"[count face] status={cs} count={cval} raw={craw[:200]}")
        if cs != 200 or not isinstance(cval, int):
            return "SCRIPT_ERROR"
        if cval != N_POINTS:
            DEFECTS.append(
                f"count face reports {cval} after wait=true upsert of {N_POINTS} — "
                f"Type4_StateLogicViolation"
            )
        s2, node2, missing2, bad2, raw2 = get_info(C)
        if s2 != 200 or node2 is None:
            return "SCRIPT_ERROR"
        if missing2 or bad2:
            DEFECTS.append(
                f"shape degraded after insert (missing={missing2} bad={bad2}) — "
                f"Type4_StateLogicViolation"
            )
        lsum, why = local_points_sum(node2)
        print(f"[info after insert] local points sum={lsum} ({why or 'ok'})")
        if lsum is not None and lsum != N_POINTS:
            DEFECTS.append(
                f"cluster info local_shards points_count sums to {lsum} but "
                f"{N_POINTS} points are committed (count face={cval}) — "
                f"Type4_StateLogicViolation"
            )
        elif lsum is None:
            print(f"OBSERVATION: {why} — points_count cross-check skipped")

        # ---- (3b) negative side: delete all -> both faces must be 0 ----
        dls, dlraw = rt.request("POST", "delete_points",
                                {"points": list(range(N_POINTS))},
                                path_params={"name": C},
                                query_params={"wait": "true"})
        print(f"[delete all] status={dls} raw={dlraw[:200]}")
        if dls not in (200, 201):
            return "SCRIPT_ERROR"
        cs0, cval0, craw0 = count_face(C)
        print(f"[count face after delete] status={cs0} count={cval0}")
        if cs0 == 200 and cval0 != 0:
            DEFECTS.append(
                f"count face reports {cval0} after wait=true delete of all points — "
                f"Type4_StateLogicViolation"
            )
        s3, node3, missing3, bad3, raw3 = get_info(C)
        if s3 != 200 or node3 is None:
            return "SCRIPT_ERROR"
        if missing3 or bad3:
            DEFECTS.append(
                f"shape degraded after delete (missing={missing3} bad={bad3}) — "
                f"Type4_StateLogicViolation"
            )
        lsum0, why0 = local_points_sum(node3)
        print(f"[info after delete] local points sum={lsum0} ({why0 or 'ok'})")
        if lsum0 is not None and lsum0 != 0:
            DEFECTS.append(
                f"cluster info local_shards points_count sums to {lsum0} after all "
                f"points deleted (count face={cval0}) — Type4_StateLogicViolation"
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
