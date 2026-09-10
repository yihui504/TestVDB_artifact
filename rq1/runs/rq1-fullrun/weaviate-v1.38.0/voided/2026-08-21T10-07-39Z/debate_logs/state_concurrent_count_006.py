# state_concurrent_count_006 — concurrent batch inserts + interleaved deletes: count consistency
# Attack: count_consistency (Strategy 4 concurrency) — Blindspot BS-03
import os, sys, time, threading, requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE = BASE.rstrip("/") + "/v1"
THREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))

S = requests.Session()
S_lock = threading.Lock()

def safe_request(method, path, body=None):
    try:
        r = S.request(method, BASE + path, json=body, timeout=120)
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, r.text
    except Exception as e:
        return -1, None, str(e)

CLS = "StC006"
CLS_BODY = {"class": CLS, "vectorizer": "none",
            "properties": [{"name": "name", "dataType": ["text"]}]}

safe_request("DELETE", f"/schema/{CLS}")
time.sleep(1)
s, b, raw = safe_request("POST", "/schema", CLS_BODY)
print("create:", s); assert s in (200, 201)

def oid(batch, i):
    return f"66666666-6666-6666-6666-{batch:03d}{i:09d}"

PER = 10
errors = []

def insert_batch(batch_id):
    objs = [{"class": CLS, "id": oid(batch_id, i),
             "properties": {"name": f"b{batch_id}i{i}"}, "vector": [0.1, 0.2]}
            for i in range(PER)]
    s, b, raw = safe_request("POST", "/batch/objects", {"objects": objs})
    if s != 200:
        errors.append(f"batch {batch_id}: HTTP {s} {raw[:100]}")
        return
    results = b if isinstance(b, list) else (b or {}).get("objects", [])
    for r in results:
        st = (r or {}).get("result", {}).get("status")
        if st != "SUCCESS":
            errors.append(f"batch {batch_id}: obj status {st}")

ts = [threading.Thread(target=insert_batch, args=(t,)) for t in range(THREADS)]
[t.start() for t in ts]; [t.join() for t in ts]
print(f"insert phase done: {THREADS}x{PER}, errors={errors}")
time.sleep(2)

# count via graphql aggregate
q = '{"query":"{ Aggregate { StC006 { meta { count } } } }"}'
r = S.post(BASE + "/graphql", data=q, headers={"Content-Type": "application/json"})
try:
    count = r.json()["data"]["Aggregate"][CLS][0]["meta"]["count"]
except Exception:
    count = None
print("aggregate count after concurrent inserts:", count, "expected:", THREADS * PER)

defect = False
if errors:
    print(f"DEFECT Type3: concurrent insert errors: {errors[:5]}"); defect = True
if count != THREADS * PER:
    print(f"DEFECT Type4: count {count} != {THREADS * PER}"); defect = True

# concurrent read + delete interleaving: delete half of batch 0's objects while reading
def deleter():
    for i in range(PER // 2):
        s, b, raw = safe_request("DELETE", f"/objects/{CLS}/{oid(0, i)}")
        if s >= 500:
            errors.append(f"delete 5xx: {s} {raw[:80]}")

def reader():
    for _ in range(20):
        s, b, raw = safe_request("GET", f"/objects?class={CLS}&limit=100")
        if s >= 500:
            errors.append(f"list 5xx: {s} {raw[:80]}")

t1, t2 = threading.Thread(target=deleter), threading.Thread(target=reader)
t1.start(); t2.start(); t1.join(); t2.join()
time.sleep(2)

r = S.post(BASE + "/graphql", data=q, headers={"Content-Type": "application/json"})
try:
    count2 = r.json()["data"]["Aggregate"][CLS][0]["meta"]["count"]
except Exception:
    count2 = None
expected2 = THREADS * PER - PER // 2
print("count after interleaved deletes:", count2, "expected:", expected2)
if count2 != expected2:
    print(f"DEFECT Type4: post-delete count {count2} != {expected2}"); defect = True
# deleted ids must 404; survivors must exist
for i in range(PER // 2):
    s, _, _ = safe_request("GET", f"/objects/{CLS}/{oid(0, i)}")
    if s != 404:
        print(f"DEFECT Type4: deleted obj {i} GET={s}"); defect = True
s, _, _ = safe_request("GET", f"/objects/{CLS}/{oid(1, 0)}")
print("survivor check:", s)
if s != 200:
    print("DEFECT Type4: survivor object missing"); defect = True

try:
    safe_request("DELETE", f"/schema/{CLS}")
except Exception:
    pass

print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
