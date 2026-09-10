# semantic_limitdefault_08 — topk default injection, limit+offset window, exprParams binding, type coercion
# Attack: constraints milvus_range_entities_search_001/002 (limit in [1,16384], default 100)
#   × strategies illegal_rejection + type_coercion + filter_semantics (exprParams)
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

COL = "sem_limit_08"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create",
                             {"collectionName": COL, "dimension": 4, "metricType": "L2"})
print("create:", st, raw[:150])
safe_request("POST", "/v2/vectordb/indexes/create", {
    "collectionName": COL,
    "indexParams": [{"fieldName": "vector", "indexName": "v", "metricType": "L2",
                     "indexType": "FLAT"}]})
safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
time.sleep(2)

rows = [{"id": i, "vector": [0.001 * i] * 4, "tag": "t%d" % (i % 3)} for i in range(1, 6)]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert",
                             {"collectionName": COL, "data": rows})
print("insert:", st, raw[:150])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed"); sys.exit(2)
time.sleep(1)

Q = {"collectionName": COL, "data": [[0.0] * 4]}

# 1. legal limits must be accepted (illegal rejection check)
for lim in (1, 5, 16384):
    st, body, raw = safe_request("POST", "/v2/vectordb/entities/search",
                                 dict(Q, limit=lim))
    code = body.get("code") if isinstance(body, dict) else None
    print("limit=%d -> code=%r raw=%s" % (lim, code, raw[:150]))
    if code is None or (code != 0 and code not in (1100, 1802)):
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — legal limit %d got code=%r (unclassified)" % (lim, code))
        sys.exit(1)
    if lim in (1, 5) and code != 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — limit=%d rejected: %s" % (lim, raw[:200]))
        sys.exit(1)

# 2. limit+offset window > 16384 -> specific range error, not 65535
st, body, raw = safe_request("POST", "/v2/vectordb/entities/search",
                             dict(Q, limit=16000, offset=1000))
code = body.get("code") if isinstance(body, dict) else None
print("limit+offset=17000 -> code=%r raw=%s" % (code, raw[:250]))
if code == 0:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — limit+offset=17000 accepted (max 16384)")
    sys.exit(1)
if code == 65535:
    print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — topk range violation surfaced as generic 65535")
    sys.exit(1)

# 3. type coercion: string/bool limit
for bad in ("5", 5.0, True):
    st, body, raw = safe_request("POST", "/v2/vectordb/entities/search",
                                 dict(Q, limit=bad))
    code = body.get("code") if isinstance(body, dict) else None
    print("limit=%r -> code=%r raw=%s" % (bad, code, raw[:150]))
    if code == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — non-int limit %r silently accepted" % bad)
        sys.exit(1)

# 4. exprParams binding: placeholder filter must match literal filter results
lit = dict(Q, limit=5, filter='tag == "t1"')
para = dict(Q, limit=5, filter='tag == {target}', exprParams={"target": "t1"})
st1, b1, r1 = safe_request("POST", "/v2/vectordb/entities/search", lit)
st2, b2, r2 = safe_request("POST", "/v2/vectordb/entities/search", para)
print("literal:", r1[:250])
print("exprParams:", r2[:250])
n1 = len(b1.get("data") or []) if isinstance(b1, dict) and b1.get("code") == 0 else None
n2 = len(b2.get("data") or []) if isinstance(b2, dict) and b2.get("code") == 0 else None
if n1 is None:
    print("VERDICT: SCRIPT_ERROR — literal filter search failed"); sys.exit(2)
if n2 is None:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — exprParams binding failed: %s" % r2[:250])
    sys.exit(1)
if n1 != n2:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — exprParams result count %d != literal %d" % (n2, n1))
    sys.exit(1)

try:
    safe_request("POST", "/v2/vectordb/collections/release", {"collectionName": COL})
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
print("VERDICT: NO_DEFECT")
