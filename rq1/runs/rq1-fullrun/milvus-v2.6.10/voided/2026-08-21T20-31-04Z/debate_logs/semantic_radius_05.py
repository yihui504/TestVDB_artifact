# semantic_radius_05 — radius/range_filter domain semantics under L2 and COSINE
# Attack: entities+search searchParams {radius, range_filter}
#   × strategy search_correctness: L2 = distance (smaller better), IP/COSINE = similarity (larger better)
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

def build(col, metric):
    try:
        safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": col})
    except Exception:
        pass
    st, body, raw = safe_request("POST", "/v2/vectordb/collections/create",
                                 {"collectionName": col, "dimension": 4, "metricType": metric})
    print("create %s/%s:" % (col, metric), st, raw[:150])
    safe_request("POST", "/v2/vectordb/indexes/create", {
        "collectionName": col,
        "indexParams": [{"fieldName": "vector", "indexName": "v", "metricType": metric,
                         "indexType": "FLAT"}]})
    safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": col})
    time.sleep(2)

def clean(col):
    try:
        safe_request("POST", "/v2/vectordb/collections/release", {"collectionName": col})
        safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": col})
    except Exception:
        pass

# vectors at known L2 distances from query [0,0,0,0]: 0.2, 1.0, 5.0
vecs = [[0.1] * 4, [0.5] * 4, [2.5] * 4]
rows = [{"id": i + 1, "vector": vecs[i]} for i in range(3)]

def distances(body):
    out = []
    for r in (body.get("data") or []):
        out.append(r.get("distance"))
    return out

# ---- L2: distance domain. radius = max distance (inclusive-ish); 1.0 keeps ids 1,2 ----
COL = "sem_radius_l2"
build(COL, "L2")
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert",
                             {"collectionName": COL, "data": rows})
print("insert l2:", st, raw[:150])
st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
    "collectionName": COL, "data": [[0.0] * 4], "limit": 10,
    "searchParams": {"radius": 1.5}})
print("L2 radius=1.5:", st, raw[:300])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — L2 radius search failed: %s" % raw[:200]); sys.exit(2)
d = distances(body)
if any(x is None for x in d):
    print("NOTE: distance field missing in results: %s" % raw[:300])
elif max(d) > 1.5 + 1e-4:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L2 radius=1.5 but returned distance %r > 1.5" % max(d))
    sys.exit(1)

# range_filter on L2: band (0.5, 2.0) should keep only id 2 (dist 1.0)
st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
    "collectionName": COL, "data": [[0.0] * 4], "limit": 10,
    "searchParams": {"radius": 2.0, "range_filter": 0.5}})
print("L2 band [0.5,2.0]:", st, raw[:300])
d = distances(body)
if d and all(x is not None for x in d):
    lo = min(d)
    if lo < 0.5 - 1e-4:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L2 range_filter=0.5 violated: min distance %r < 0.5" % lo)
        sys.exit(1)
clean(COL)

# ---- COSINE: similarity domain. Milvus converts to distance = 1 - cosine_sim ----
COL = "sem_radius_cos"
build(COL, "COSINE")
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert",
                             {"collectionName": COL, "data": rows})
print("insert cos:", st, raw[:150])
# query parallel to all vectors -> cosine sim 1.0 for all -> distance ~0.
# use a query at 45deg: [1,0,0,0] -> cos sim 0.5 vs all -> dist 0.5 for all.
st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
    "collectionName": COL, "data": [[1.0, 0.0, 0.0, 0.0]], "limit": 10})
print("COSINE baseline:", st, raw[:300])
d = distances(body)
if d and all(x is not None for x in d):
    for x in d:
        if abs(x - 0.5) > 0.05:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — COSINE distance should be ~0.5 (1-sim), got %r" % d)
            sys.exit(1)
# radius in COSINE distance domain: 0.4 should return nothing (all dist 0.5)
st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
    "collectionName": COL, "data": [[1.0, 0.0, 0.0, 0.0]], "limit": 10,
    "searchParams": {"radius": 0.4}})
print("COSINE radius=0.4:", st, raw[:300])
d = distances(body)
if d and all(x is not None for x in d) and min(d) <= 0.4:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — COSINE radius=0.4 but returned distance %r <= 0.4 (domain direction wrong?)" % min(d))
    sys.exit(1)
clean(COL)
print("VERDICT: NO_DEFECT")
