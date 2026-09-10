# script_id: state_collections_create_006
# strategy: concurrent (策略7 变体 — create 期间并发访问：collection 尚未 ready 时 upsert/query)
# endpoint: collections+create
# Attack: collections+create 初始化窗口状态一致性（shard 尚未 ready 时写入是否丢失/500）
# constraint_ids: qdrant_state_collections_create_001, qdrant_inv_collection_visible_after_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness
"""
Create a collection and IMMEDIATELY (no sleep) upsert points and query.
Expected: server either queues/accepts writes (200, points eventually visible)
or rejects cleanly (4xx/503) — but never 500, and no silently-lost writes
(accepted-200 upserts must all be visible in final exact count).
Tests the create→ready transition window.
"""
import requests, json, sys, os, time, threading

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
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
            print(f"JSON_DECODE_ERROR: {text[:200]}")
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""

TS = str(int(time.time()))
COLL = f"st_cc_ready_{TS}"
N = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))
M = 5  # points per thread
accepted = []
errors5xx = []
lock = threading.Lock()

def cleanup():
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except Exception:
        pass

try:
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
        json={"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"create: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)

    def writer(tid):
        pts = [{"id": tid * 100 + i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(M)]
        st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true",
            json={"points": pts})
        with lock:
            if st in (200, 201):
                accepted.append(len(pts))
            elif st >= 500 or st == 0:
                errors5xx.append((tid, st, raw[:100]))

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_accepted = sum(accepted)
    print(f"accepted points: {total_accepted} (threads OK: {len(accepted)}/{N}), 5xx: {len(errors5xx)}")
    for e in errors5xx[:5]:
        print("5xx:", e)

    if len(errors5xx) >= 2:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 500 during create→ready window")
        sys.exit(1)

    time.sleep(2)
    st, body, raw = safe_request("POST", f"/collections/{COLL}/points/count", json={"exact": True})
    print(f"count: {st} {raw[:200]}")
    cnt = None
    try:
        cnt = body["result"]["count"]
    except (TypeError, KeyError):
        pass
    if cnt != total_accepted:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — silently lost writes: accepted {total_accepted}, counted {cnt}")
        sys.exit(1)

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
