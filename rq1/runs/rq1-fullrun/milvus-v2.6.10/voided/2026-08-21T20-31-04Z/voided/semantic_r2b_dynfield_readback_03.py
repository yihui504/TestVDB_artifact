# semantic_r2b_dynfield_readback_03 — dynamic-field full readback completeness (blind R2b, R2 data-accessibility)
# Attack: dynamic schema new fields (typed + unconventional names + nullable) written via insert, read via
#   entities+get outputFields=["*"] vs entities+query per-field outputFields; asymmetry/loss => Type4
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

COL = "sem_r2b_dynread2"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass

st, body, raw = safe_request("POST", "/v2/vectordb/collections/create", {
    "collectionName": COL, "dimension": 4, "metricType": "L2", "enableDynamicField": True})
print("create:", st, raw[:120])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed: %s" % raw[:200]); sys.exit(2)

DYN_FIELDS = {
    "category": "A",                       # conventional
    "extra_score": 42,                     # int
    "ratio": 3.14,                         # float
    "meta.details": "dotted-name",         # unconventional: dot in name
    "camélia": "unicode-name",             # unicode
}
rows = [dict({"id": 1, "vector": [0.1] * 4}, **DYN_FIELDS),
        {"id": 2, "vector": [0.2] * 4}]   # no dynamic fields at all
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert", {"collectionName": COL, "data": rows})
print("insert:", st, raw[:200])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed: %s" % raw[:300]); sys.exit(2)
st, _, _ = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
time.sleep(2)

# probe 1: get with outputFields=["*"]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/get", {
    "collectionName": COL, "id": [1], "outputFields": ["*"]})
print("get *:", st, raw[:400])
rec = {}
if st == 200 and isinstance(body, dict) and body.get("code") == 0:
    d = body.get("data", [])
    rec = d[0] if d else {}
else:
    print("VERDICT: SCRIPT_ERROR — get failed: %s" % raw[:200]); sys.exit(2)

# probe 2: query per dynamic field (isolate parse failures per name)
problems = []
for k, v in DYN_FIELDS.items():
    st2, body2, raw2 = safe_request("POST", "/v2/vectordb/entities/query", {
        "collectionName": COL, "filter": "id == 1", "outputFields": [k]})
    ok2 = st2 == 200 and isinstance(body2, dict) and body2.get("code") == 0
    got = None
    if ok2:
        d = body2.get("data", [])
        got = d[0].get(k) if d else "NO_RECORD"
    print("query [%s]: ok=%s got=%r raw=%s" % (k, ok2, got, raw2[:120]))
    if not ok2:
        problems.append("query cannot reference field '%s' (parse fail: %s) while insert accepted it and get(*) returns it" % (k, raw2[:120]))
    elif got != v:
        problems.append("query readback mismatch for '%s': wrote %r, read %r" % (k, v, got))

missing_star = [k for k in DYN_FIELDS if k not in rec]
print("missing in get(*):", missing_star)
if missing_star:
    problems.append("fields present in insert but absent from get(*): %s" % missing_star)

if problems:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — %s" % "; ".join(problems))
    sys.exit(1)
print("VERDICT: NO_DEFECT")
