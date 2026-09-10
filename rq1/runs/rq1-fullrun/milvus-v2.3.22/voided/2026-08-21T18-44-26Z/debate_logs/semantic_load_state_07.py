# Attack: load lifecycle state machine + topk truncation
# contracts milvus_inv_load_lifecycle + milvus_state_release_001 + milvus_state_search_001
# source: https://github.com/milvus-io/milvus/blob/v2.3.22/internal/distributed/proxy/httpserver/handler_v2.go doc_version v2.3.22
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}
DIM = 4
COL = "testvdb_sem_load_07"

def safe_request(method, endpoint, json=None, timeout=25):
    try:
        r = requests.request(method, f"{BASE_URL}{endpoint}", json=json, headers=H, timeout=timeout)
        try: body = r.json()
        except Exception: body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)

def ok(b): return isinstance(b, dict) and b.get("code") == 200

def drop(name):
    try: safe_request("POST", "/v2/vectordb/collections/drop", json={"collectionName": name})
    except Exception: pass

drop(COL)
schema = {"fields": [
    {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
    {"fieldName": "vector", "dataType": "FloatVector", "elementTypeParams": {"dim": DIM}},
]}
s, b, r = safe_request("POST", "/v2/vectordb/collections/create",
    json={"collectionName": COL, "schema": schema, "indexParams": [
        {"fieldName": "vector", "indexName": "idx", "metricType": "L2", "params": {"index_type": "FLAT"}}]})
print("create:", s, r[:300])
if not (s == 200 and ok(b)):
    print("VERDICT: SCRIPT_ERROR - create failed"); sys.exit(2)

defects = []
# 1. before load: state should be NotLoad
time.sleep(2)
s, b, r = safe_request("POST", "/v2/vectordb/collections/get_load_state", json={"collectionName": COL})
print("state_before_load:", s, r[:300])
state = (b.get("data") or {}).get("loadState") if ok(b) else None
if state not in ("NotLoad", "NotExist", "Loading", "Loaded", "LoadStateNotLoad", "LoadStateNotExist", "LoadStateLoading", "LoadStateLoaded"):
    defects.append(f"invalid loadState {state!r} (Type4)")
elif state == "NotExist":
    defects.append("existing collection reported NotExist (Type4_StateLogicViolation)")
if str(state).endswith("Loaded"):
    print("OBSERVATION: explicit-schema collection auto-Loaded without explicit load call (v2 create+index path)")
    defects.append("explicit-schema collection auto-Loaded before load() call (Type4_StateLogicViolation: load is async/explicit per contract)")

# 2. load -> eventually Loaded
s, b, r = safe_request("POST", "/v2/vectordb/collections/load", json={"collectionName": COL})
print("load:", s, r[:200])
loaded = False
for _ in range(15):
    time.sleep(2)
    s, b, r = safe_request("POST", "/v2/vectordb/collections/get_load_state", json={"collectionName": COL})
    if ok(b):
        d = b.get("data") or {}
        print("  state:", d.get("loadState"), "progress:", d.get("loadProgress"))
        if str(d.get("loadState")).endswith("Loaded"):
            loaded = True
            prog = d.get("loadProgress")
            if isinstance(prog, int) and not (0 <= prog <= 100 or prog == -1):
                defects.append(f"loadProgress {prog} outside [0,100] (Type4)")
            break
if not loaded:
    print("WARN: never reached Loaded within 30s; continuing")

# 3. insert 5 rows, topk truncation: limit=3 -> exactly 3
s, b, r = safe_request("POST", "/v2/vectordb/entities/insert", json={"collectionName": COL, "data": [
    {"id": i, "vector": [float(i), 0.0, 0.0, 0.0]} for i in range(1, 6)]})
print("insert:", s, r[:200])
time.sleep(3)
s, b, r = safe_request("POST", "/v2/vectordb/entities/search",
    json={"collectionName": COL, "data": [[0.0, 0.0, 0.0, 0.0]], "limit": 3, "outputFields": ["id"]})
print("topk3:", s, r[:300])
if ok(b):
    hits = b.get("data") or []
    if len(hits) != 3:
        defects.append(f"limit=3 returned {len(hits)} hits (Type4 topk truncation)")
    ids = [h.get("id") for h in hits]
    if sorted(ids, key=lambda x: int(x)) != [1, 2, 3]:
        defects.append(f"top-3 by L2 from 0-vec should be ids 1,2,3 got {ids} (Type4)")
else:
    defects.append("search on Loaded collection failed")

# 4. offset+limit: offset=1 limit=2 -> ids 2,3
s, b, r = safe_request("POST", "/v2/vectordb/entities/search",
    json={"collectionName": COL, "data": [[0.0, 0.0, 0.0, 0.0]], "limit": 2, "offset": 1, "outputFields": ["id"]})
print("offset:", s, r[:300])
if ok(b):
    ids = sorted([h.get("id") for h in (b.get("data") or [])], key=lambda x: int(x))
    if ids != [2, 3]:
        defects.append(f"offset=1,limit=2 returned {ids}, expected [2,3] (Type4)")

# 5. release -> NotLoad; search then must fail
s, b, r = safe_request("POST", "/v2/vectordb/collections/release", json={"collectionName": COL})
print("release:", s, r[:200])
time.sleep(2)
s, b, r = safe_request("POST", "/v2/vectordb/collections/get_load_state", json={"collectionName": COL})
print("state_after_release:", s, r[:200])
state = (b.get("data") or {}).get("loadState") if ok(b) else None
if not str(state).endswith("NotLoad"):
    defects.append(f"after release loadState {state!r} != NotLoad (Type4_StateLogicViolation)")
s, b, r = safe_request("POST", "/v2/vectordb/entities/search",
    json={"collectionName": COL, "data": [[0.0, 0.0, 0.0, 0.0]], "limit": 1})
print("search_after_release:", s, r[:300])
code = b.get("code") if isinstance(b, dict) else None
if s == 200 and code == 200:
    defects.append("search on NotLoad collection succeeded (Type1_IllegalSuccess)")

drop(COL)
if defects:
    print("VERDICT: DEFECT_FOUND")
    for d in defects: print("-", d)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
