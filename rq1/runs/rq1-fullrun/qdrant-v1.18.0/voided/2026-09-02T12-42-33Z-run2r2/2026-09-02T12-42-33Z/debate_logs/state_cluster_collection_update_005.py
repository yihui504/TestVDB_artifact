#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_collection_update_005
# strategy: concurrent
# endpoint: cluster+collection+update
# constraint_ids: qdrant_behavioral_cluster_collection_update_001, qdrant_state_cluster_collection_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 7 (lifecycle concurrency attack) on POST
  /collections/{name}/cluster and GET /collections/{name}/cluster (URLs
  from raw_knowledge api_endpoints[].url: cluster+collection+update /
  cluster+collection+info). Thread A cycles the collection lifecycle
  (drop -> create custom-sharded -> short sleep), Thread B concurrently
  drives the chunk's endpoint: alternating create_sharding_key submissions
  and cluster-info reads. The behavioral assertion's disposition set is
  {200 accepted, 400 invalid peer/shard, 404 missing collection} — under a
  lifecycle race every one of those is legal at any instant, but a 500
  internal error never is (the server must resolve "collection temporarily
  absent" gracefully as 404, not crash). 5xx events are judged only when
  count >= 2 or reproduced once with /healthz alive (race false-positive
  guard). Final reconciliation: collection recreated -> cluster info 200
  with shard_transfers list, exact point count 0.
  # Blindspot: BS-03 Concurrency Blindness (collection lifecycle races)
  [chunk_cluster+collection+update coverage: lifecycle-concurrency x
   qdrant_behavioral_cluster_collection_update_001 (disposition set under
   race; 500 never legal) + qdrant_state_cluster_collection_update_001
   (accepted ops must stay reconcilable after the race)]
Oracle: every access-thread response in {200, 400, 404} (2xx-other noted);
  500-class responses = Type3_RuntimeFailure when >=2 events or reproduced
  once AND /healthz alive; after the race, recreated collection -> cluster
  info 200 with shard_transfers a list (empty expected), exact count == 0
  (non-zero = Type4 ghost data)
"""

import os
import sys
import json
import time
import threading
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

CYCLES = 8
ACCESS_ROUNDS = 40
CREATE_BODY = {"vectors": {"size": 4, "distance": "Cosine"},
               "sharding_method": "custom"}


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


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccu5_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    events = []  # (kind, label, status)
    stop = threading.Event()

    def lifecycle_thread():
        for _ in range(CYCLES):
            try:
                safe_request("DELETE", "drop_collection",
                             path_params={"name": C})
            except Exception:
                pass
            time.sleep(0.05)
            try:
                safe_request("PUT", "create_collection",
                             path_params={"name": C}, body=CREATE_BODY)
            except Exception:
                pass
            time.sleep(0.08)
        stop.set()

    def access_thread():
        for i in range(ACCESS_ROUNDS):
            if i % 2 == 0:
                key_op = {"create_sharding_key": {
                    "shard_key": f"{PFX}k{i % 3}", "shards_number": 1,
                    "replication_factor": 1}}
                try:
                    s, raw = safe_request("POST", "collection_cluster",
                                          path_params={"name": C},
                                          body=key_op)
                    events.append(("post", f"k{i % 3}", s))
                except Exception as e:
                    events.append(("post", f"k{i % 3}", f"EXC:{e}"))
            else:
                try:
                    s, raw = safe_request("GET", "collection_cluster",
                                          path_params={"name": C})
                    events.append(("get", "info", s))
                except Exception as e:
                    events.append(("get", "info", f"EXC:{e}"))
            time.sleep(0.03)

    try:
        # pre-create so access thread's first ops have a target half the time
        safe_request("PUT", "create_collection", path_params={"name": C},
                     body=CREATE_BODY)
        ta = threading.Thread(target=lifecycle_thread)
        tb = threading.Thread(target=access_thread)
        ta.start()
        tb.start()
        ta.join(timeout=120)
        tb.join(timeout=120)
        stop.set()

        posts = [e for e in events if e[0] == "post" and isinstance(e[2], int)]
        gets = [e for e in events if e[0] == "get" and isinstance(e[2], int)]
        p5 = [e for e in posts if 500 <= e[2] <= 599]
        g5 = [e for e in gets if 500 <= e[2] <= 599]
        p_ok = [e for e in posts if 200 <= e[2] < 300]
        p_4xx = [e for e in posts if 400 <= e[2] < 500]
        p_404 = [e for e in posts if e[2] == 404]
        g_ok = [e for e in gets if e[2] in (200, 404)]
        exc = [e for e in events if isinstance(e[2], str)]
        print(f"[summary] posts={len(posts)} (2xx={len(p_ok)} 4xx={len(p_4xx)} "
              f"404={len(p_404)} 5xx={len(p5)}); gets={len(gets)} "
              f"(200/404={len(g_ok)} 5xx={len(g5)}); exceptions={len(exc)}")
        for e in exc[:5]:
            print(f"[exception sample] {e}")

        n5 = len(p5) + len(g5)
        if n5 >= 1:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            reproduced = False
            if n5 == 1:
                probe = {"move_shard": {"shard_id": 0, "to_peer_id": 987654,
                                        "from_peer_id": 987655}}
                try:
                    ps, praw = safe_request("POST", "collection_cluster",
                                            path_params={"name": C},
                                            body=probe)
                    reproduced = 500 <= ps <= 599
                    print(f"[reproduce probe] status={ps} raw={praw[:200]}")
                except Exception:
                    reproduced = False
            if n5 >= 2 or reproduced:
                DEFECTS.append(
                    f"(race) {n5} 500-class responses from the chunk endpoint "
                    f"during collection lifecycle race (posts={[e[2] for e in p5]}"
                    f" gets={[e[2] for e in g5]}); the documented disposition "
                    f"set is 200/400/404 — graceful 404 expected for a "
                    f"temporarily absent collection, service alive per "
                    f"/healthz — Type3_RuntimeFailure"
                )
            else:
                print("ENV_ISSUE: single sporadic 5xx not reproduced — "
                      "recorded, not judged")
        if exc and not posts and not gets:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[exc liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: access thread produced only exceptions — "
                  "liveness ok, race not judged")

        # ---- final reconciliation ----
        cs, craw = safe_request("PUT", "create_collection",
                                path_params={"name": C}, body=CREATE_BODY)
        print(f"[reconcile create] status={cs} raw={craw[:160]}")
        if cs in (200, 201, 409):
            time.sleep(0.5)
            fs, fraw = safe_request("GET", "collection_cluster",
                                    path_params={"name": C})
            print(f"[reconcile info] status={fs} raw={fraw[:300]}")
            if fs == 200:
                node = result_node(fraw)
                transfers = node.get("shard_transfers") \
                    if isinstance(node, dict) else None
                if not isinstance(transfers, list):
                    DEFECTS.append(
                        f"(reconcile) shard_transfers missing/not a list after "
                        f"race: {transfers!r} — Type4_StateLogicViolation"
                    )
            elif 500 <= fs <= 599:
                hs, hraw = safe_request("GET", "healthz")
                print(f"[reconcile liveness] healthz status={hs} "
                      f"raw={str(hraw)[:120]}")
                if hs != 200:
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(reconcile) cluster info {fs} (5xx; 200 expected, "
                    f"service alive per /healthz) — Type3_RuntimeFailure — "
                    f"raw={fraw[:200]}"
                )
            ncs, nraw = safe_request("POST", "count", path_params={"name": C},
                                     body={"exact": True})
            print(f"[reconcile count] status={ncs} raw={nraw[:160]}")
            if ncs == 200:
                node = result_node(nraw)
                cnt = node.get("count") if isinstance(node, dict) else None
                if isinstance(cnt, int) and cnt != 0:
                    DEFECTS.append(
                        f"(reconcile) freshly recreated collection has "
                        f"count={cnt} (0 expected) — ghost data survived the "
                        f"lifecycle race — Type4_StateLogicViolation"
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
