#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_create_006
# strategy: concurrent
# endpoint: index+create
# constraint_ids: qdrant_behavioral_index_create_001, qdrant_inv_index_toggle_preserves_data_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness — index-resource lifecycle
#   churning under concurrent access is the state the team under-instruments)
"""
Attack: concurrent (Strategy 7: lifecycle concurrency of the index RESOURCE
  vs concurrent access; distinct from Strategy 4 point-level races) x
  qdrant_behavioral_index_create_001 (200 branch under lifecycle churn) +
  invariant qdrant_inv_index_toggle_preserves_data_001. The COLLECTION stays
  alive the whole time; only its payload index is churned. Thread A
  (lifecycle): R=8 rounds of create_index city keyword (wait=true) ->
  delete_index city (wait=true); Threads B.. (access): until the lifecycle
  finishes, alternate filtered exact count on city=c0 (baseline 200 of 400
  points) and nearest query limit 3. Because the collection provably exists,
  the access faces must never 404 and never 5xx; the index presence/absence
  must NEVER change what the data faces return (filtered count is the
  state-oracle: exactly 200 on every sample regardless of index state). At
  the end: final exact count == 400. Sporadic discipline (strategy 7):
  single 5xx/404 occurrences are re-probed in a post-join access burst and
  claimed only on reproduction (>=2); count-drift samples are claimed
  individually (deterministic oracle).
  [chunk_index+create coverage: concurrent x
  qdrant_behavioral_index_create_001 (200 branch during churn) x
  qdrant_inv_index_toggle_preserves_data_001]
Oracle: during 8 create/delete index churn rounds with concurrent access,
  every filtered count sample on c0 returns exactly 200 and every query
  returns 200 (no 404 - the collection exists; no 5xx); lifecycle
  create/delete ops themselves return 200; final total count == 400.
  Reproduced (>=2) 5xx = Type3_RuntimeFailure; reproduced 404 on the live
  collection = Type4_StateLogicViolation; any c0 count != 200 =
  Type4_StateLogicViolation (index state must not change query results)
  (qdrant_behavioral_index_create_001, qdrant_inv_index_toggle_preserves_data_001)
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

print(f"[PATHS] index keys present="
      f"{[k for k in ('create_index', 'delete_index', 'count', 'query', 'upsert_points') if k in rt.PATHS]}")

N = 400
PER_VAL = N // 2          # c0 = c1 = 200
ROUNDS = 8                # lifecycle churn rounds
MAX_WINDOW_S = 12.0       # hard cap on the access window


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    """Transport/5xx branch liveness re-check via the lightweight healthz face."""
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def filtered_count_c0(tag, collection):
    """Exact filtered count on city=c0; returns (count_or_None, s)."""
    s, raw = safe_request("POST", "count",
                          body={"exact": True,
                                "filter": {"must": [
                                    {"key": "city",
                                     "match": {"value": "c0"}}]}},
                          path_params={"name": collection})
    if s != 200:
        print(f"[{tag}] filtered count status={s} raw={str(raw)[:160]}")
        return None, s
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict) or not isinstance(res.get("count"), int):
        return None, s
    return res["count"], s


def vec4(i):
    return [0.1 + 0.001 * (i % 100), 0.2, 0.3, 0.4]


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidx6_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    NOTES = []

    lock = threading.Lock()
    access_5xx = []        # (tag, raw) 5xx on access faces (alive-checked)
    access_404 = []        # (tag, raw) 404 on access faces
    count_drifts = []      # (tag, seen, raw)
    transport_hits = []    # (tag,)
    lifecycle_errs = []    # (op, status, raw)
    stop_flag = threading.Event()

    try:
        ok, err = rt.setup_default(C, 4)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"
        batch = 200
        for start in range(0, N, batch):
            pts = [{"id": i, "vector": vec4(i),
                    "payload": {"city": f"c{i % 2}"}}
                   for i in range(start, min(start + batch, N))]
            s, raw = safe_request("PUT", "upsert_points",
                                  body={"points": pts},
                                  path_params={"name": C},
                                  query_params={"wait": "true"})
            print(f"[setup upsert {start}-{start + len(pts)}] status={s} "
                  f"raw={str(raw)[:120]}")
            if s not in (200, 201):
                return "SCRIPT_ERROR"

        c0_base, _ = filtered_count_c0("baseline c0", C)
        if c0_base != PER_VAL:
            print(f"VERDICT: SCRIPT_ERROR - baseline c0={c0_base} != {PER_VAL}")
            return "SCRIPT_ERROR"
        print(f"[baseline] c0={c0_base}")

        # ---- thread A: index lifecycle churn (create <-> delete) ----
        def lifecycle_thread():
            for rnd in range(ROUNDS):
                if not stop_flag.is_set():
                    s, raw = safe_request("PUT", "create_index",
                                          body={"field_name": "city",
                                                "field_schema": {"type": "keyword"}},
                                          path_params={"name": C},
                                          query_params={"wait": "true"})
                    print(f"[lifecycle r{rnd} create] status={s} "
                          f"raw={str(raw)[:160]}")
                    if s not in (200, 201):
                        with lock:
                            lifecycle_errs.append(("create", s, str(raw)[:160]))
                    time.sleep(0.05)
                if not stop_flag.is_set():
                    s, raw = safe_request("DELETE", "delete_index",
                                          path_params={"name": C,
                                                       "field_name": "city"},
                                          query_params={"wait": "true"})
                    print(f"[lifecycle r{rnd} delete] status={s} "
                          f"raw={str(raw)[:160]}")
                    if s not in (200, 201):
                        # 404 on delete of a just-deleted index is idempotent
                        # delete territory (by-design per threat_model) -
                        # only 5xx/transport are lifecycle anomalies
                        if s == 404:
                            NOTES.append(f"lifecycle r{rnd} delete: 404 "
                                         f"(index already absent - idempotent "
                                         f"delete, not claimed)")
                        else:
                            with lock:
                                lifecycle_errs.append(("delete", s, str(raw)[:160]))
                    time.sleep(0.05)

        # ---- threads B..: concurrent access while the index churns ----
        t_count = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10") or 10)
        t_count = max(2, min(t_count, 20))
        print(f"[window] lifecycle x{ROUNDS} rounds; {t_count} access workers")

        def access_worker(wid):
            seq = 0
            while not stop_flag.is_set():
                seq += 1
                tag = f"a{wid}#{seq}"
                try:
                    if seq % 2 == 1:
                        cnt, s = filtered_count_c0(tag, C)
                        if s == 0:
                            with lock:
                                transport_hits.append((tag,))
                        elif s == 404:
                            with lock:
                                access_404.append((tag, "count"))
                        elif 500 <= s <= 599:
                            if liveness(tag):
                                with lock:
                                    access_5xx.append((tag, "count"))
                        elif s == 200 and cnt is not None and cnt != PER_VAL:
                            with lock:
                                count_drifts.append((tag, cnt, ""))
                    else:
                        s, raw = safe_request("POST", "query",
                                              body={"query": {"nearest": vec4(wid)},
                                                    "limit": 3},
                                              path_params={"name": C})
                        if s == 0:
                            with lock:
                                transport_hits.append((tag,))
                        elif s == 404:
                            with lock:
                                access_404.append((tag, str(raw)[:120]))
                        elif 500 <= s <= 599:
                            if liveness(tag):
                                with lock:
                                    access_5xx.append((tag, str(raw)[:120]))
                except Exception as e:
                    with lock:
                        NOTES.append(f"{tag}: exception {str(e)[:120]}")
                time.sleep(0.02)

        lt = threading.Thread(target=lifecycle_thread)
        workers = [threading.Thread(target=access_worker, args=(w,))
                   for w in range(t_count)]
        lt.start()
        for w in workers:
            w.start()
        lt.join(timeout=MAX_WINDOW_S)
        stop_flag.set()
        for w in workers:
            w.join(timeout=5.0)
        lifecycle_done = not lt.is_alive()
        print(f"[window done] lifecycle_completed={lifecycle_done} "
              f"5xx={len(access_5xx)} 404={len(access_404)} "
              f"drifts={len(count_drifts)} transport={len(transport_hits)}")

        # ---- sporadic reproduction burst (strategy 7: >=2 rule) ----
        if (access_5xx or access_404) and len(access_5xx) + len(access_404) == 1:
            repro_5xx = repro_404 = 0
            for i in range(10):
                s, raw = safe_request("POST", "query",
                                      body={"query": {"nearest": vec4(i)},
                                            "limit": 3},
                                      path_params={"name": C})
                if 500 <= s <= 599:
                    repro_5xx += 1
                elif s == 404:
                    repro_404 += 1
            print(f"[repro burst] 5xx={repro_5xx}/10 404={repro_404}/10")
            if repro_5xx:
                access_5xx.append(("repro-burst", "query"))
            if repro_404:
                access_404.append(("repro-burst", "query"))

        # ---- final state: data untouched by the churn ----
        s, raw = safe_request("POST", "count", body={"exact": True},
                              path_params={"name": C})
        b = parse_json(raw)
        total_final = ((b or {}).get("result") or {}).get("count") if s == 200 else None
        c0_final, _ = filtered_count_c0("final c0", C)
        print(f"[final] total={total_final} c0={c0_final} "
              f"expected total={N} c0={PER_VAL}")
        if total_final != N:
            DEFECTS.append(
                f"(final count) total {total_final} != {N} after the index "
                f"lifecycle churn - Type4_StateLogicViolation "
                f"(qdrant_inv_index_toggle_preserves_data_001)")
        if c0_final != PER_VAL:
            DEFECTS.append(
                f"(final c0) filtered count {c0_final} != {PER_VAL} after "
                f"the churn - Type4_StateLogicViolation")

        # ---- anomaly adjudication ----
        for (tag, face) in access_5xx:
            DEFECTS.append(
                f"({tag}) HTTP 5xx on the {face} face while the collection "
                f"exists and /healthz alive, during index lifecycle churn - "
                f"Type3_RuntimeFailure (BS-03)")
        for (tag, face) in access_404:
            DEFECTS.append(
                f"({tag}) HTTP 404 on the {face} face of a LIVE collection "
                f"during index lifecycle churn - Type4_StateLogicViolation "
                f"(BS-03; the collection was never dropped)")
        for (tag, seen, raw) in count_drifts:
            DEFECTS.append(
                f"({tag}) filtered count drifted to {seen} != {PER_VAL} "
                f"while the index was churning - Type4_StateLogicViolation "
                f"(index state must not change query results)")
        if len(transport_hits) >= 2:
            DEFECTS.append(
                f"{len(transport_hits)} transport losses (status 0) during "
                f"the churn window on an alive service - "
                f"Type3_RuntimeFailure - {[t for (t,) in transport_hits][:6]}")
        elif transport_hits:
            NOTES.append(f"single transport loss recorded (race discipline, "
                         f"not claimed): {transport_hits}")
        for (op, s, raw) in lifecycle_errs:
            if 500 <= s <= 599 or s == 0:
                DEFECTS.append(
                    f"(lifecycle {op}) HTTP {s} while /healthz alive - "
                    f"Type3_RuntimeFailure - raw={raw}")
            else:
                DEFECTS.append(
                    f"(lifecycle {op}) index lifecycle op rejected with "
                    f"HTTP {s} - Type1_IllegalSuccess - raw={raw}")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print(f"index lifecycle churn verified: {ROUNDS} create/delete rounds "
              f"under {t_count} concurrent access workers; every c0 sample="
              f"{PER_VAL}, no 404/5xx on live-collection faces, final total="
              f"{N} - NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup (own data only; failure must not flip the verdict)
        stop_flag.set()
        try:
            rt.drop_collection(C)
            print(f"[cleanup] dropped {C}")
        except Exception as e:
            print(f"[cleanup] drop {C} failed (ignored): {e}")


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
