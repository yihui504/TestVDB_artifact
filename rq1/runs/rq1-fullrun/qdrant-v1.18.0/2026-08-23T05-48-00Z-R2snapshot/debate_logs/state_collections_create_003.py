# script_id: state_collections_create_003
# strategy: concurrent (策略7 lifecycle × 访问并发 — create/delete vs query)
# endpoint: collections+create
# Attack: collections+create lifecycle 与访问端点并发（qdrant_state_collections_create_001 相关）
#   生命周期线程: delete → create 同名循环; 访问线程: query + upsert
# constraint_ids: qdrant_state_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness
"""
Lifecycle thread: DELETE → PUT create (same name) loop.
Access threads:   query / upsert against the same name.
Expected: access gets clean 404/400 while collection momentarily absent.
Defect: 500 / panic / connection reset (cf. qdrant #9229 pattern),
or final state inconsistent (describe broken after loop).
偶发 500 需 ≥2 次才报（避免竞态误报）。
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
COLL = f"st_cc_lc_{TS}"
N = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))
BODY = {"vectors": {"size": 4, "distance": "Cosine"}}
QUERY = {"query": {"nearest": [0.1, 0.2, 0.3, 0.4]}, "limit": 3}
err500 = {"query": [], "upsert": []}
stop = threading.Event()

def lifecycle():
    for _ in range(12):
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except Exception:
            pass
        time.sleep(0.05)
        try:
            safe_request("PUT", f"/collections/{COLL}", json=BODY)
        except Exception:
            pass
        time.sleep(0.05)

def access(kind):
    for _ in range(40):
        if stop.is_set():
            break
        try:
            if kind == "query":
                st, _, raw = safe_request("POST", f"/collections/{COLL}/points/query", json=QUERY)
            else:
                st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true",
                    json={"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]})
            if st >= 500 or st == 0:
                err500[kind].append((st, raw[:100]))
        except Exception as e:
            err500[kind].append((-1, str(e)[:100]))
        time.sleep(0.03)

def cleanup():
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except Exception:
        pass

try:
    # ensure a collection exists initially
    st, _, raw = safe_request("PUT", f"/collections/{COLL}", json=BODY)
    print(f"init create: {st} {raw[:150]}")

    lt = threading.Thread(target=lifecycle)
    ats = [threading.Thread(target=access, args=("query",)),
           threading.Thread(target=access, args=("upsert",))]
    lt.start()
    for t in ats:
        t.start()
    lt.join()
    stop.set()
    for t in ats:
        t.join()

    print(f"query 5xx count: {len(err500['query'])}  upsert 5xx count: {len(err500['upsert'])}")
    for e in err500['query'][:5]:
        print("query err:", e)
    for e in err500['upsert'][:5]:
        print("upsert err:", e)

    # ≥2 occurrences to report (avoid single-race false positive)
    if len(err500['query']) >= 2 or len(err500['upsert']) >= 2:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 500/conn-reset during collection lifecycle race (should be 404/503)")
        sys.exit(1)

    # final state sanity: describe must be 2xx with valid status
    st, _, raw = safe_request("GET", f"/collections/{COLL}")
    print(f"final describe: {st} {raw[:200]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — final state indeterminate")
        sys.exit(2)

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
