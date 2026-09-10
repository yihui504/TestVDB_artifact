# script_id: state_collections_delete_004
# strategy: concurrent
# endpoint: collections+delete
# Attack: qdrant_state_collections_delete_001 × 策略7 生命周期并发攻击 (collection 级 lifecycle vs 并发访问)
#   覆盖: DELETE/recreate 同名循环期间，并发 query/count/upsert 访问不得出现 500/panic/连接重置
#   (应为 404 集合暂不存在 / 200 正常)；竞态结束后状态机必须健康(可确定性重建+计数)
# constraint_ids: qdrant_state_collections_delete_001, qdrant_inv_collection_gone_after_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness
"""
Lifecycle race: thread A loops DELETE -> recreate same collection; access threads
hammer query / count / upsert concurrently. Expected per access call: 200 or 404.
Defect signals (census >= 2 events to avoid single-race false positive):
  - 5xx response on any access call (should be 404 while collection absent)  -> Type3
  - transport failure (status 0, connection reset)                            -> Type3
Post-race: collection is recreated fresh; upsert 25 ids; exact count must be 25.
"""
import requests, json, sys, os, time, threading

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")

def safe_request(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else {}
        except (json.JSONDecodeError, ValueError):
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        return 0, None, str(e)

TS = str(int(time.time()))
COLL = f"st_cdel_lc_{TS}"
DIM = 4
N_ACCESS = max(2, min(10, int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))))
CYCLES = 8
ITERS = 40
error_events = []          # (kind, status, raw) for 5xx / transport failures
lock = threading.Lock()

def note_error(kind, status, raw):
    with lock:
        error_events.append((kind, status, (raw or "")[:160]))

def lifecycle_thread():
    for _ in range(CYCLES):
        st, _, raw = safe_request("DELETE", f"/collections/{COLL}")
        if st >= 500 or st == 0:
            note_error("lifecycle_delete", st, raw)
        time.sleep(0.05)
        st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                                  json={"vectors": {"size": DIM, "distance": "Cosine"}})
        if st >= 500 or st == 0:
            note_error("lifecycle_create", st, raw)
        elif st not in (200, 201, 409):
            print(f"OBSERVATION lifecycle create status {st}: {(raw or '')[:120]}")
        time.sleep(0.05)

def access_thread(tid):
    for i in range(ITERS):
        # query
        st, _, raw = safe_request("POST", f"/collections/{COLL}/points/query",
                                  json={"query": [0.1] * DIM, "limit": 3})
        if st >= 500 or st == 0:
            note_error(f"query[t{tid}]", st, raw)
        # count
        st, _, raw = safe_request("POST", f"/collections/{COLL}/points/count", json={"exact": True})
        if st >= 500 or st == 0:
            note_error(f"count[t{tid}]", st, raw)
        # upsert small batch
        if i % 2 == 0:
            pts = [{"id": tid * 1000 + i, "vector": [0.1] * DIM} for _ in range(1)]
            pts[0]["id"] = tid * 1000 + i
            st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true", json={"points": pts})
            if st >= 500 or st == 0:
                note_error(f"upsert[t{tid}]", st, raw)
        time.sleep(0.03)

def cleanup():
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except Exception:
        pass

try:
    # initial create + seed
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"initial create: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    seed = [{"id": i, "vector": [0.1 * (i + 1)] * DIM} for i in range(20)]
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true", json={"points": seed})
    print(f"seed upsert: {st} {raw[:150]}")

    threads = [threading.Thread(target=lifecycle_thread)]
    for tid in range(N_ACCESS):
        threads.append(threading.Thread(target=access_thread, args=(tid,)))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    time.sleep(1)

    print(f"ERROR_CENSUS: {len(error_events)} events (threshold for DEFECT: 2)")
    for ev in error_events[:20]:
        print(f"  error_event: {ev}")

    # post-race deterministic state-machine check: clean -> recreate -> seed -> count
    cleanup()
    time.sleep(0.3)
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"post-race recreate: {st} {raw[:150]}")
    if st not in (200, 201):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — post-race recreate failed {st}: {raw[:150]}")
        sys.exit(1)
    pts = [{"id": i, "vector": [0.05 * (i + 1)] * DIM} for i in range(25)]
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true", json={"points": pts})
    print(f"post-race upsert: {st} {raw[:150]}")
    time.sleep(0.5)
    st, body, raw = safe_request("POST", f"/collections/{COLL}/points/count", json={"exact": True})
    print(f"post-race count: {st} {raw[:200]}")
    c = None
    if isinstance(body, dict) and isinstance(body.get("result"), dict):
        c = body["result"].get("count")
    if c != 25:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — post-race count expected 25, got {c}")
        sys.exit(1)

    if len(error_events) >= 2:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {len(error_events)} 5xx/transport errors during lifecycle race (>=2 confirms)")
        sys.exit(1)
    if len(error_events) == 1:
        print("OBSERVATION: single 5xx/transport event (below confirmation threshold 2); not reported as defect")

    print("VERDICT: NO_DEFECT")
    sys.exit(0)
except SystemExit:
    raise
except Exception as e:
    print(f"UNEXPECTED_ERROR: {e}")
    print("VERDICT: SCRIPT_ERROR")
    sys.exit(2)
finally:
    cleanup()
