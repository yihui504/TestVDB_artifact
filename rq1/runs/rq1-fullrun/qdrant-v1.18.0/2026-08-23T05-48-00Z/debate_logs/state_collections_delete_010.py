# script_id: state_collections_delete_010
# strategy: concurrent
# endpoint: collections+delete
# Attack: qdrant_state_collections_delete_001 × 策略7 变体 (DELETE 与持续写入竞态)
#   覆盖: 多 writer 线程持续 upsert（wait=false 保持压力，避开 wait=false 错误不记录的 by-design）
#   期间 DELETE collection；writer 后续响应应为 200 或 404（500/连接重置 census>=2 = Type3）；
#   DELETE 后 settle：GET 必须 404；同名 recreate 后 count 必须 0（in-flight WAL 写入不得在删除后复活）
# constraint_ids: qdrant_state_collections_delete_001, qdrant_inv_collection_gone_after_delete_001,
#   qdrant_inv_count_after_upsert_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness (writes racing collection removal —
#   the closest in-process proxy for "WAL replay resurrects deleted points")
"""
Delete-under-write: writers keep upserting while the collection is deleted.
Accepted writer responses: 200 (before removal lands) or 404 (after).
Defect: 5xx/transport census >= 2 -> Type3; zombie GET after settle -> Type4;
points reappearing in a same-name recreate -> Type4 (delayed-write resurrection).
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
COLL = f"st_cdel_duw_{TS}"
DIM = 8
N_WRITERS = max(2, min(10, int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))))
WRITER_ITERS = 60
error_events = []
status_hist = {}
lock = threading.Lock()
stop_flag = threading.Event()

def note(kind, st, raw):
    with lock:
        error_events.append((kind, st, (raw or "")[:160]))

def tally(st):
    with lock:
        status_hist[st] = status_hist.get(st, 0) + 1

def writer(tid):
    i = 0
    while not stop_flag.is_set() and i < WRITER_ITERS:
        pts = [{"id": tid * 100000 + i * 10 + k, "vector": [0.02 * (k + 1)] * DIM} for k in range(5)]
        st, _, raw = safe_request("PUT", f"/collections/{COLL}/points", json={"points": pts})
        tally(st)
        if st >= 500 or st == 0:
            note(f"upsert[t{tid}.{i}]", st, raw)
        i += 1
        time.sleep(0.01)

def cleanup():
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except Exception:
        pass

try:
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"create: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    seed = [{"id": i, "vector": [0.1] * DIM} for i in range(20)]
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true", json={"points": seed})
    print(f"seed: {st} {raw[:150]}")

    writers = [threading.Thread(target=writer, args=(t,)) for t in range(N_WRITERS)]
    for t in writers:
        t.start()

    # let writes get going, then delete mid-flight
    time.sleep(1.0)
    st, _, raw = safe_request("DELETE", f"/collections/{COLL}")
    print(f"delete under write: {st} {raw[:200]}")
    if st >= 500 or st == 0:
        note("delete", st, raw)

    # keep writers running a bit past the delete, then stop
    time.sleep(1.5)
    stop_flag.set()
    for t in writers:
        t.join()
    time.sleep(2)

    print(f"writer status histogram: {status_hist}")
    print(f"ERROR_CENSUS: {len(error_events)} (threshold 2)")
    for ev in error_events[:20]:
        print(f"  error_event: {ev}")

    # zombie check after settle (double sample 2s apart)
    for sample in range(2):
        st, _, raw = safe_request("GET", f"/collections/{COLL}")
        print(f"zombie check {sample}: GET={st} {raw[:150]}")
        if st == 200:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — collection resurrected/existed after DELETE under write load")
            sys.exit(1)
        if st >= 500 or st == 0:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — GET after delete got {st}: {raw[:150]}")
            sys.exit(1)
        if sample == 0:
            time.sleep(2)

    # same-name recreate: in-flight WAL writes must not resurrect any point
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"recreate: {st} {raw[:150]}")
    if st not in (200, 201):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — recreate after delete-under-write failed {st}: {raw[:150]}")
        sys.exit(1)
    time.sleep(1.0)
    st, body, raw = safe_request("POST", f"/collections/{COLL}/points/count", json={"exact": True})
    print(f"count after recreate: {st} {raw[:200]}")
    c = None
    if isinstance(body, dict) and isinstance(body.get("result"), dict):
        c = body["result"].get("count")
    if c != 0:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {c} points resurrected in recreated collection (delayed-write resurrection)")
        sys.exit(1)

    if len(error_events) >= 2:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {len(error_events)} 5xx/transport errors during delete-under-write (>=2 confirms)")
        sys.exit(1)
    if len(error_events) == 1:
        print("OBSERVATION: single 5xx/transport event (below threshold 2)")

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
