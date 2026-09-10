# state_delete_02: DELETE 后一致性（invariant weaviate_state_collection_deletion_001）
# Attack: delete_consistency — collection gone from schema, objects 404, graphql errors not 500, alias dangling behavior
import os, sys, time, uuid, json
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
S = requests.Session()

def safe_request(method, path, **kw):
    try:
        r = S.request(method, BASE_URL + path, timeout=30, **kw)
    except Exception as e:
        return None, None, "EXC:" + str(e)
    try:
        return r.status_code, r.json(), r.text
    except Exception:
        return r.status_code, None, r.text

CLS = "StDelB"
ALIAS = "stDelBAlias"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

safe_request("POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["text"]}]})
OID = str(uuid.uuid4())
st, _, raw = safe_request("POST", "/v1/objects", json={"class": CLS, "id": OID,
    "properties": {"name": "x"}})
print("insert:", st)
# alias to this class
st, _, raw = safe_request("POST", "/v1/aliases", json={"alias": ALIAS, "class": CLS})
print("alias create:", st, raw[:150])

# delete collection
st, _, raw = safe_request("DELETE", f"/v1/schema/{CLS}")
print("delete class:", st)

defect = None
# 1. schema must not contain class
st, body, raw = safe_request("GET", "/v1/schema")
classes = []
if isinstance(body, dict):
    classes = [c.get("class") for c in body.get("classes", body.get("schema", []))]
if CLS in classes:
    defect = f"deleted class {CLS} still present in GET /schema"

# 2. direct object read -> expect 404, not 500
st, _, raw = safe_request("GET", f"/v1/objects/{CLS}/{OID}")
print("read object on deleted class:", st, raw[:150])
if st == 500:
    defect = f"GET object on deleted class returns 500 (expected 404): {raw[:150]}"

# 3. graphql on deleted class -> expect error in body, not HTTP 500
q = {"query": "{ Get { %s { name } } }" % CLS}
st, _, raw = safe_request("POST", "/v1/graphql", data=json.dumps(q),
                          headers={"Content-Type": "application/json"})
print("graphql on deleted class:", st, raw[:200])
if st == 500:
    defect = f"graphql on deleted class returns HTTP 500: {raw[:200]}"

# 4. alias pointing to deleted class: check alias still listed & queries through it
st, body, raw = safe_request("GET", "/v1/aliases")
print("aliases after class delete:", st, raw[:300])
st, _, raw = safe_request("GET", f"/v1/aliases/{ALIAS}")
print("alias detail:", st, raw[:200])

# recreate same class name: old alias should resolve again; stale object must NOT resurrect
safe_request("POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["text"]}]})
st, _, raw = safe_request("GET", f"/v1/objects/{CLS}/{OID}")
print("read old object id after recreate:", st, raw[:150])
if st in (200, 201):
    defect = f"object {OID} resurrected after collection delete+recreate (data residue)"

# cleanup
try:
    safe_request("DELETE", f"/v1/aliases/{ALIAS}")
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if defect:
    print(f"DEFECT: {defect}")
    print("VERDICT: DEFECT_FOUND"); sys.exit(1)
print("VERDICT: NO_DEFECT")
