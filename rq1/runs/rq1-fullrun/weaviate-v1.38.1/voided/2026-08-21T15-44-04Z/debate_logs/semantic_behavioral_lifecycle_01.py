# Attack: behavioral_contract x weaviate_behavioral_{collection,object}_lifecycle_001 + object_deletion_001
# Strategy: behavioral_contract | Blindspot: BS-05
import os, sys, json, requests, uuid

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
S = requests.Session()

def safe_request(method, path, **kw):
    r = S.request(method, BASE_URL + path, timeout=30, **kw)
    try: body = r.json()
    except Exception: body = None
    return r.status_code, body, r.text

CLS = "SemLife01"
# setup: delete then create class
safe_request("DELETE", f"/v1/schema/{CLS}")
status, body, raw = safe_request("POST", "/v1/schema", json={
    "class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["string"]}]})
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create failed", status, raw[:200]); sys.exit(2)

# Contract 1: created collection retrievable by name, appears in list
status, body, raw = safe_request("GET", f"/v1/schema/{CLS}")
if status != 200 or not isinstance(body, dict) or body.get("class") != CLS:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print("created collection not retrievable by name:", status, raw[:300]); sys.exit(1)
status, body, raw = safe_request("GET", "/v1/schema")
names = [c.get("class") for c in (body or {}).get("classes", []) if isinstance(c, dict)]
if CLS not in names:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - collection missing from schema list"); sys.exit(1)

# Contract 2: object create -> retrieve same properties
oid = str(uuid.uuid4())
props = {"name": "alpha"}
status, body, raw = safe_request("POST", "/v1/objects", json={
    "class": CLS, "id": oid, "properties": props, "vector": [0.1, 0.2, 0.3]})
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - object create failed", status, raw[:200]); sys.exit(2)
status, body, raw = safe_request("GET", f"/v1/objects/{CLS}/{oid}")
if status != 200 or (body or {}).get("properties") != props:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print("object properties differ after retrieval:", raw[:300]); sys.exit(1)

# Contract 3: delete -> subsequent GET returns 404
status, _, raw = safe_request("DELETE", f"/v1/objects/{CLS}/{oid}")
if status not in (200, 204):
    print("VERDICT: SCRIPT_ERROR - delete failed", status, raw[:200]); sys.exit(2)
status, body, raw = safe_request("GET", f"/v1/objects/{CLS}/{oid}")
if status != 404:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print(f"deleted object should 404, got {status}: {raw[:300]}"); sys.exit(1)

# cleanup
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
print("VERDICT: NO_DEFECT")
