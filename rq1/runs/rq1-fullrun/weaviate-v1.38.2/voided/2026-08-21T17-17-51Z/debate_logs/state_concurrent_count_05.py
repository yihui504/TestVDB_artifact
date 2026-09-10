# Attack: concurrent inserts — final count consistency (concurrent, BS-03)
import os, sys, uuid, time, threading
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
THREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))
PER = 5

def safe_request(method, path, **kw):
    try:
        r = requests.request(method, BASE + path, timeout=30, **kw)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, str(e)

CLS = "StateConc05"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass
s, _, raw = safe_request("POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["text"]}]})
print("create:", s)

errors = []
def worker(tid):
    for j in range(PER):
        st, b, raw = safe_request("POST", "/v1/objects", json={
            "class": CLS, "id": str(uuid.uuid4()), "properties": {"name": f"t{tid}j{j}"},
            "vector": [0.1, 0.2]})
        if st not in (200, 201):
            errors.append((tid, j, st, raw[:100]))

ts = [threading.Thread(target=worker, args=(i,)) for i in range(THREADS)]
for t in ts: t.start()
for t in ts: t.join()
print("write errors:", len(errors), errors[:3])

expected = THREADS * PER
count = None
for _ in range(15):
    time.sleep(1)
    s, b, raw = safe_request("POST", "/v1/graphql", json={"query": f"{{ Aggregate {{ {CLS} {{ meta {{ count }} }} }} }}"})
    try:
        count = b["data"]["Aggregate"][CLS][0]["meta"]["count"]
        break
    except Exception:
        pass
print(f"count={count} expected={expected}")

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if errors and any(e[2] >= 500 or e[2] == -1 for e in errors):
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 5xx/connection errors under concurrency: {errors[:3]}")
    sys.exit(1)
if count != expected:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — count {count} != {expected}")
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
