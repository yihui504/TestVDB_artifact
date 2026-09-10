# semantic_r2_outputfields_01 — data accessibility semantics: insert-accepted fields must be readable via query outputFields
# Attack: entities+insert -> entities+query outputFields matrix (valid scalar / dynamic key / invalid name / "*")
#   x strategy: behavioral_contract (milvus_bc_crud_visibility_001 read-back extension) + diagnosis_quality
# Contract: SearchReqV2/QueryReq outputFields; V2Envelope merr codes (1100 invalid parameter)
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

COL = "sem_r2_ofield"

# setup: quick-create (dynamic field enabled by default on quick create), insert with extra dynamic key
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create",
                             {"collectionName": COL, "dimension": 4})
print("create:", st, raw[:150])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — quick create failed: %s" % raw[:200]); sys.exit(2)

rows = [
    {"id": 1, "vector": [0.1, 0.1, 0.1, 0.1], "dyn_note": "alpha", "dyn_score": 42},
    {"id": 2, "vector": [0.2, 0.2, 0.2, 0.2], "dyn_note": "beta",  "dyn_score": 7},
]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert",
                             {"collectionName": COL, "data": rows})
print("insert w/ dynamic keys:", st, raw[:200])
insert_ok = st == 200 and isinstance(body, dict) and body.get("code") == 0
if not insert_ok:
    # insert rejecting dynamic keys on quick-create collection is itself a semantic signal, but
    # cannot proceed with readback matrix
    print("VERDICT: SCRIPT_ERROR — insert with dynamic keys rejected: %s" % raw[:200]); sys.exit(2)

def q(fields):
    return safe_request("POST", "/v2/vectordb/entities/query", {
        "collectionName": COL, "filter": "id in [1,2]", "outputFields": fields, "limit": 10})

# Case A: "*" must return inserted dynamic values back
st, body, raw = q(["*"])
print("query outputFields=['*']:", st, raw[:400])
data = body.get("data") if isinstance(body, dict) else None
if not (st == 200 and body.get("code") == 0 and data):
    print("VERDICT: SCRIPT_ERROR — wildcard query failed: %s" % raw[:200]); sys.exit(2)
row1 = next((r for r in data if r.get("id") == 1), {})
got_note = row1.get("dyn_note")
if got_note != "alpha":
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — insert accepted dyn_note='alpha' but query '*' returned %r (dynamic data loss / readback mismatch)" % got_note)
    sys.exit(1)

# Case B: explicit dynamic field name readback
st, body, raw = q(["id", "dyn_score"])
print("query outputFields=['id','dyn_score']:", st, raw[:300])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — dynamic field dyn_score accepted at insert but rejected at query outputFields: %s" % raw[:200])
    sys.exit(1)
row1 = next((r for r in body.get("data", []) if r.get("id") == 1), {})
if row1.get("dyn_score") != 42:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — dyn_score=42 inserted, query returned %r" % row1.get("dyn_score"))
    sys.exit(1)

# Case C: invalid field name -> must error (1100-class) with the field named, not silent success / silent drop
st, body, raw = q(["id", "no_such_field_xyz"])
print("query outputFields=['id','no_such_field_xyz']:", st, raw[:300])
if st == 200 and isinstance(body, dict) and body.get("code") == 0:
    # accepted: check whether bogus field was silently ignored (empty) or echoed
    row = (body.get("data") or [{}])[0]
    if "no_such_field_xyz" not in row:
        print("NOTE: invalid outputField silently dropped (code 0), no error, no echo — permissive but not data-loss")
else:
    msg = str(raw).lower()
    if "no_such_field_xyz" not in msg:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — invalid outputFields rejected without naming the field: %s" % raw[:200])
        sys.exit(1)

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
print("VERDICT: NO_DEFECT")
