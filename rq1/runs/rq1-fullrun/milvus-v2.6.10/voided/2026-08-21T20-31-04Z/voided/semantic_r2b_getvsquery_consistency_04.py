# semantic_r2b_getvsquery_consistency_04 — get vs query result-set consistency (R2 supplement, blind R2b)
# Attack: same pk set retrieved via entities+get vs entities+query filter -> identical record content/order-insensitive
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set"); sys.exit(2)
AUTH = {"Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ.get("TESTVDB_MILVUS_TOKEN", "root:Milvus")}

def safe_request(method, endpoint, json_body=None, timeout=20):
    try:
        r = requests.request(method, BASE_URL + endpoint, json=json_body, headers=AUTH, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)

COL = "sem_r2b_getquery"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass

st, body, raw = safe_request("POST", "/v2/vectordb/collections/create", {
    "collectionName": COL, "dimension": 4, "metricType": "L2", "enableDynamicField": True})
print("create:", st, raw[:120])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed: %s" % raw[:200]); sys.exit(2)

rows = [{"id": i, "vector": [i * 0.1] * 4, "score": i * 10, "tag": "t%d" % i} for i in range(1, 13)]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert", {"collectionName": COL, "data": rows})
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed: %s" % raw[:200]); sys.exit(2)
st, _, _ = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
time.sleep(2)

# get subset [3,5,7,11]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/get", {
    "collectionName": COL, "id": [3, 5, 7, 11], "outputFields": ["id", "score", "tag"]})
print("get:", st, raw[:300])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — get failed: %s" % raw[:200]); sys.exit(2)
by_get = {r.get("id"): r for r in body.get("data", [])}

# query same subset
st2, body2, raw2 = safe_request("POST", "/v2/vectordb/entities/query", {
    "collectionName": COL, "filter": "id in [3,5,7,11]",
    "outputFields": ["id", "score", "tag"]})
print("query:", st2, raw2[:300])
if not (st2 == 200 and isinstance(body2, dict) and body2.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — query failed: %s" % raw2[:200]); sys.exit(2)
by_query = {r.get("id"): r for r in body2.get("data", [])}

problems = []
if set(by_get) != {3, 5, 7, 11}:
    problems.append("get returned wrong pk set: %s" % sorted(by_get))
if set(by_query) != {3, 5, 7, 11}:
    problems.append("query returned wrong pk set: %s" % sorted(by_query))
for pk in set(by_get) & set(by_query):
    a = {k: v for k, v in by_get[pk].items() if k != "distance"}
    b = {k: v for k, v in by_query[pk].items() if k != "distance"}
    if a != b:
        problems.append("record mismatch pk=%s get=%s query=%s" % (pk, a, b))

if problems:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — %s" % "; ".join(problems))
    sys.exit(1)
print("VERDICT: NO_DEFECT")
