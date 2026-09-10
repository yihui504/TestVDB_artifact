# state_count_01: CRUD 后 COUNT 一致性（invariant weaviate_state_object_count_001）
# Attack: count_consistency on POST /objects + Aggregate COUNT graphql
import os, sys, time, uuid, json
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)

S = requests.Session()

def safe_request(method, path, **kw):
    try:
        r = S.request(method, BASE_URL + path, timeout=30, **kw)
    except Exception as e:
        return None, None, "EXC:" + str(e)
    body = None
    try:
        body = r.json()
    except Exception:
        pass
    return r.status_code, body, r.text

CLS = "StCntA"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

st = None
for _ in range(5):
    st, _, raw = safe_request("POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
        "properties": [{"name": "name", "dataType": ["text"]}]})
    if st in (200, 201):
        break
    time.sleep(0.5)
print("create class:", st, raw[:200])
if st not in (200, 201):
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
# wait until graphql schema knows the class
for _ in range(20):
    q = {"query": "{ Aggregate { %s { meta { count } } } }" % CLS}
    s1, b1, r1 = safe_request("POST", "/v1/graphql", data=json.dumps(q),
                              headers={"Content-Type": "application/json"})
    if s1 == 200 and "errors" not in (b1 or {}):
        break
    time.sleep(0.3)

N = 50
ok = 0
for i in range(N):
    st, _, raw = safe_request("POST", "/v1/objects", json={
        "class": CLS, "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"cnt-{i}")),
        "properties": {"name": f"obj{i}"}})
    if st in (200, 201):
        ok += 1
print(f"inserted ok={ok}/{N}")

# GraphQL Aggregate COUNT (with metadata _count on Get since pure Aggregate may lag inverted index)
def gql_count():
    q = {"query": "{ Aggregate { %s { meta { count } } } }" % CLS}
    st, body, raw = safe_request("POST", "/v1/graphql", data=json.dumps(q),
                                 headers={"Content-Type": "application/json"})
    try:
        return st, body["data"]["Aggregate"][CLS][0]["meta"]["count"], raw
    except Exception:
        return st, None, raw

def gql_get_count():
    q = {"query": "{ Get { %s (limit: 10000) { _additional { id } } } }" % CLS}
    st, body, raw = safe_request("POST", "/v1/graphql", data=json.dumps(q),
                                 headers={"Content-Type": "application/json"})
    try:
        return st, len(body["data"]["Get"][CLS]), raw
    except Exception:
        return st, None, raw

defect = None
# Poll up to 10s: count should converge to N
final_agg = None
for _ in range(20):
    st, agg, raw = gql_count()
    final_agg = agg
    if agg == N:
        break
    time.sleep(0.5)
print(f"Aggregate count final={final_agg} (raw last: {raw[:150]})")

st2, getc, raw2 = gql_get_count()
print(f"Get _count={getc}")

if ok == 0:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
if ok == N:
    if final_agg != N:
        defect = f"Aggregate COUNT={final_agg} != {N} after 10s convergence window"
    if getc not in (None, N) and getc != N:
        defect = f"Get returns {getc} objects, expected {N}"
    if getc == 0 and final_agg == 0:
        defect = "both channels return 0 after N successful inserts"

# delete K objects, recount
K = 10
# fetch ids via Get
q = {"query": "{ Get { %s (limit: %d) { _additional { id } } } }" % (CLS, K)}
st, body, raw = safe_request("POST", "/v1/graphql", data=json.dumps(q),
                             headers={"Content-Type": "application/json"})
try:
    ids = [o["_additional"]["id"] for o in body["data"]["Get"][CLS]]
    for i in ids:
        st, _, raw = safe_request("DELETE", f"/v1/objects/{CLS}/{i}")
        if st not in (204, 200):
            print("delete err", st, raw[:120])
    time.sleep(2)
    st, agg, raw = gql_count()
    print(f"after delete count={agg} expected={N-K}")
    if agg is not None and agg != N - K:
        defect = f"COUNT after deleting K={K}: got {agg}, expected {N-K}"
except Exception as e:
    print("delete phase skipped:", e)

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if defect:
    print(f"DEFECT: {defect}")
    print("VERDICT: DEFECT_FOUND"); sys.exit(1)
print("VERDICT: NO_DEFECT")
