# semantic_r2_nprobe_02 — nprobe semantics: valid domain effect + illegal values (IVF_FLAT index)
# Attack: entities+search searchParams.nprobe x {valid recall effect, -1, 0, string "4", huge}
#   x strategy: search_correctness + type_coercion + diagnosis_quality
# Contract: SearchReqV2 searchParams "nprobe/ef/level/radius/range_filter/search_list (index-type dependent)";
#           generateSearchParams passthrough (REST layer does not validate; segcore consumes)
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

COL = "sem_r2_nprobe"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create",
                             {"collectionName": COL, "dimension": 8, "metricType": "L2"})
print("create:", st, raw[:120])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed: %s" % raw[:200]); sys.exit(2)

# 64 rows: id i has vector with i/64 in every dim -> known 1-D ordering by L2 from origin
rows = [{"id": i, "vector": [i / 64.0] * 8} for i in range(64)]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert", {"collectionName": COL, "data": rows})
print("insert:", st, raw[:120])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed: %s" % raw[:200]); sys.exit(2)

st, body, raw = safe_request("POST", "/v2/vectordb/indexes/create", {
    "collectionName": COL,
    "indexParams": [{"fieldName": "vector", "indexName": "ivf", "metricType": "L2",
                     "indexType": "IVF_FLAT", "params": {"nlist": 4}}]})
print("index create:", st, raw[:150])
st, body, raw = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
print("load:", st, raw[:120])
time.sleep(3)

def search(params):
    return safe_request("POST", "/v2/vectordb/entities/search", {
        "collectionName": COL, "data": [[0.0] * 8], "limit": 5, "searchParams": params})

# ground truth: nearest ids to origin are 0..4
EXPECT = {0, 1, 2, 3, 4}

# Case A: nprobe=4 (== nlist, exhaustive) must give exact top-5
st, body, raw = search({"nprobe": 4})
print("nprobe=4:", st, raw[:300])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — baseline nprobe=4 search failed: %s" % raw[:200]); sys.exit(2)
ids = {r.get("id") for r in body.get("data", [])}
if ids != EXPECT:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — nprobe=4 (full nlist) top-5 = %s, expected %s (nprobe not applied / wrong recall)" % (sorted(ids), sorted(EXPECT)))
    sys.exit(1)

# Case B: string nprobe must be rejected (type coercion on passthrough key)
st, body, raw = search({"nprobe": "4"})
print("nprobe='4':", st, raw[:250])
if st == 200 and isinstance(body, dict) and body.get("code") == 0:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — string nprobe='4' silently accepted (coerced) via searchParams passthrough")
    sys.exit(1)

# Case C: negative nprobe
st, body, raw = search({"nprobe": -1})
print("nprobe=-1:", st, raw[:250])
if st == 200 and isinstance(body, dict) and body.get("code") == 0:
    # accepted: results must still be correct (fallback to valid default), else semantic violation
    ids = {r.get("id") for r in body.get("data", [])}
    if not ids <= EXPECT | {5}:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — nprobe=-1 accepted and returned wrong neighbors %s" % sorted(ids))
        sys.exit(1)
    print("NOTE: nprobe=-1 accepted with plausible results (default fallback), Type1 permissive acceptance")
else:
    msg = raw.lower()
    if "nprobe" not in msg:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — nprobe=-1 rejected without naming nprobe: %s" % raw[:200])
        sys.exit(1)

# Case D: absurd nprobe
st, body, raw = search({"nprobe": 2147483647})
print("nprobe=INT32_MAX:", st, raw[:250])
if st == 200 and isinstance(body, dict) and body.get("code") == 0:
    ids = {r.get("id") for r in body.get("data", [])}
    if ids != EXPECT:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — nprobe=INT32_MAX accepted, top-5 = %s != %s" % (sorted(ids), sorted(EXPECT)))
        sys.exit(1)

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
print("VERDICT: NO_DEFECT")
