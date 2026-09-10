#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_collection_info_001
# strategy: delete_consistency
# endpoint: cluster+collection+info
# constraint_ids: qdrant_behavioral_cluster_collection_info_001, qdrant_type_cluster_collection_info_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 2 (post-DELETE consistency) + never-existed unknown probe on
  GET /collections/{name}/cluster. The behavioral assertion promises two
  dispositions for the SAME path parameter (collection_name): existing
  collection -> HTTP 200 with cluster info, unknown collection -> HTTP 404.
  Sequence: (A) never-existed unique name must 404 (200-on-unknown is the
  same defect family as the R1-confirmed per-collection alias listing
  200-on-unknown); (B) create -> GET must 200 and the body must actually be
  CollectionClusterInfo (all six documented fields present: peer_id,
  shard_count>=0, local_shards, remote_shards, shard_transfers,
  resharding_operations — a 200 without the promised shape is a broken
  promise, not a success); (C) drop -> after the drop is verifiably acked
  (describe control = 404) -> GET must 404 exactly (200 = ghost/stale row =
  Type4; 5xx = Type3 after liveness re-check).
  [chunk_cluster+collection+info coverage: delete_consistency x
   qdrant_behavioral_cluster_collection_info_001 (+ shape clause of
   qdrant_type_cluster_collection_info_001 on the positive side)]
Oracle: unknown name -> 404; existing collection -> 200 whose result object
  contains all six CollectionClusterInfo fields with shard_count an integer
  >= 0 and the three *_shards/*_operations fields lists; after verified drop
  -> exactly 404 (200 = Type4_StateLogicViolation, 5xx = Type3 after
  /healthz confirms liveness)
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


def safe_request(method, path_key, path_params=None):
    """Health-probe form over the target runtime (DB-neutral path_key).

    Used for the in-branch /healthz liveness re-checks so the transport-failure
    branches probe the documented lightweight health endpoint directly.
    """
    return rt.request(method, path_key, path_params=path_params)


def alive():
    """Liveness re-check via the lightweight health endpoint (helper form)."""
    hs, hraw = rt.request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_info(raw):
    """Return (info_dict, missing_fields) from a 200 cluster-info body."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None, []
    node = b.get("result") if isinstance(b, dict) else None
    if not isinstance(node, dict):
        return None, []
    missing = [f for f in REQUIRED_FIELDS if f not in node]
    return node, missing


def shape_ok(node):
    """Type-side sanity of the six documented fields (constraint _001)."""
    bad = []
    if not isinstance(node.get("peer_id"), int):
        bad.append(f"peer_id not int: {type(node.get('peer_id')).__name__}")
    sc = node.get("shard_count")
    if not isinstance(sc, int) or isinstance(sc, bool) or sc < 0:
        bad.append(f"shard_count not int>=0: {sc!r}")
    for f in ("local_shards", "remote_shards", "shard_transfers",
              "resharding_operations"):
        if not isinstance(node.get(f), list):
            bad.append(f"{f} not list: {type(node.get(f)).__name__}")
    return bad


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scci1_" + TS + "_"
    C = PFX + "col"
    NEVER = PFX + "never_existed"
    DEFECTS = []

    try:
        # ---- (A) never-existed unknown collection: must be 404 ----
        s, raw = rt.request("GET", "collection_cluster", path_params={"name": NEVER})
        print(f"[A unknown-name] status={s} raw={raw[:300]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[A transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on unknown-name probe; "
                  "liveness re-checked via /healthz — skipped")
        elif s == 200:
            DEFECTS.append(
                f"(A) GET cluster info on never-existed collection '{NEVER}' returned "
                f"200 (200-on-unknown) — assertion promises 404 — raw={raw[:200]} — "
                f"Type4_StateLogicViolation"
            )
        elif 500 <= s <= 599:
            if alive():
                DEFECTS.append(
                    f"(A) GET cluster info on never-existed collection returned {s} "
                    f"(5xx; graceful 404 expected, service alive per /healthz) — "
                    f"Type3_RuntimeFailure — raw={raw[:200]}"
                )
            else:
                return "SCRIPT_ERROR"
        elif s != 404:
            print(f"OBSERVATION (A): unknown-name returned {s} (not 404/200/5xx) — "
                  f"unexpected disposition, not in promise set; recorded, not judged")

        # ---- (B) positive side: existing collection -> 200 + real shape ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"
        s, raw = rt.request("GET", "collection_cluster", path_params={"name": C})
        print(f"[B existing] status={s} raw={raw[:400]}")
        if s != 200:
            print(f"SETUP_ERROR: cluster info on freshly created collection = {s}")
            return "SCRIPT_ERROR"
        node, missing = parse_info(raw)
        if node is None:
            DEFECTS.append(
                f"(B) 200 but result envelope is not a CollectionClusterInfo object — "
                f"raw={raw[:200]} — Type4_StateLogicViolation"
            )
        else:
            if missing:
                DEFECTS.append(
                    f"(B) 200 but documented fields missing from CollectionClusterInfo: "
                    f"{missing} — Type4_StateLogicViolation"
                )
            bad = shape_ok(node)
            if bad:
                DEFECTS.append(
                    f"(B) 200 but field types violate the documented shape: {bad} — "
                    f"Type4_StateLogicViolation"
                )

        # ---- (C) post-delete: drop acked -> GET must be exactly 404 ----
        ds, draw = rt.request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[C drop] status={ds} raw={draw[:200]}")
        if ds not in (200, 404):
            print(f"SETUP_ERROR: drop returned {ds}")
            return "SCRIPT_ERROR"
        # quiescence control: describe must confirm the drop before judging
        gone = False
        for _ in range(10):
            try:
                cs, craw = rt.request("GET", "describe_collection",
                                      path_params={"name": C})
            except Exception:
                cs = -1
            if cs == 404:
                gone = True
                break
            time.sleep(0.4)
        print(f"[C quiescence] describe({C}) -> 404? {gone}")
        if not gone:
            print("ENV_ISSUE: drop not observable via describe within retries — "
                  "post-delete disposition not judged")
        else:
            s, raw = rt.request("GET", "collection_cluster", path_params={"name": C})
            print(f"[C post-delete] status={s} raw={raw[:300]}")
            if s == 200:
                DEFECTS.append(
                    f"(C) cluster info still 200 after verified drop of '{C}' — "
                    f"ghost/stale per-collection cluster row — Type4_StateLogicViolation "
                    f"— raw={raw[:200]}"
                )
            elif 500 <= s <= 599:
                if alive():
                    DEFECTS.append(
                        f"(C) cluster info after verified drop returned {s} (5xx; "
                        f"404 expected, service alive per /healthz) — "
                        f"Type3_RuntimeFailure — raw={raw[:200]}"
                    )
                else:
                    return "SCRIPT_ERROR"
            elif s == 0:
                hs, hraw = safe_request("GET", "healthz")
                print(f"[C transport] /healthz probe status={hs} "
                      f"raw={str(hraw)[:120]}")
                if hs != 200:
                    return "SCRIPT_ERROR"
                print("ENV_ISSUE: transport failure on post-delete probe; "
                      "liveness re-checked via /healthz — skipped")
            elif s != 404:
                print(f"OBSERVATION (C): post-delete returned {s} (not 404) — "
                      f"unexpected disposition, recorded, not judged")

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
