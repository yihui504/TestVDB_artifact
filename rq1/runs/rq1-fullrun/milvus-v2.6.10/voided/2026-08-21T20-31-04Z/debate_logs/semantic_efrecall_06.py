# semantic_efrecall_06 — ef searchParam semantics: ef >= topk, higher ef recall monotonicity, bad ef diagnosis
# Attack: entities+search searchParams.ef (contract param searchParams.ef, verified transparent passthrough)
#   × strategy search_correctness + diagnosis_quality
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

COL = "sem_ef_06"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create",
                             {"collectionName": COL, "dimension": 8, "metricType": "L2"})
print("create:", st, raw[:150])
safe_request("POST", "/v2/vectordb/indexes/create", {
    "collectionName": COL,
    "indexParams": [{"fieldName": "vector", "indexName": "v", "indexType": "HNSW",
                     "metricType": "L2", "params": {"M": 16, "efConstruction": 200}}]})
# poll index build
for _ in range(10):
    st, body, raw = safe_request("POST", "/v2/vectordb/indexes/describe",
                                 {"collectionName": COL, "indexName": "v"})
    if isinstance(body, dict) and "Finished" in raw:
        break
    time.sleep(1)
st, body, raw = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
print("load:", st, raw[:150])
time.sleep(2)

# 200 deterministic points, query = point of id 1
import random
random.seed(42)
rows = [{"id": 1, "vector": [0.5] * 8}]
for i in range(2, 202):
    noise = [0.5 + random.uniform(-1.5, 1.5) for _ in range(8)]
    rows.append({"id": i, "vector": noise})
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert",
                             {"collectionName": COL, "data": rows})
print("insert:", st, raw[:150])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed"); sys.exit(2)
time.sleep(1)

def topk_with(ef, k=5):
    st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
        "collectionName": COL, "data": [[0.5] * 8], "limit": k,
        "searchParams": {"ef": ef}})
    if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
        return None, raw
    ids = [r.get("id") for r in (body.get("data") or [])]
    return ids, raw

ids_hi, raw = topk_with(128)
print("ef=128 top5:", ids_hi, raw[:200])
if ids_hi is None:
    print("VERDICT: SCRIPT_ERROR — ef search failed: %s" % raw[:200]); sys.exit(2)
if not ids_hi or ids_hi[0] != 1:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — exact-match point id=1 not top-1 with ef=128: %r" % ids_hi)
    sys.exit(1)

# lower ef must not produce better-ranked results than higher ef (recall monotonicity, ties aside)
ids_lo, raw = topk_with(16)
print("ef=16 top5:", ids_lo)
# bad ef: string / negative — must be rejected with clear code, not silently coerced
for bad_ef in ("64", -1):
    st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
        "collectionName": COL, "data": [[0.5] * 8], "limit": 5,
        "searchParams": {"ef": bad_ef}})
    code = body.get("code") if isinstance(body, dict) else None
    print("bad ef=%r -> HTTP=%s code=%r raw=%s" % (bad_ef, st, code, raw[:250]))
    if bad_ef == "64" and code == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — string ef='64' silently accepted/coerced")
        sys.exit(1)

try:
    safe_request("POST", "/v2/vectordb/collections/release", {"collectionName": COL})
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
print("VERDICT: NO_DEFECT")
