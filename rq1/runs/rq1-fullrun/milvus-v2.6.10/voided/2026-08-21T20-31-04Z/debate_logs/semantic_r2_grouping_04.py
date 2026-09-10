# semantic_r2_grouping_04 — groupingField semantics (R1 aborted-test backfill, quick-create avoids full-schema pitfall)
# Attack: entities+search groupingField/groupSize x strategy search_correctness
# Contract: SearchReqV2 groupingField/groupSize/strictGroupSize params
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

COL = "sem_r2_group"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create",
                             {"collectionName": COL, "dimension": 4, "metricType": "L2"})
print("create:", st, raw[:120])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed: %s" % raw[:200]); sys.exit(2)

# 3 groups x 3 members; distances from origin [0,0,0,0]: g1 nearest, then g2, g3
rows = [
    {"id": 1, "vector": [0.1] * 4, "grp": "g1"},
    {"id": 2, "vector": [0.11] * 4, "grp": "g1"},
    {"id": 3, "vector": [0.12] * 4, "grp": "g1"},
    {"id": 4, "vector": [0.5] * 4, "grp": "g2"},
    {"id": 5, "vector": [0.51] * 4, "grp": "g2"},
    {"id": 6, "vector": [0.52] * 4, "grp": "g2"},
    {"id": 7, "vector": [2.0] * 4, "grp": "g3"},
    {"id": 8, "vector": [2.01] * 4, "grp": "g3"},
    {"id": 9, "vector": [2.02] * 4, "grp": "g3"},
]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert", {"collectionName": COL, "data": rows})
print("insert:", st, raw[:120])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed: %s" % raw[:200]); sys.exit(2)
st, _, raw = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
time.sleep(2)

# Case A: groupingField with limit=3 -> one best hit per group, groups ordered by their best member
st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
    "collectionName": COL, "data": [[0.0] * 4], "limit": 3,
    "groupingField": "grp", "outputFields": ["grp"]})
print("grouping limit=3:", st, raw[:350])
if not (st == 200 and body.get("code") == 0):
    msg = raw.lower()
    if "grp" not in msg and "group" not in msg:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — grouping search failed without naming field/cause: %s" % raw[:200])
        sys.exit(1)
    print("VERDICT: SCRIPT_ERROR — grouping search rejected: %s" % raw[:250]); sys.exit(2)
data = body.get("data", [])
grps = [d.get("grp") for d in data]
ids = [d.get("id") for d in data]
if sorted(g for g in grps if g) != ["g1", "g2", "g3"] or ids != [1, 4, 7]:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — grouping top-1 per group expected ids [1,4,7] grps [g1,g2,g3], got ids=%s grps=%s" % (ids, grps))
    sys.exit(1)

# Case B: groupSize=2, limit=3 -> 3 groups x 2 members; per-group best two first
st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
    "collectionName": COL, "data": [[0.0] * 4], "limit": 3,
    "groupingField": "grp", "groupSize": 2, "outputFields": ["grp"]})
print("grouping groupSize=2:", st, raw[:400])
if st == 200 and body.get("code") == 0:
    data = body.get("data", [])
    ids = [d.get("id") for d in data]
    # each group contributes its 2 nearest; non-strict may under-fill last group (candidate-pool
    # truncation) — record as evidence; hard check is strictGroupSize below
    if sorted(ids) != [1, 2, 4, 5, 7, 8]:
        print("EVIDENCE: non-strict groupSize=2 under-filled: got %s (topks=%s)" % (
            sorted(ids), body.get("topks")))

# Case C: strictGroupSize=true must return exactly groupSize per group
st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
    "collectionName": COL, "data": [[0.0] * 4], "limit": 3,
    "groupingField": "grp", "groupSize": 2, "strictGroupSize": True, "outputFields": ["grp"]})
print("strictGroupSize=true:", st, raw[:400])
if st == 200 and body.get("code") == 0:
    from collections import Counter
    cnt = Counter(d.get("grp") for d in body.get("data", []))
    if any(v != 2 for v in cnt.values()):
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — strictGroupSize=true but group counts %s != 2 each (3 members exist per group)" % dict(cnt))
        sys.exit(1)
    st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
        "collectionName": COL, "data": [[0.0] * 4], "limit": 3,
        "groupingField": "grp", "groupSize": 2, "strictGroupSize": False, "outputFields": ["grp"]})
    cnt_ns = Counter(d.get("grp") for d in (body.get("data") or [])) if (st == 200 and isinstance(body, dict) and body.get("code") == 0) else {}
    print("strictGroupSize=false counts:", dict(cnt_ns), raw[:200])

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
print("VERDICT: NO_DEFECT")
