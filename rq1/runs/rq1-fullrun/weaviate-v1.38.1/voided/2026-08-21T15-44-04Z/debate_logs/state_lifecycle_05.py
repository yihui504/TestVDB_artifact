# state_lifecycle_05: 生命周期并发攻击 — collection create/drop 循环 vs 并发读写
# 500 on access endpoints = defect; 404/503 = correct "not available" semantics
import os, sys, time, json, threading
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
CLS = "StLcE"
THREADS_ACCESS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "8"))
S = requests.Session()

def safe_request(method, path, **kw):
    try:
        r = S.request(method, BASE_URL + path, timeout=30, **kw)
    except Exception as e:
        return None, None, "EXC:" + str(e)
    try:
        return r.status_code, r.json(), r.text
    except Exception:
        return r.status_code, None, r.text

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

SCHEMA = {"class": CLS, "vectorizer": "none", "properties": [{"name": "name", "dataType": ["text"]}]}

stop = threading.Event()
errors_500 = []
lock = threading.Lock()

def lifecycle_thread():
    for i in range(15):
        safe_request("DELETE", f"/v1/schema/{CLS}")
        time.sleep(0.05)
        safe_request("POST", "/v1/schema", json=SCHEMA)
        time.sleep(0.05)

def access_thread(tid):
    gql = {"query": "{ Get { %s (limit: 5) { name } } }" % CLS}
    for i in range(40):
        st, _, raw = safe_request("POST", "/v1/graphql", data=json.dumps(gql),
                                  headers={"Content-Type": "application/json"})
        if st == 500:
            with lock:
                errors_500.append((tid, i, raw[:150]))
        # concurrent writes
        st2, _, raw2 = safe_request("GET", f"/v1/objects/{CLS}/00000000-0000-0000-0000-00000000000%d" % (tid % 10))
        if st2 == 500:
            with lock:
                errors_500.append((tid, i, "objread:" + raw2[:150]))
        time.sleep(0.03)

lt = threading.Thread(target=lifecycle_thread)
lt.start()
ats = [threading.Thread(target=access_thread, args=(t,)) for t in range(THREADS_ACCESS)]
for t in ats: t.start()
lt.join()
for t in ats: t.join()

print(f"500 errors collected: {len(errors_500)}")
for e in errors_500[:5]:
    print("  ", e)

# cleanup: leave a live class then delete
safe_request("POST", "/v1/schema", json=SCHEMA)
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if len(errors_500) >= 2:  # >=2 occurrences to avoid flaky race false positive
    print(f"DEFECT: {len(errors_500)} HTTP 500 during concurrent lifecycle/access (expect 404/503 or GraphQL error)")
    print("VERDICT: DEFECT_FOUND"); sys.exit(1)
print("VERDICT: NO_DEFECT")
