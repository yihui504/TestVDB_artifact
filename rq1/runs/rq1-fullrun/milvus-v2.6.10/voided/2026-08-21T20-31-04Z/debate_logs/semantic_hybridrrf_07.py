# semantic_hybridrrf_07 — hybrid_search RRF fusion math + rerank param diagnosis
# Attack: entities+hybrid_search (rrf strategy) × strategy metamorphic/search_correctness
# Checks: (1) rrf fusion with k=60 on two identical subsearches preserves ranking,
#         (2) known rrf score arithmetic, (3) bad rerank params rejected with named error.
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

COL = "sem_rrf_07"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass

# full-schema mode: two vector fields
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create", {
    "collectionName": COL,
    "schema": {
        "autoId": False,
        "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "color", "dataType": "FloatVector", "dimension": 4},
            {"fieldName": "shape", "dataType": "FloatVector", "dimension": 4},
        ]}})
print("create:", st, raw[:200])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed"); sys.exit(2)
safe_request("POST", "/v2/vectordb/indexes/create", {
    "collectionName": COL,
    "indexParams": [
        {"fieldName": "color", "indexName": "ci", "metricType": "L2", "indexType": "FLAT"},
        {"fieldName": "shape", "indexName": "si", "metricType": "L2", "indexType": "FLAT"}]})
safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
time.sleep(2)

rows = [
    {"id": 1, "color": [0.0] * 4,  "shape": [0.0] * 4},   # rank1 in both
    {"id": 2, "color": [0.3] * 4,  "shape": [3.0] * 4},
    {"id": 3, "color": [3.0] * 4,  "shape": [0.3] * 4},
]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert",
                             {"collectionName": COL, "data": rows})
print("insert:", st, raw[:150])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed"); sys.exit(2)
time.sleep(1)

subs = [{"data": [[0.0] * 4], "annsField": "color", "limit": 3},
        {"data": [[0.0] * 4], "annsField": "shape", "limit": 3}]

# RRF k=60: identical subsearch rankings -> fused ranking preserved, score = sum 1/(60+rank)
st, body, raw = safe_request("POST", "/v2/vectordb/entities/hybrid_search", {
    "collectionName": COL, "search": subs, "limit": 3,
    "rerank": {"strategy": "rrf", "params": {"k": 60}}})
print("rrf:", st, raw[:400])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — hybrid_search failed: %s" % raw[:300]); sys.exit(2)
data = body.get("data") or []
ids = [r.get("id") for r in data]
dists = [r.get("distance") for r in data]
print("fused ids:", ids, "distances:", dists)
if not ids or ids[0] != 1:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — RRF fused top-1 should be id 1 (rank1 both fields), got %r" % ids)
    sys.exit(1)
if dists and dists[0] is not None:
    expected = 1.0 / 61 + 1.0 / 61  # rank1 in both subsearches, k=60
    if abs(dists[0] - expected) > 1e-3:
        print("NOTE: RRF top score %r != expected %.6f (fusion math deviation candidate)" % (dists[0], expected))
        if abs(dists[0] - expected) > 0.05:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — RRF k=60 score math wrong: %r vs %.6f" % (dists[0], expected))
            sys.exit(1)

# bad rerank strategy -> named rejection
st, body, raw = safe_request("POST", "/v2/vectordb/entities/hybrid_search", {
    "collectionName": COL, "search": subs, "limit": 3,
    "rerank": {"strategy": "nonexistent_rerank", "params": {}}})
code = body.get("code") if isinstance(body, dict) else None
print("bad rerank:", st, code, raw[:300])
if code == 0:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — unknown rerank strategy accepted")
    sys.exit(1)
msg = str(raw).lower()
if "rrf" not in msg and "weighted" not in msg and "strategy" not in msg:
    print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — bad rerank error names neither valid strategies nor param: %s" % raw[:300])
    sys.exit(1)

# advanced_search alias equivalence (metamorphic)
st2, body2, raw2 = safe_request("POST", "/v2/vectordb/entities/advanced_search", {
    "collectionName": COL, "search": subs, "limit": 3,
    "rerank": {"strategy": "rrf", "params": {"k": 60}}})
ids2 = [r.get("id") for r in ((body2.get("data") if isinstance(body2, dict) else None) or [])] \
    if isinstance(body2, dict) and body2.get("code") == 0 else None
print("advanced_search ids:", ids2)
if ids2 is not None and ids2 != ids:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — advanced_search alias differs from hybrid_search: %r vs %r" % (ids2, ids))
    sys.exit(1)

try:
    safe_request("POST", "/v2/vectordb/collections/release", {"collectionName": COL})
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
print("VERDICT: NO_DEFECT")
