# Attack: batch objects partial failure — committed state vs reported status (state_consistency)
# Blindspot: BS-03 partial-commit detection
import os, sys, uuid, time
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
S = requests.Session()

def safe_request(method, path, **kw):
    try:
        r = S.request(method, BASE + path, timeout=60, **kw)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, str(e)

CLS = "StateBatch03"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

s, _, raw = safe_request("POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["text"]}]})
print("create:", s)

# Mixed batch: valid objects + invalid (bad dataType int->text? use wrong vector length for explicit invalid)
GOOD = 10
objs = []
good_ids = []
for i in range(GOOD):
    oid = str(uuid.uuid4())
    good_ids.append(oid)
    objs.append({"class": CLS, "id": oid, "properties": {"name": f"g{i}"}, "vector": [0.1, 0.2]})
# invalid: bad property name (nonexistent property) — weaviate rejects
for i in range(5):
    objs.append({"class": CLS, "id": str(uuid.uuid4()), "properties": {"nonexistent_prop_xyz": "v"}, "vector": [0.1, 0.2]})

s, b, raw = safe_request("POST", "/v1/batch/objects", json={"objects": objs})
print("batch status:", s)
statuses = {}
if isinstance(b, list):
    for x in b:
        st = x.get("result", {}).get("status", "NO_RESULT_FIELD")
        statuses[st] = statuses.get(st, 0) + 1
print("reported per-object statuses:", statuses)

time.sleep(2)
q = {"query": f"{{ Aggregate {{ {CLS} {{ meta {{ count }} }} }} }}"}
s, b, raw = safe_request("POST", "/v1/graphql", json=q)
count = None
try:
    count = b["data"]["Aggregate"][CLS][0]["meta"]["count"]
except Exception:
    print("count raw:", raw[:200])
print(f"committed count={count}, reported SUCCESS={statuses.get('SUCCESS', 0)}")

# verify each good id retrievable
missing = []
for oid in good_ids:
    s2, _, _ = safe_request("GET", f"/v1/objects/{CLS}/{oid}")
    if s2 != 200:
        missing.append(oid)
print(f"good objects missing: {len(missing)}")

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

succ = statuses.get("SUCCESS", 0)
if count is not None and count != succ:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — committed {count} != reported SUCCESS {succ}")
    sys.exit(1)
if missing:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {len(missing)} objects reported SUCCESS but not retrievable")
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
