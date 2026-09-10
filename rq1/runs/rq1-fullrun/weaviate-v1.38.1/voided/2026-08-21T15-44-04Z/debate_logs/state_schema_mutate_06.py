# state_schema_mutate_06: schema 配置变更对既有数据一致性影响
# PUT /schema/{class} 修改属性 (tokenization/invertedIndex) / DROP prop via null：
# 既有对象是否可见、属性删除后数据残留、改配置后读写通道分裂
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

CLS = "StSchF"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass
st, _, raw = safe_request("POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [
        {"name": "keep", "dataType": ["text"]},
        {"name": "dropme", "dataType": ["text"], "tokenization": "word"},
    ]})
print("create:", st, raw[:150])

IDS = [str(uuid.uuid5(uuid.NAMESPACE_DNS, f"sch-{i}")) for i in range(5)]
for i, oid in enumerate(IDS):
    st, _, raw = safe_request("POST", "/v1/objects", json={"class": CLS, "id": oid,
        "properties": {"keep": f"k{i}", "dropme": f"secret{i}"}})
    if st not in (200, 201):
        print("insert err", st, raw[:150])

# mutation 1: remove property by setting null (weaviate prop-drop feature)
st, _, raw = safe_request("PUT", f"/v1/schema/{CLS}", json={"class": CLS, "properties": [{"name": "dropme"}]})
# weaviate uses null to drop: some versions accept {"name": None}; try both
if st not in (200, 201):
    st, _, raw = safe_request("PUT", f"/v1/schema/{CLS}", json={"class": CLS, "properties": [{"name": None}]})
print("put schema (drop prop):", st, raw[:250])

# check schema state
st, body, raw = safe_request("GET", f"/v1/schema/{CLS}")
props = [p.get("name") for p in (body or {}).get("properties", [])] if isinstance(body, dict) else []
print("schema props after mutate:", st, props)

defect = None
time.sleep(1.5)
# read object: dropme should be gone; if prop still in schema, data must still be intact (no partial state)
st, body, raw = safe_request("GET", f"/v1/objects/{CLS}/{IDS[0]}")
print("object read after mutate:", st, raw[:300])
if st == 200 and isinstance(body, dict):
    pr = body.get("properties", {})
    has_drop = "dropme" in pr
    if "dropme" not in props and has_drop:
        defect = f"property dropped from schema but value still served: {pr}"
    if "dropme" in props and pr.get("dropme") != "secret0":
        defect = f"prop still in schema but value corrupted: {pr}"

# graphql where filter on dropped/mutated prop should error gracefully not 500
q = {"query": '{ Get { %s (where: {path: ["dropme"] operator: Equal valueText: "secret0"}) { keep } } }' % CLS}
st, _, raw = safe_request("POST", "/v1/graphql", data=json.dumps(q),
                          headers={"Content-Type": "application/json"})
print("graphql where on mutated prop:", st, raw[:250])
if st == 500:
    defect = f"graphql where on mutated prop returns HTTP 500: {raw[:200]}"

# mutation 2: change tokenization of existing prop with data
st, _, raw = safe_request("PUT", f"/v1/schema/{CLS}", json={"class": CLS, "properties": [
    {"name": "keep", "tokenization": "lowercase"}]})
print("put schema (retokenize):", st, raw[:250])
# re-read data intact
st, body, raw = safe_request("GET", f"/v1/objects/{CLS}/{IDS[1]}")
if st == 200 and isinstance(body, dict) and body.get("properties", {}).get("keep") != "k1":
    defect = f"data corrupted after retokenize: {body.get('properties')}"

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if defect:
    print(f"DEFECT: {defect}")
    print("VERDICT: DEFECT_FOUND"); sys.exit(1)
print("VERDICT: NO_DEFECT")
