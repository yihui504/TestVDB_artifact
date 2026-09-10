# Attack: schema update — PUT /schema/{class} config change vs live index state (state_consistency / read-write split)
# Read-write channel split: GET /schema/{class} reported config vs actual behavior on objects endpoint.
import os, sys, time, uuid
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
S = requests.Session()

def safe_request(method, path, **kw):
    try:
        r = S.request(method, BASE + path, timeout=30, **kw)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, str(e)

CLS = "StateSchema07"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

s, _, raw = safe_request("POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["text"]}]})
print("create:", s)

# insert with 2-dim vector
oid = str(uuid.uuid4())
s, _, raw = safe_request("POST", "/v1/objects", json={"class": CLS, "id": oid,
    "properties": {"name": "x"}, "vector": [0.1, 0.2]})
print("insert 2-dim:", s, raw[:150])

# try updating class-level vector config via PUT /schema/{class}
newconf = {"class": CLS, "vectorizer": "none",
    "vectorIndexConfig": {"distance": "cosine", "ef": 128},
    "properties": [{"name": "name", "dataType": ["text"]}, {"name": "extra", "dataType": ["int"]}]}
s, b, raw = safe_request("PUT", f"/v1/schema/{CLS}", json=newconf)
print("PUT schema:", s, raw[:200])

# reported config after update
s, b, raw = safe_request("GET", f"/v1/schema/{CLS}")
print("GET schema after PUT:", s, raw[:300])
reported_distance = None
reported_extra = None
try:
    reported_distance = b["vectorIndexConfig"]["distance"]
    reported_extra = [p["name"] for p in b["properties"]]
except Exception:
    pass

# behavior check: can we insert into new 'extra' prop? does old 2-dim object still readable?
s, b, raw = safe_request("POST", "/v1/objects", json={"class": CLS, "id": str(uuid.uuid4()),
    "properties": {"name": "y", "extra": 5}, "vector": [0.1, 0.2]})
print("insert with extra prop:", s, raw[:150])
s, b, raw = safe_request("GET", f"/v1/objects/{CLS}/{oid}")
print("old object readable:", s, raw[:150])

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

# split-brain check: PUT accepted(2xx) but reported config lacks changes
if s is not None and reported_distance and "cosine" in str(newconf):
    # if PUT returned 2xx but GET shows old distance -> read/write split
    if reported_distance and reported_distance != "cosine":
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — PUT accepted but GET reports distance={reported_distance}")
        sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
