# Attack: state_invariants weaviate_state_object_count_001 / collection_creation_001 (count_consistency)
# Blindspot: N/A. Target: weaviate v1.38.2 REST
import os, sys, json, time, uuid
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
S = requests.Session()

def safe_request(method, path, **kw):
    try:
        r = S.request(method, BASE + path, timeout=30, **kw)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, str(e)

CLS = "StateCount01"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

schema = {"class": CLS, "vectorizer": "none", "properties": [
    {"name": "name", "dataType": ["text"]}]}
s, b, raw = safe_request("POST", "/v1/schema", json=schema)
print("create:", s, raw[:200])
if s not in (200, 201):
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)

# invariant 1: creation -> queryable
s, b, raw = safe_request("GET", f"/v1/schema/{CLS}")
print("get schema:", s, raw[:200])
if s != 200:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — created class not queryable, status %d" % s)
    sys.exit(1)

N = 50
objs = [{"class": CLS, "id": str(uuid.uuid4()), "properties": {"name": f"n{i}"}, "vector": [0.1, 0.2]} for i in range(N)]
s, b, raw = safe_request("POST", "/v1/batch/objects", json={"objects": objs})
print("batch:", s, raw[:300])
if s not in (200, 201):
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
if isinstance(b, list):
    bad = [x for x in b if x.get("result", {}).get("status") not in ("SUCCESS",)]
    print("batch reported failures:", len(bad))

q = {"query": f"{{ Aggregate {{ {CLS} {{ meta {{ count }} }} }} }}"}
count = None
for _ in range(10):
    time.sleep(1)
    s, b, raw = safe_request("POST", "/v1/graphql", json=q)
    print("count raw:", raw[:200])
    try:
        count = b["data"]["Aggregate"][CLS][0]["meta"]["count"]
        break
    except Exception:
        pass
if count is None:
    print("VERDICT: SCRIPT_ERROR — could not read count"); sys.exit(2)
print(f"count={count} expected={N}")
if count != N:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — count {count} != inserted {N}")
    sys.exit(1)

# delete one, re-check
s, b, raw = safe_request("GET", f"/v1/objects/{CLS}?limit=1")
try:
    oid = b["objects"][0]["id"]
except Exception:
    oid = objs[0]["id"]
s, _, raw = safe_request("DELETE", f"/v1/objects/{CLS}/{oid}")
print("delete obj:", s)
time.sleep(2)
s, b, raw = safe_request("POST", "/v1/graphql", json=q)
try:
    count = b["data"]["Aggregate"][CLS][0]["meta"]["count"]
except Exception:
    count = None
print(f"count_after_delete={count} expected={N-1}")
if count != N - 1:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — after delete count {count} != {N-1}")
    sys.exit(1)

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass
print("VERDICT: NO_DEFECT")
sys.exit(0)
