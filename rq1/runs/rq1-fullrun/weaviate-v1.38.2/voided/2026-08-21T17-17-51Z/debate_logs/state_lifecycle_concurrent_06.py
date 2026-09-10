# Attack: lifecycle concurrency — schema create/delete cycle vs concurrent reads/writes (lifecycle_concurrent, BS-03)
# Defect signal: 500/panic during transient non-existence (should be 404); residual data after final recreate.
import os, sys, time, threading
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)

def safe_request(method, path, **kw):
    try:
        r = requests.request(method, BASE + path, timeout=15, **kw)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, str(e)

CLS = "StateLife06"
SCHEMA = {"class": CLS, "vectorizer": "none", "properties": [{"name": "name", "dataType": ["text"]}]}
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

stop = threading.Event()
server_errors = []
read_failures = []

def lifecycle():
    for _ in range(8):
        safe_request("POST", "/v1/schema", json=SCHEMA)
        time.sleep(0.3)
        safe_request("DELETE", f"/v1/schema/{CLS}")
        time.sleep(0.3)
    stop.set()

def reader():
    while not stop.is_set():
        s, b, raw = safe_request("GET", f"/v1/objects/{CLS}?limit=1")
        if s >= 500 or s == -1:
            server_errors.append((s, raw[:120]))
        time.sleep(0.05)

def writer():
    while not stop.is_set():
        s, b, raw = safe_request("POST", "/v1/graphql", json={"query": f"{{ Aggregate {{ {CLS} {{ meta {{ count }} }} }} }}"})
        if s >= 500 or s == -1:
            server_errors.append(("graphql", s, raw[:120]))
        time.sleep(0.05)

lt = threading.Thread(target=lifecycle)
r1 = threading.Thread(target=reader)
r2 = threading.Thread(target=writer)
r1.start(); r2.start(); lt.start()
lt.join(); r1.join(); r2.join()
print("server_errors:", len(server_errors), server_errors[:3])

# final state: ensure class exists, insert 3, count must be 3 (no residue)
safe_request("POST", "/v1/schema", json=SCHEMA)
time.sleep(1)
import uuid
for i in range(3):
    safe_request("POST", "/v1/objects", json={"class": CLS, "id": str(uuid.uuid4()),
        "properties": {"name": f"x{i}"}, "vector": [0.1, 0.2]})
count = None
for _ in range(10):
    time.sleep(1)
    s, b, raw = safe_request("POST", "/v1/graphql", json={"query": f"{{ Aggregate {{ {CLS} {{ meta {{ count }} }} }} }}"})
    try:
        count = b["data"]["Aggregate"][CLS][0]["meta"]["count"]
        break
    except Exception:
        pass
print(f"final count={count} expected=3")

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if server_errors:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 5xx during lifecycle churn: {server_errors[:3]}")
    sys.exit(1)
if count != 3:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — residual/mismatched count {count} != 3")
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
