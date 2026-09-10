# script_id: state_collections_create_002
# strategy: concurrent (模式 B 重复创建 × 并发版)
# endpoint: collections+create
# Attack: qdrant_state_collections_create_001 (并发重复创建 — create/create race on same name)
#   策略7 变体：collection 级 lifecycle 并发（create vs create）
# constraint_ids: qdrant_state_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness
"""
State: N threads concurrently PUT /collections/{same_name} with identical body.
Expected: exactly one 2xx; all others rejected with clean 4xx (409/400).
Defect signals: any 500/panic, or collection ends in broken state
(describe returns non-2xx or status not in green/yellow/red), or >1 success
(corrupts concurrent-create invariant).
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
COLL = f"st_cc_race_{TS}"
N = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))
BODY = {"vectors": {"size": 4, "distance": "Cosine"}}
results = []
lock = threading.Lock()

def creator(i):
    st, _, raw = safe_request("PUT", f"/collections/{COLL}", json=BODY)
    with lock:
        results.append((i, st, raw[:150]))

def cleanup():
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except Exception:
        pass

try:
    threads = [threading.Thread(target=creator, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i, st, raw in sorted(results):
        print(f"thread {i}: {st} {raw}")

    statuses = [st for _, st, _ in results]
    successes = [s for s in statuses if s in (200, 201)]
    internal = [s for s in statuses if s >= 500 or s == 0]

    if internal:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — concurrent duplicate create produced 5xx/connection errors: {internal}")
        sys.exit(1)
    if len(successes) != 1:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — expected exactly 1 success under concurrent create, got {len(successes)}: {statuses}")
        sys.exit(1)

    # final state must be intact
    st, body, raw = safe_request("GET", f"/collections/{COLL}")
    print(f"describe: {st} {raw[:200]}")
    try:
        cstatus = body["result"]["status"]
    except (TypeError, KeyError):
        cstatus = None
    if st != 200 or cstatus not in ("green", "yellow", "red"):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — collection broken after concurrent create race: status={cstatus}")
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
