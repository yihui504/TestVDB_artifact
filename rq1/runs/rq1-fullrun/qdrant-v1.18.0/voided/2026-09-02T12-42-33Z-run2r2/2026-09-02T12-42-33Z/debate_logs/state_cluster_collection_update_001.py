#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_collection_update_001
# strategy: delete_consistency
# endpoint: cluster+collection+update
# constraint_ids: qdrant_behavioral_cluster_collection_update_001, qdrant_state_cluster_collection_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 2 (post-DELETE consistency) + Pattern C (broken dependency
  chain) on POST /collections/{name}/cluster (cluster+collection+update; URL
  from raw_knowledge api_endpoints[].url). The behavioral assertion promises
  three dispositions: valid op -> 200 accepted, invalid peer/shard -> 400,
  missing collection -> 404. Sequence: (A) POST a move_shard op referencing
  ghost peers against a never-existed collection name -> must be exactly 404
  (2xx = accepted op on a collection that never existed = ghost state,
  5xx = Type3 after liveness); (B) contrast face: identical op on an existing
  collection must NOT 404 (invalid peers are documented to 400; 2xx there =
  Type1_IllegalSuccess — accepting an unachievable transfer); (C) drop the
  collection, ack the drop via describe=404 quiescence control, replay the
  same POST -> must be exactly 404 again (2xx = stale/ghost cluster state).
  [chunk_cluster+collection+update coverage: delete_consistency x
   qdrant_behavioral_cluster_collection_update_001 (404 leg + existing-face
   contrast) + dependency-chain leg of qdrant_state_cluster_collection_update_001]
Oracle: cluster op on never-existed and on verified-dropped collection ->
  HTTP 404 exactly (2xx = Type4_StateLogicViolation, 5xx = Type3 only after
  /healthz confirms liveness); existing collection + ghost-peer move_shard ->
  non-404 rejection (400 documented); 2xx there = Type1_IllegalSuccess
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


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; kept in this exact call form so the
    inline liveness probes (GET healthz) stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def cluster_op(name, op_body):
    """POST /collections/{name}/cluster — the chunk's endpoint face."""
    return safe_request("POST", "collection_cluster",
                        path_params={"name": name}, body=op_body)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccu1_" + TS + "_"
    C = PFX + "col"
    NEVER = PFX + "never_existed"
    DEFECTS = []
    # Ghost peer ids derived at runtime when possible; fallback ids are far
    # outside the small-uint peer-id space of a lab deployment.
    GHOST_A, GHOST_B = 987654, 987655
    OP = {"move_shard": {"shard_id": 0, "to_peer_id": GHOST_A,
                         "from_peer_id": GHOST_B}}

    try:
        # ---- (A) never-existed collection: cluster op must 404 ----
        s, raw = cluster_op(NEVER, OP)
        print(f"[A never-existed] status={s} raw={raw[:300]}")
        if 200 <= s < 300:
            DEFECTS.append(
                f"(A) cluster op on never-existed collection '{NEVER}' returned "
                f"{s} (2xx) — assertion promises 404 for missing collection — "
                f"accepted op against ghost state — Type4_StateLogicViolation — "
                f"raw={raw[:200]}"
            )
        elif 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[A liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(A) cluster op on never-existed collection returned {s} (5xx; "
                f"404 expected, service alive per /healthz) — "
                f"Type3_RuntimeFailure — raw={raw[:200]}"
            )
        elif s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[A transport] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on (A); liveness ok — skipped")
        elif s != 404:
            print(f"OBSERVATION (A): never-existed face returned {s} (not 404) — "
                  f"disposition outside promise set, recorded, not judged")

        # ---- (B) contrast face: existing collection must NOT 404 ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"
        s, raw = cluster_op(C, OP)
        print(f"[B existing] status={s} raw={raw[:300]}")
        if 200 <= s < 300:
            DEFECTS.append(
                f"(B) move_shard to ghost peer {GHOST_A} on existing collection "
                f"returned {s} (2xx) — assertion promises 400 for invalid peer — "
                f"unachievable transfer accepted into the cluster state machine — "
                f"Type1_IllegalSuccess — raw={raw[:200]}"
            )
        elif 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[B liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(B) move_shard ghost-peer on existing collection returned {s} "
                f"(5xx; 400 expected, service alive per /healthz) — "
                f"Type3_RuntimeFailure — raw={raw[:200]}"
            )
        elif s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[B transport] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on (B); liveness ok — skipped")
        elif s == 404:
            print(f"OBSERVATION (B): existing-collection face returned 404 "
                  f"(documented disposition for this face is 400) — "
                  f"same param different face, recorded, not judged")
        else:
            print(f"[B] existing-collection face rejected with {s} (4xx family) "
                  f"— contrast established: missing->404 vs invalid-peer->4xx")

        # ---- (C) post-delete: acked drop -> cluster op must 404 again ----
        ds, draw = safe_request("DELETE", "drop_collection",
                                path_params={"name": C})
        print(f"[C drop] status={ds} raw={draw[:200]}")
        if ds not in (200, 404):
            print(f"SETUP_ERROR: drop returned {ds}")
            return "SCRIPT_ERROR"
        gone = False
        for _ in range(10):
            try:
                cs, craw = safe_request("GET", "describe_collection",
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
            s, raw = cluster_op(C, OP)
            print(f"[C post-delete] status={s} raw={raw[:300]}")
            if 200 <= s < 300:
                DEFECTS.append(
                    f"(C) cluster op still {s} (2xx) after verified drop of "
                    f"'{C}' — stale/ghost per-collection cluster state — "
                    f"Type4_StateLogicViolation — raw={raw[:200]}"
                )
            elif 500 <= s <= 599:
                hs, hraw = safe_request("GET", "healthz")
                print(f"[C liveness] healthz status={hs} raw={str(hraw)[:120]}")
                if hs != 200:
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(C) cluster op after verified drop returned {s} (5xx; "
                    f"404 expected, service alive per /healthz) — "
                    f"Type3_RuntimeFailure — raw={raw[:200]}"
                )
            elif s == 0:
                hs, hraw = safe_request("GET", "healthz")
                print(f"[C transport] healthz status={hs} raw={str(hraw)[:120]}")
                if hs != 200:
                    return "SCRIPT_ERROR"
                print("ENV_ISSUE: transport failure on (C); liveness ok — skipped")
            elif s != 404:
                print(f"OBSERVATION (C): post-delete face returned {s} "
                      f"(not 404) — disposition outside promise set, "
                      f"recorded, not judged")

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
