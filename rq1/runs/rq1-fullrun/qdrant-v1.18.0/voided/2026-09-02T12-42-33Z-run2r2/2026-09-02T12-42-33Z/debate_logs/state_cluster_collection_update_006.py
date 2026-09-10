#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_collection_update_006
# strategy: count_consistency
# endpoint: cluster+collection+update
# constraint_ids: qdrant_state_cluster_collection_update_001, qdrant_behavioral_cluster_collection_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Positive-direction attack on the state constraint's core promise —
  "HTTP 200 means the operation was accepted, not completed; progress is
  observable through the collection cluster info endpoint". Flow (Pattern A
  create -> modify -> verify -> teardown) on POST
  /collections/{name}/cluster (URL from raw_knowledge
  api_endpoints[].url): (1) create a sharding_method=custom collection and
  capture the baseline shard_count from GET cluster info plus the raw shard
  keys listing (GET /collections/{name}/shards); (2) submit
  create_sharding_key -> 2xx means ACCEPTED, so the effect (shard_count +1
  or the key appearing in the shards listing) MUST become observable by
  polling — an accepted operation that never surfaces violates the
  observability promise (Type4); (3) duplicate create of the same key ->
  the duplicate-key promise says 400; a 2xx = accepted twice (Type4);
  (4) drop_sharding_key -> 2xx ack must reconcile: shard_count back to
  baseline and the key gone from the shards listing (persist = Type4);
  (5) final cluster info must be 200 with shard_transfers empty.
  [chunk_cluster+collection+update coverage: async-acceptance observability
   x qdrant_state_cluster_collection_update_001 (core promise, positive
   side) + qdrant_behavioral_cluster_collection_update_001 (200 leg valid
   op / 400 leg duplicate key)]
Oracle: create_sharding_key -> 2xx accepted and the shard becomes
  observable in cluster info (shard_count >= baseline+1) or the shards
  listing (key present) within a 10s poll (never observable =
  Type4_StateLogicViolation); duplicate create -> 400 (2xx = Type4);
  drop_sharding_key 2xx -> shard_count back to baseline and key absent
  within 10s (persist = Type4); any 5xx = Type3 only after /healthz
  liveness; shard_transfers must be [] at the end
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

POLL_ROUNDS = 20
POLL_SLEEP = 0.5


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


def shard_count_of(name):
    """(shard_count|None, status, raw) from GET cluster info."""
    s, raw = safe_request("GET", "collection_cluster",
                          path_params={"name": name})
    if s != 200:
        return None, s, raw
    node = result_node(raw)
    cnt = node.get("shard_count") if isinstance(node, dict) else None
    return (cnt if isinstance(cnt, int) else None), s, raw


def shards_raw(name):
    """Raw text of the shard-keys listing (GET /collections/{name}/shards)."""
    try:
        s, raw = safe_request("GET", "update_shards",
                              path_params={"name": name})
        return s, raw or ""
    except Exception:
        return 0, ""


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccu6_" + TS + "_"
    C = PFX + "col"
    KEY = PFX + "sk1"
    DEFECTS = []

    try:
        cs, craw = safe_request(
            "PUT", "create_collection", path_params={"name": C},
            body={"vectors": {"size": 4, "distance": "Cosine"},
                  "sharding_method": "custom"})
        print(f"[setup create custom] status={cs} raw={craw[:200]}")
        if cs not in (200, 201, 409):
            print("SETUP_ERROR: custom-sharded collection could not be "
                  "created — positive observability flow not runnable")
            return "SCRIPT_ERROR"

        base_cnt, bs, braw = shard_count_of(C)
        ssr0 = shards_raw(C)
        print(f"[baseline] cluster info status={bs} shard_count={base_cnt} "
              f"raw={braw[:200]}")
        print(f"[baseline] shards listing status={ssr0[0]} "
              f"key_present={KEY in ssr0[1]} raw={ssr0[1][:200]}")
        if bs != 200 or base_cnt is None:
            print("SETUP_ERROR: baseline cluster info unreadable")
            return "SCRIPT_ERROR"

        # ---- (1) submit create_sharding_key: 2xx = ACCEPTED ----
        op = {"create_sharding_key": {"shard_key": KEY, "shards_number": 1,
                                      "replication_factor": 1}}
        s, raw = safe_request("POST", "collection_cluster",
                              path_params={"name": C}, body=op)
        print(f"[create key] status={s} raw={raw[:300]}")
        accepted = 200 <= s < 300
        if 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[create liveness] healthz status={hs} "
                  f"raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(create key) returned {s} (5xx; 200/400 promised, service "
                f"alive per /healthz) — Type3_RuntimeFailure — "
                f"raw={raw[:200]}"
            )
        elif s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[create transport] healthz status={hs} "
                  f"raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on create key — flow aborted")
        elif not accepted:
            print(f"OBSERVATION (create key): valid op rejected with {s} — "
                  f"clear diagnostics, deployment face recorded, not judged")

        if accepted:
            # ---- (2) observability poll: accepted MUST surface ----
            observable = False
            for i in range(POLL_ROUNDS):
                time.sleep(POLL_SLEEP)
                cnt, cs2, craw2 = shard_count_of(C)
                sr = shards_raw(C)
                key_in = KEY in sr[1]
                if (isinstance(cnt, int) and cnt >= base_cnt + 1) or key_in:
                    observable = True
                    print(f"[poll {i}] observable: shard_count={cnt} "
                          f"(base={base_cnt}) key_in_shards={key_in}")
                    break
            if not observable:
                cnt, cs2, craw2 = shard_count_of(C)
                sr = shards_raw(C)
                DEFECTS.append(
                    f"(observability) create_sharding_key was 2xx-accepted "
                    f"but never became observable within "
                    f"{POLL_ROUNDS * POLL_SLEEP:.0f}s: shard_count={cnt} "
                    f"(base={base_cnt}), key_in_shards={KEY in sr[1]} — "
                    f"accepted-but-invisible violates the 'progress is "
                    f"observable through cluster info' constraint — "
                    f"Type4_StateLogicViolation"
                )

            # ---- (3) duplicate create: promise says 400 ----
            s, raw = safe_request("POST", "collection_cluster",
                                  path_params={"name": C}, body=op)
            print(f"[duplicate key] status={s} raw={raw[:300]}")
            if 200 <= s < 300:
                DEFECTS.append(
                    f"(duplicate key) duplicate create_sharding_key '{KEY}' "
                    f"returned {s} (2xx) — duplicate-key rejection (400) "
                    f"promise broken — same key accepted twice — "
                    f"Type4_StateLogicViolation — raw={raw[:200]}"
                )
            elif 500 <= s <= 599:
                hs, hraw = safe_request("GET", "healthz")
                print(f"[duplicate liveness] healthz status={hs} "
                      f"raw={str(hraw)[:120]}")
                if hs != 200:
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(duplicate key) {s} (5xx; 400 expected, service alive "
                    f"per /healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
                )
            elif s == 0:
                hs, hraw = safe_request("GET", "healthz")
                print(f"[duplicate transport] healthz status={hs} "
                      f"raw={str(hraw)[:120]}")
                if hs != 200:
                    return "SCRIPT_ERROR"
                print("ENV_ISSUE: transport failure on duplicate — skipped")

            # ---- (4) drop the key: 2xx ack must reconcile ----
            drop_op = {"drop_sharding_key": {"shard_key": KEY}}
            s, raw = safe_request("POST", "collection_cluster",
                                  path_params={"name": C}, body=drop_op)
            print(f"[drop key] status={s} raw={raw[:300]}")
            if 200 <= s < 300:
                reconciled = False
                for i in range(POLL_ROUNDS):
                    time.sleep(POLL_SLEEP)
                    cnt, ds2, draw2 = shard_count_of(C)
                    sr = shards_raw(C)
                    if (isinstance(cnt, int) and cnt <= base_cnt) \
                            and KEY not in sr[1]:
                        reconciled = True
                        print(f"[drop poll {i}] reconciled: shard_count={cnt} "
                              f"key_in_shards={KEY in sr[1]}")
                        break
                if not reconciled:
                    cnt, ds2, draw2 = shard_count_of(C)
                    sr = shards_raw(C)
                    DEFECTS.append(
                        f"(drop key) drop was 2xx-acked but state did not "
                        f"reconcile: shard_count={cnt} (base={base_cnt}), "
                        f"key_in_shards={KEY in sr[1]} — dropped key "
                        f"persists — Type4_StateLogicViolation"
                    )
            elif 500 <= s <= 599:
                hs, hraw = safe_request("GET", "healthz")
                print(f"[drop liveness] healthz status={hs} "
                      f"raw={str(hraw)[:120]}")
                if hs != 200:
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(drop key) {s} (5xx; 200 expected for empty key, "
                    f"service alive per /healthz) — Type3_RuntimeFailure — "
                    f"raw={raw[:200]}"
                )
            elif 400 <= s < 500:
                time.sleep(1.0)
                s2, raw2 = safe_request("POST", "collection_cluster",
                                        path_params={"name": C},
                                        body=drop_op)
                print(f"[drop retry] status={s2} raw={raw2[:200]}")
                if 500 <= s2 <= 599:
                    hs, hraw = safe_request("GET", "healthz")
                    print(f"[drop retry liveness] healthz status={hs} "
                          f"raw={str(hraw)[:120]}")
                    if hs != 200:
                        return "SCRIPT_ERROR"
                    DEFECTS.append(
                        f"(drop key retry) {s2} (5xx; service alive per "
                        f"/healthz) — Type3_RuntimeFailure — "
                        f"raw={raw2[:200]}"
                    )
                else:
                    print("OBSERVATION (drop key): teardown face rejected "
                          f"with {s}/{s2} — recorded, not judged "
                          f"(creation-side promises already judged)")

        # ---- (5) final state must be clean ----
        fs, fraw = safe_request("GET", "collection_cluster",
                                path_params={"name": C})
        print(f"[final info] status={fs} raw={fraw[:300]}")
        if fs == 200:
            node = result_node(fraw)
            transfers = node.get("shard_transfers") \
                if isinstance(node, dict) else None
            if not isinstance(transfers, list) or transfers:
                DEFECTS.append(
                    f"(final) shard_transfers not empty at rest: "
                    f"{transfers!r} — Type4_StateLogicViolation"
                )
        elif 500 <= fs <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[final liveness] healthz status={hs} "
                  f"raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(final) cluster info {fs} (5xx; 200 expected, service "
                f"alive per /healthz) — Type3_RuntimeFailure — "
                f"raw={fraw[:200]}"
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
