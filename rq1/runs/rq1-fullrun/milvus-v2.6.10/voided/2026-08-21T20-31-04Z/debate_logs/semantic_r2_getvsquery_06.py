# semantic_r2_getvsquery_06 — data accessibility: entities+get vs entities+query vs entities+search readback consistency
#   for insert-accepted fields (incl. dynamic). Any divergence = data-loss signal.
# Attack: entities+get / entities+query / entities+search outputFields x strategy metamorphic
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set"); sys.exit(2)
AUTH = {"Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ.get("TESTVDB_MILVUS_TOKEN", "root:Milvus")}

def safe_request(method, endpoint, json_body=None, timeout=15):
    try:
        r = requests.request(method, BASE_URL + endpoint, json=json_body, headers=AUTH, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)

COL = "sem_r2_getvsq"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create",
                             {"collectionName": COL, "dimension": 4, "metricType": "L2"})
print("create:", st, raw[:120])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed: %s" % raw[:200]); sys.exit(2)

rows = [
    {"id": 1, "vector": [0.1] * 4, "tag": "alpha", "n": 10},
    {"id": 2, "vector": [0.6] * 4, "tag": "beta",  "n": 20},
]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert", {"collectionName": COL, "data": rows})
print("insert:", st, raw[:150])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed: %s" % raw[:200]); sys.exit(2)
st, _, raw = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
time.sleep(2)

# readback via entities+get (pk)
st, body, raw = safe_request("POST", "/v2/vectordb/entities/get", {
    "collectionName": COL, "id": [1, 2], "outputFields": ["*"]})
print("get id=[1,2]:", st, raw[:400])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — get failed: %s" % raw[:200]); sys.exit(2)
get_map = {r.get("id"): r for r in body.get("data", [])}

# readback via entities+query (filter)
st, body, raw = safe_request("POST", "/v2/vectordb/entities/query", {
    "collectionName": COL, "filter": "id in [1,2]", "outputFields": ["*"], "limit": 10})
print("query id in [1,2]:", st, raw[:400])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — query failed: %s" % raw[:200]); sys.exit(2)
q_map = {r.get("id"): r for r in body.get("data", [])}

# readback via entities+search (outputFields)
st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
    "collectionName": COL, "data": [[0.0] * 4], "limit": 2, "outputFields": ["*"]})
print("search outputFields=*:", st, raw[:400])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — search failed: %s" % raw[:200]); sys.exit(2)
s_map = {r.get("id"): r for r in body.get("data", [])}

for src, m in (("get", get_map), ("query", q_map), ("search", s_map)):
    if 1 not in m or 2 not in m:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — %s did not return both inserted rows (got ids %s)" % (src, sorted(m)))
        sys.exit(1)
    for key, want in (("tag", "alpha"), ("n", 10)):
        got = m[1].get(key)
        if got != want:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — %s readback of dynamic field %s on id=1: got %r, inserted %r (insert/query inconsistency = data loss)" % (src, key, got, want))
            sys.exit(1)

# consistency across the three channels: same field set for id=1
keys_get, keys_q, keys_s = (set(get_map[1].keys()), set(q_map[1].keys()), set(s_map[1].keys()))
print("field sets:", sorted(keys_get), sorted(keys_q), sorted(keys_s))
common = keys_get & keys_q & keys_s
for k in common:
    vals = (get_map[1].get(k), q_map[1].get(k), s_map[1].get(k))
    if len({repr(v) for v in vals}) != 1:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — field %s diverges across get/query/search: %r" % (k, vals))
        sys.exit(1)

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
print("VERDICT: NO_DEFECT")
