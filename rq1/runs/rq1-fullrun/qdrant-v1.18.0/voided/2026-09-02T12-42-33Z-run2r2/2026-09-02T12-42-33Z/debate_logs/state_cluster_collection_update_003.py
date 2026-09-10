#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_collection_update_003
# strategy: count_consistency
# endpoint: cluster+collection+update
# constraint_ids: qdrant_state_cluster_collection_update_001, qdrant_behavioral_cluster_collection_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 (CRUD-then-COUNT consistency) wrapped around a
  cluster-operation battery on POST /collections/{name}/cluster
  (cluster+collection+update; URL from raw_knowledge api_endpoints[].url).
  The state constraint frames cluster ops as asynchronous transfer
  initiations that must never corrupt the collection's data plane; the
  behavioral assertion promises 4xx for invalid peer/shard. Sequence:
  create -> upsert N=48 points (wait=true) -> exact count == N (baseline
  acked) -> run a compact ghost-peer/shard cluster-op battery (move_shard,
  replicate_shard, drop_replica, abort_transfer) -> exact count must still
  be N (Type4 on drift), a scroll spot-check must return real inserted ids
  (Type4 on loss/ghosts), and cluster info must stay 200 with empty
  shard_transfers (Type4 on pollution).
  [chunk_cluster+collection+update coverage: count_consistency x
   qdrant_state_cluster_collection_update_001 (data-plane preservation
   across transfer initiations) + qdrant_behavioral_cluster_collection_update_001
   (rejection dispositions of the battery)]
Oracle: exact count after the battery == 48 (drift = Type4), scroll returns
  5 points whose ids are among the inserted set (missing/foreign ids =
  Type4), cluster info 200 with shard_transfers == []; any op 2xx =
  Type1_IllegalSuccess, any 5xx = Type3 only after /healthz liveness
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

N_POINTS = 48
DIM = 4


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


def exact_count(name):
    s, raw = safe_request("POST", "count", path_params={"name": name},
                          body={"exact": True})
    if s != 200:
        return None, (s, raw)
    node = result_node(raw)
    cnt = node.get("count") if isinstance(node, dict) else None
    return (cnt if isinstance(cnt, int) else None), (s, raw)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccu3_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    inserted = list(range(1, N_POINTS + 1))
    inserted_set = set(inserted)

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"

        pts = [{"id": i, "vector": [round(0.01 * i + 0.1 * (j + 1), 6)
                                    for j in range(DIM)]}
               for i in inserted]
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C}, body={"points": pts},
                              query_params={"wait": "true"})
        print(f"[upsert] status={s} raw={raw[:200]}")
        if not (200 <= s < 300):
            print(f"SETUP_ERROR: upsert returned {s}")
            return "SCRIPT_ERROR"

        cnt0, (cs0, craw0) = exact_count(C)
        print(f"[count baseline] status={cs0} count={cnt0} raw={craw0[:200]}")
        if cnt0 != N_POINTS:
            print(f"SETUP_ERROR: baseline count {cnt0} != {N_POINTS}")
            return "SCRIPT_ERROR"

        # ghost ids: far outside the small-uint peer/shard id space
        GHOST_PEER = 987654
        GHOST_SHARD = 9000
        battery = [
            ("move_shard:ghost_peer",
             {"move_shard": {"shard_id": 0, "to_peer_id": GHOST_PEER,
                             "from_peer_id": GHOST_PEER + 1}}),
            ("replicate_shard:ghost_peer",
             {"replicate_shard": {"shard_id": 0, "to_peer_id": GHOST_PEER,
                                  "from_peer_id": GHOST_PEER + 1}}),
            ("drop_replica:ghost_peer",
             {"drop_replica": {"shard_id": 0, "peer_id": GHOST_PEER}}),
            ("abort_transfer:unknown",
             {"abort_transfer": {"shard_id": GHOST_SHARD,
                                 "to_peer_id": GHOST_PEER,
                                 "from_peer_id": GHOST_PEER + 1}}),
        ]
        for label, op in battery:
            s, raw = safe_request("POST", "collection_cluster",
                                  path_params={"name": C}, body=op)
            print(f"[op {label}] status={s} raw={raw[:240]}")
            if 200 <= s < 300:
                DEFECTS.append(
                    f"(op {label}) returned {s} (2xx) — assertion promises 400 "
                    f"for invalid peer/shard — Type1_IllegalSuccess — "
                    f"raw={raw[:200]}"
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

        # ---- data-plane reconciliation ----
        time.sleep(1.0)
        cnt1, (cs1, craw1) = exact_count(C)
        print(f"[count after] status={cs1} count={cnt1} raw={craw1[:200]}")
        if cnt1 is None:
            if cs1 == 404:
                DEFECTS.append(
                    f"(count after) count endpoint 404 on live collection "
                    f"'{C}' — collection state lost after cluster-op battery — "
                    f"Type4_StateLogicViolation — raw={craw1[:200]}"
                )
            elif 500 <= cs1 <= 599:
                hs, hraw = safe_request("GET", "healthz")
                print(f"[count after liveness] healthz status={hs} "
                      f"raw={str(hraw)[:120]}")
                if hs != 200:
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(count after) count endpoint {cs1} (5xx; 200 expected, "
                    f"service alive per /healthz) — Type3_RuntimeFailure — "
                    f"raw={craw1[:200]}"
                )
            else:
                print(f"OBSERVATION: count after battery status={cs1} — "
                      f"outside promise set, recorded, not judged")
        elif cnt1 != N_POINTS:
            DEFECTS.append(
                f"(count after) exact count {cnt1} != {N_POINTS} after "
                f"cluster-op battery — data-plane drift from transfer-plane "
                f"operations — Type4_StateLogicViolation"
            )

        ss, sraw = safe_request("POST", "scroll", path_params={"name": C},
                                body={"limit": 5, "with_vector": False,
                                      "with_payload": False})
        print(f"[scroll spot-check] status={ss} raw={sraw[:300]}")
        if ss == 200:
            res = result_node(sraw)
            got = []
            if isinstance(res, dict) and isinstance(res.get("points"), list):
                got = [p.get("id") for p in res["points"]
                       if isinstance(p, dict)]
            if len(got) != 5:
                DEFECTS.append(
                    f"(scroll) expected 5 points back, got {len(got)} — "
                    f"Type4_StateLogicViolation — raw={sraw[:200]}"
                )
            foreign = [g for g in got if g not in inserted_set]
            if foreign:
                DEFECTS.append(
                    f"(scroll) foreign ids {foreign} not in inserted set — "
                    f"ghost records — Type4_StateLogicViolation"
                )
        elif 500 <= ss <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[scroll liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(scroll) {ss} (5xx; 200 expected, service alive per "
                f"/healthz) — Type3_RuntimeFailure — raw={sraw[:200]}"
            )

        is_, iraw = safe_request("GET", "collection_cluster",
                                 path_params={"name": C})
        print(f"[cluster info after] status={is_} raw={iraw[:300]}")
        if is_ == 200:
            node = result_node(iraw)
            transfers = node.get("shard_transfers") if isinstance(node, dict) \
                else None
            if not isinstance(transfers, list) or transfers:
                DEFECTS.append(
                    f"(cluster info after) shard_transfers polluted: "
                    f"{transfers!r} — Type4_StateLogicViolation"
                )
        elif is_ == 404:
            DEFECTS.append(
                f"(cluster info after) 404 on live collection '{C}' — state "
                f"lost — Type4_StateLogicViolation — raw={iraw[:200]}"
            )
        elif 500 <= is_ <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[info liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(cluster info after) {is_} (5xx; 200 expected, service "
                f"alive per /healthz) — Type3_RuntimeFailure — "
                f"raw={iraw[:200]}"
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
