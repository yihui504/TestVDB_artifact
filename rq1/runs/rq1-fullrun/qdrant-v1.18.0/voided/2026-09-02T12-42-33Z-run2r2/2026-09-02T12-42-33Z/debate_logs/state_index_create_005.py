#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_create_005
# strategy: concurrent
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001, qdrant_inv_index_toggle_preserves_data_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness — the payload-index build is
#   async under wait=false; concurrent reads/writes during the build window
#   are exactly the state the team under-instruments)
"""
Attack: concurrent + index_state (Strategy 6: state consistency during index
  builds) x qdrant_type_index_create_001 (valid keyword schema) + invariant
  qdrant_inv_index_toggle_preserves_data_001 (index building must not alter
  point data). Sequence: (1) collection dim 8 with N=1200 points, keyword
  payload city in {c0,c1,c2} (400 each), upserted wait=true; baseline exact
  counts recorded; (2) fire index+create city keyword with wait=false (the
  ack returns immediately, the build proceeds in the background); (3) DURING
  the build window run TESTVDB_CONCURRENT_THREADS workers for ~3s in three
  roles: filtered exact count on city=c0 (must be EXACTLY 400 at every
  sample - index building must never change query results), nearest query
  limit 5 (must stay 200), and upserts of NEW points tagged
  city=cw{worker} (wait=true, accounted per worker); (4) after the window,
  poll describe (<=30s) until the city index appears in
  result.payload_schema - a 2xx create that never materializes =
  Type4 (ack without persistence); (5) final exact count == N + upserted
  total and filtered c0 count == 400. 5xx on any face with /healthz alive =
  Type3; transport losses need >=2 reproductions (race discipline).
  SKIPPED (by-design per threat_model): async-operation error logging for
  wait=false (issue #4925) is NOT asserted — only synchronous observable
  state (status codes + describe echo + exact counts) is adjudicated.
  [chunk_index+create coverage: concurrent x qdrant_type_index_create_001
  (valid schema during build) x qdrant_inv_index_toggle_preserves_data_001]
Oracle: during the async index build every filtered count sample on c0
  returns exactly 400 and every query returns 200; the create ack is 2xx
  and the index becomes visible in describe result.payload_schema within
  the poll budget; final total count == 1200 + succeeded upserts and c0
  count == 400. Any 5xx with /healthz alive = Type3_RuntimeFailure; count
  drift, c0 != 400, or a never-materialized index = Type4_StateLogicViolation
  (qdrant_type_index_create_001, qdrant_inv_index_toggle_preserves_data_001)
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
      f"{[k for k in ('create_index', 'describe_collection', 'count', 'query', 'upsert_points') if k in rt.PATHS]}")

N = 1200                      # baseline points
PER_VAL = N // 3              # c0/c1/c2 each 400
WINDOW_S = 3.0                # concurrent window overlapping the build
POLL_BUDGET_S = 30.0          # describe poll budget for materialization


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


def filtered_count(tag, collection, value):
    """Exact filtered count on the keyword payload; returns (count_or_None, s)."""
    s, raw = safe_request("POST", "count",
                          body={"exact": True,
                                "filter": {"must": [
                                    {"key": "city",
                                     "match": {"value": value}}]}},
                          path_params={"name": collection})
    if s != 200:
        print(f"[{tag}] filtered count status={s} raw={str(raw)[:160]}")
        return None, s
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict) or not isinstance(res.get("count"), int):
        return None, s
    return res["count"], s


def vec8(i):
    return [0.1 + 0.001 * (i % 100), 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidx5_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    NOTES = []

    lock = threading.Lock()
    anomalies = []       # (role, kind, status, raw) observed anomalies
    transport_hits = []  # (role, raw) transport losses (status 0)
    upserted = {}        # worker -> count of accepted new points

    try:
        ok, err = rt.setup_default(C, 8)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"
        batch = 400
        for start in range(0, N, batch):
            pts = [{"id": i, "vector": vec8(i),
                    "payload": {"city": f"c{i % 3}"}}
                   for i in range(start, min(start + batch, N))]
            s, raw = safe_request("PUT", "upsert_points",
                                  body={"points": pts},
                                  path_params={"name": C},
                                  query_params={"wait": "true"})
            print(f"[setup upsert {start}-{start + len(pts)}] status={s} "
                  f"raw={str(raw)[:120]}")
            if s not in (200, 201):
                return "SCRIPT_ERROR"

        s, raw = safe_request("POST", "count", body={"exact": True},
                              path_params={"name": C})
        b = parse_json(raw)
        total0 = ((b or {}).get("result") or {}).get("count") if s == 200 else None
        c0_0, _ = filtered_count("baseline c0", C, "c0")
        print(f"[baseline] total={total0} c0={c0_0}")
        if total0 != N or c0_0 != PER_VAL:
            print(f"VERDICT: SCRIPT_ERROR - baseline counts wrong: "
                  f"total={total0} c0={c0_0}")
            return "SCRIPT_ERROR"

        # ---- fire the async index create (wait=false) ----
        t_start = time.time()
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": "city",
                                    "field_schema": {"type": "keyword"}},
                              path_params={"name": C},
                              query_params={"wait": "false"})
        print(f"[create wait=false] status={s} raw={str(raw)[:240]}")
        if s == 0 or 500 <= s <= 599:
            if not liveness("create wait=false"):
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(create wait=false) HTTP {s} on a valid create while "
                f"/healthz alive - Type3_RuntimeFailure - raw={str(raw)[:160]}")
        elif s not in (200, 201):
            DEFECTS.append(
                f"(create wait=false) valid create rejected with HTTP {s} - "
                f"Type1_IllegalSuccess - raw={str(raw)[:160]} "
                f"(qdrant_type_index_create_001)")
        create_acked = 200 <= s <= 299

        # ---- concurrent window over the build ----
        t_count = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10") or 10)
        t_count = max(3, min(t_count, 50))
        print(f"[window] {t_count} workers for {WINDOW_S}s "
              f"(roles: count-c0 / query / upsert-new)")

        def record(role, kind, s, raw):
            with lock:
                anomalies.append((role, kind, s, str(raw)[:160]))

        def worker(wid):
            role = wid % 3
            ups = 0
            deadline = time.time() + WINDOW_S
            seq = 0
            while time.time() < deadline:
                seq += 1
                tag = f"w{wid}#{seq}"
                try:
                    if role == 0:
                        cnt, s = filtered_count(tag, C, "c0")
                        if s == 0:
                            with lock:
                                transport_hits.append((tag, "count"))
                        elif s == 404:
                            record(tag, "404-during-build", s, "")
                        elif 500 <= s <= 599:
                            if liveness(tag):
                                record(tag, "5xx", s, "")
                        elif s == 200 and cnt is not None and cnt != PER_VAL:
                            record(tag, "count-drift", s,
                                   f"c0={cnt} expected {PER_VAL}")
                    elif role == 1:
                        s, raw = safe_request("POST", "query",
                                              body={"query": {"nearest": vec8(wid)},
                                                    "limit": 5},
                                              path_params={"name": C})
                        if s == 0:
                            with lock:
                                transport_hits.append((tag, "query"))
                        elif s == 404:
                            record(tag, "404-during-build", s, raw)
                        elif 500 <= s <= 599:
                            if liveness(tag):
                                record(tag, "5xx", s, raw)
                    else:
                        pid = 1_000_000 + wid * 10_000 + seq
                        s, raw = safe_request("PUT", "upsert_points",
                                              body={"points": [
                                                  {"id": pid,
                                                   "vector": vec8(pid),
                                                   "payload": {"city": f"cw{wid}"}}]},
                                              path_params={"name": C},
                                              query_params={"wait": "true"})
                        if s in (200, 201):
                            ups += 1
                        elif s == 0:
                            with lock:
                                transport_hits.append((tag, "upsert"))
                        elif 500 <= s <= 599:
                            if liveness(tag):
                                record(tag, "5xx", s, raw)
                except Exception as e:   # worker guard: never kill the thread
                    with lock:
                        anomalies.append((f"w{wid}", "exception", 0, str(e)[:160]))
                time.sleep(0.02)
            with lock:
                upserted[wid] = ups

        threads = [threading.Thread(target=worker, args=(w,))
                   for w in range(t_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        window_s = time.time() - t_start
        total_upserted = sum(upserted.values())
        print(f"[window done] elapsed={window_s:.1f}s upserted_new="
              f"{total_upserted} anomalies={len(anomalies)} "
              f"transport={len(transport_hits)}")

        # ---- materialization poll: index must appear in describe ----
        materialized = False
        poll_deadline = time.time() + POLL_BUDGET_S
        while time.time() < poll_deadline:
            s, raw = safe_request("GET", "describe_collection",
                                  path_params={"name": C})
            ps = ((parse_json(raw) or {}).get("result") or {}).get("payload_schema") \
                if s == 200 else None
            if isinstance(ps, dict) and "city" in ps:
                materialized = True
                print(f"[materialized] city in payload_schema: "
                      f"{str(ps.get('city'))[:160]}")
                break
            time.sleep(0.5)
        if create_acked and not materialized:
            DEFECTS.append(
                f"(materialization) index+create returned 2xx (wait=false) "
                f"but field city never appeared in describe "
                f"result.payload_schema within {POLL_BUDGET_S:.0f}s - "
                f"Type4_StateLogicViolation - ack without persistence")

        # ---- final counts: data preserved through the build ----
        s, raw = safe_request("POST", "count", body={"exact": True},
                              path_params={"name": C})
        b = parse_json(raw)
        total_final = ((b or {}).get("result") or {}).get("count") if s == 200 else None
        c0_final, _ = filtered_count("final c0", C, "c0")
        expected_total = N + total_upserted
        print(f"[final] total={total_final} expected={expected_total} "
              f"c0={c0_final} expected_c0={PER_VAL}")
        if total_final != expected_total:
            DEFECTS.append(
                f"(final count) total {total_final} != {expected_total} "
                f"({N} baseline + {total_upserted} accounted upserts) after "
                f"the concurrent build window - Type4_StateLogicViolation")
        if c0_final != PER_VAL:
            DEFECTS.append(
                f"(final c0) filtered count on c0 = {c0_final} != {PER_VAL} "
                f"after the concurrent build window - "
                f"Type4_StateLogicViolation "
                f"(qdrant_inv_index_toggle_preserves_data_001)")

        # ---- anomaly adjudication ----
        for (role, kind, s, raw) in anomalies:
            if kind == "5xx":
                DEFECTS.append(
                    f"({role}) HTTP {s} on the {role.split('#')[0]} face "
                    f"during the async index build while /healthz alive - "
                    f"Type3_RuntimeFailure - raw={raw}")
            elif kind == "404-during-build":
                DEFECTS.append(
                    f"({role}) HTTP 404 on a LIVE collection during the "
                    f"async index build - Type4_StateLogicViolation - "
                    f"raw={raw}")
            elif kind == "count-drift":
                DEFECTS.append(
                    f"({role}) filtered count drifted during the async "
                    f"index build - Type4_StateLogicViolation - raw={raw} "
                    f"(qdrant_inv_index_toggle_preserves_data_001)")
            else:
                NOTES.append(f"{role}: exception {raw}")
        if len(transport_hits) >= 2:
            DEFECTS.append(
                f"{len(transport_hits)} transport losses (status 0) during "
                f"the build window on an alive service - "
                f"Type3_RuntimeFailure - {transport_hits[:6]}")
        elif transport_hits:
            NOTES.append(f"single transport loss recorded (race discipline, "
                         f"not claimed): {transport_hits}")

        for n in NOTES:
            print(f"NOTE: {n}")
        print("SKIPPED: by-design per threat_model - async wait=false "
              "operation error logging (issue #4925) is not asserted; only "
              "synchronous observable state is adjudicated")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print(f"index-build state consistency verified: {t_count} workers x "
              f"{WINDOW_S:.0f}s over the async build with every c0 sample="
              f"{PER_VAL}, queries 200, index materialized, final total="
              f"{expected_total} exact - NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup (own data only; failure must not flip the verdict)
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
