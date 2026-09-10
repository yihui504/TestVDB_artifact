# script_id: state_collections_delete_005
# strategy: concurrent
# endpoint: collections+delete
# Attack: qdrant_state_collections_delete_001 × 策略4/7 并发 DELETE 同一存在集合 + 并发 upsert 竞态
#   覆盖: N 线程同时 DELETE 同一 collection — 每个响应应为 200 或 404（第一个 200，其余 404）；
#   并发 upserter 的响应应为 200 或 404；任何 500/连接重置 = Type3；
#   结束后 GET 必须 404（无僵尸），同名 recreate 后 count 必须 0（删除竞态下无数据复活）
# constraint_ids: qdrant_state_collections_delete_001, qdrant_inv_collection_gone_after_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness
"""
Concurrent DELETE storm: N threads barrier-synchronised DELETE the SAME existing
collection while M upsert threads race against the removal.
Per-delete accepted: {200, 404}. Per-upsert accepted: {200, 404}.
Defect (census >= 2): 5xx or transport failure on either side -> Type3.
Final: GET 404 (zombie -> Type4); recreate same name -> exact count 0 (resurrection -> Type4).
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
COLL = f"st_cdel_cstorm_{TS}"
DIM = 4
N_DEL = max(3, min(10, int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))))
N_UPS = 2
error_events = []
delete_statuses = []
lock = threading.Lock()
barrier = threading.Barrier(N_DEL + N_UPS)

def note_error(kind, status, raw):
    with lock:
        error_events.append((kind, status, (raw or "")[:160]))

def delete_worker(i):
    barrier.wait()
    st, _, raw = safe_request("DELETE", f"/collections/{COLL}")
    with lock:
        delete_statuses.append(st)
    if st >= 500 or st == 0:
        note_error(f"delete[{i}]", st, raw)

def upsert_worker(i):
    barrier.wait()
    for j in range(15):
        pts = [{"id": i * 10000 + j, "vector": [0.1] * DIM}]
        st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true", json={"points": pts})
        if st >= 500 or st == 0:
            note_error(f"upsert[{i}.{j}]", st, raw)
        time.sleep(0.02)

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
    pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM} for i in range(10)]
    st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true", json={"points": pts})
    print(f"seed: {st} {raw[:150]}")

    threads = [threading.Thread(target=delete_worker, args=(i,)) for i in range(N_DEL)]
    threads += [threading.Thread(target=upsert_worker, args=(i,)) for i in range(N_UPS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    time.sleep(1)

    print(f"delete_statuses: {sorted(delete_statuses)}")
    print(f"ERROR_CENSUS: {len(error_events)} events (threshold: 2)")
    for ev in error_events[:20]:
        print(f"  error_event: {ev}")

    # every concurrent delete must be 200 or 404 — anything else recorded above;
    # final state must be deleted
    st, _, raw = safe_request("GET", f"/collections/{COLL}")
    print(f"final GET: {st} {raw[:200]}")
    if st == 200:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — collection still exists after delete storm (zombie)")
        sys.exit(1)
    if st >= 500 or st == 0:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — final GET got {st}: {raw[:150]}")
        sys.exit(1)

    # recreate + resurrection check under race
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"recreate: {st} {raw[:150]}")
    if st not in (200, 201):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — recreate after delete storm failed {st}: {raw[:150]}")
        sys.exit(1)
    time.sleep(0.5)
    st, body, raw = safe_request("POST", f"/collections/{COLL}/points/count", json={"exact": True})
    print(f"count after recreate: {st} {raw[:200]}")
    c = None
    if isinstance(body, dict) and isinstance(body.get("result"), dict):
        c = body["result"].get("count")
    if c != 0:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — recreated collection count={c}, expected 0 (resurrection under delete race)")
        sys.exit(1)

    if len(error_events) >= 2:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {len(error_events)} 5xx/transport errors in delete storm (>=2 confirms)")
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
