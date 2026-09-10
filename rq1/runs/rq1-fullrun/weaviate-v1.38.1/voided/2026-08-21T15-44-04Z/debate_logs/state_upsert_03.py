# state_upsert_03: Upsert 幂等性 — same UUID POST twice => 1 object, last write wins
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

CLS = "StUpsC"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass
safe_request("POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["text"]}]})

OID = str(uuid.uuid4())
st1, _, raw1 = safe_request("POST", "/v1/objects", json={"class": CLS, "id": OID,
    "properties": {"name": "first"}})
st2, _, raw2 = safe_request("POST", "/v1/objects", json={"class": CLS, "id": OID,
    "properties": {"name": "second"}})
print("post1:", st1, raw1[:150])
print("post2(same id):", st2, raw2[:200])

# PUT same id twice
st3, _, raw3 = safe_request("PUT", f"/v1/objects/{CLS}/{OID}", json={"class": CLS, "id": OID,
    "properties": {"name": "third"}})
print("put:", st3, raw3[:150])

time.sleep(1.5)

# count via Get
q = {"query": "{ Get { %s (limit: 100) { name _additional { id } } } }" % CLS}
st, body, raw = safe_request("POST", "/v1/graphql", data=json.dumps(q),
                             headers={"Content-Type": "application/json"})
objs = []
try:
    objs = body["data"]["Get"][CLS]
except Exception:
    print("graphql raw:", raw[:300])
print("objects returned:", len(objs), objs)

defect = None
if len(objs) != 1:
    defect = f"upsert same id 3x produced {len(objs)} objects (expected 1)"
elif objs and objs[0].get("name") != "third":
    defect = f"last-write-wins violated: name={objs[0].get('name')}, expected 'third'"
if st2 == 500:
    defect = f"duplicate-id POST returns 500 instead of idempotent/upsert or 422: {raw2[:200]}"

# DELETE twice: second should be idempotent-ish (404 or 204), not 500
st4, _, raw4 = safe_request("DELETE", f"/v1/objects/{CLS}/{OID}")
st5, _, raw5 = safe_request("DELETE", f"/v1/objects/{CLS}/{OID}")
print("delete1:", st4, "delete2:", st5, raw5[:150])
if st5 == 500:
    defect = f"second DELETE of same object returns 500: {raw5[:200]}"

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if defect:
    print(f"DEFECT: {defect}")
    print("VERDICT: DEFECT_FOUND"); sys.exit(1)
print("VERDICT: NO_DEFECT")
