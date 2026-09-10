# state_ref_dangling_008 — cross-object reference integrity: delete target -> dangling ref on source
# Attack: dependency-chain break (Mode C) at object level; batch/references partial state
import os, sys, time, requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE = BASE.rstrip("/") + "/v1"
S = requests.Session()

def safe_request(method, path, body=None):
    try:
        r = S.request(method, BASE + path, json=body, timeout=60)
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, r.text
    except Exception as e:
        return -1, None, str(e)

SRC = "StR008Src"; DST = "StR008Dst"
SID = "99999999-9999-9999-9999-999999999999"
DID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

safe_request("DELETE", f"/schema/{SRC}")
safe_request("DELETE", f"/schema/{DST}")
time.sleep(1)
s, _, raw = safe_request("POST", "/schema", {"class": DST, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["text"]}]})
print("create dst:", s)
s, _, raw = safe_request("POST", "/schema", {"class": SRC, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["text"]},
                   {"name": "linked", "dataType": [DST]}]})
print("create src:", s)
assert s in (200, 201)

safe_request("POST", "/objects", {"class": DST, "id": DID, "properties": {"name": "target"}, "vector": [0.1]})
s, b, raw = safe_request("POST", "/objects", {"class": SRC, "id": SID,
    "properties": {"name": "src"}, "vector": [0.1]})
print("insert src (no ref yet):", s)

# add reference via POST /batch/references (contract endpoint)
ref_body = {"from": f"weaviate://localhost/{SRC}/{SID}/linked",
            "to": f"weaviate://localhost/{DST}/{DID}"}
s, b, raw = safe_request("POST", "/batch/references", [ref_body])
print("batch add ref:", s, raw[:150])
time.sleep(1)
s, b, raw = safe_request("GET", f"/objects/{SRC}/{SID}?include=vector")
print("src with ref:", s, str((b or {}).get("properties", {}).get("linked"))[:120])

defect = False
# delete target object -> source read must not crash / must surface clean dangling state
s, b, raw = safe_request("DELETE", f"/objects/{DST}/{DID}")
print("delete target:", s)
time.sleep(1)
s, b, raw = safe_request("GET", f"/objects/{SRC}/{SID}")
print("src after target delete:", s, raw[:200])
if s >= 500:
    print("DEFECT Type3: 5xx reading object with dangling reference"); defect = True
if s == 200:
    linked = ((b or {}).get("properties") or {}).get("linked")
    print("linked after target delete:", linked)

# graphql traversal over dangling ref must not 5xx
q = '{"query":"{ Get { StR008Src { name linked { ... on StR008Dst { name } } } } }"}'
r = S.post(BASE + "/graphql", data=q, headers={"Content-Type": "application/json"})
print("graphql ref traversal (dangling):", r.status_code, r.text[:300])
if r.status_code >= 500:
    print("DEFECT Type3: 5xx graphql traversal over dangling ref"); defect = True
try:
    jd = r.json()
    if "errors" in (jd or {}) and any("panic" in str(e).lower() for e in jd["errors"]):
        print("DEFECT Type3: panic in graphql dangling-ref traversal"); defect = True
except Exception:
    pass

# re-create target with same id: does ref silently rebind (resurrection)?
s, b, raw = safe_request("POST", "/objects",
    {"class": DST, "id": DID, "properties": {"name": "target2"}, "vector": [0.2]})
print("recreate target same id:", s)
time.sleep(1)
s, b, raw = safe_request("GET", f"/objects/{SRC}/{SID}")
linked = ((b or {}).get("properties") or {}).get("linked") if s == 200 else None
print("src ref after target recreate:", linked)
# rebind is acceptable weaviate behavior (beacon by URI); flag only torn/half state
if isinstance(linked, list) and len(linked) > 1:
    print("DEFECT Type4: duplicated reference beacons after recreate"); defect = True

try:
    safe_request("DELETE", f"/schema/{SRC}")
    safe_request("DELETE", f"/schema/{DST}")
except Exception:
    pass

print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
