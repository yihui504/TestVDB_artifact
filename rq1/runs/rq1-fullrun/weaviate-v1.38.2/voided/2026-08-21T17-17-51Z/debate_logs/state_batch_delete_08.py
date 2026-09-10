# Attack: batch delete — DELETE /batch/objects with match filter; committed vs matched counts
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

CLS = "StateBDel08"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass
s, _, raw = safe_request("POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["text"]}, {"name": "grp", "dataType": ["int"]}]})
print("create:", s)

objs = [{"class": CLS, "id": str(uuid.uuid4()), "properties": {"name": f"n{i}", "grp": i % 2},
         "vector": [0.1, 0.2]} for i in range(20)]
s, _, raw = safe_request("POST", "/v1/batch/objects", json={"objects": objs})
print("batch insert:", s)
if s not in (200,201):
    try:
        safe_request("DELETE", f"/v1/schema/{CLS}")
    except Exception: pass
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
time.sleep(2)

# delete only grp==1 (10 objects)
filt = {"match": {"class": CLS, "where": {"operator": "Equal", "path": ["grp"], "valueInt": 1},
                  "output": "minimal"}}
s, b, raw = safe_request("DELETE", "/v1/batch/objects", json=filt)
print("batch delete:", s, raw[:300])
reported = None
try:
    reported = b["results"]["matches"]
except Exception:
    pass
print("reported matches:", reported)

time.sleep(2)
count = None
s, b, raw = safe_request("POST", "/v1/graphql", json={"query": f"{{ Aggregate {{ {CLS} {{ meta {{ count }} }} }} }}"})
try:
    count = b["data"]["Aggregate"][CLS][0]["meta"]["count"]
except Exception:
    print(raw[:200])
print(f"count after batch delete={count} expected=10, reported={reported}")

# delete same filter again — should match 0 now
s, b, raw = safe_request("DELETE", "/v1/batch/objects", json=filt)
reported2 = None
try:
    reported2 = b["results"]["matches"]
except Exception:
    pass
print("second identical batch delete reported:", reported2, "status", s)

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if count != 10:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — count {count} != 10 after filtered batch delete")
    sys.exit(1)
if reported2 not in (0, None) and reported2 == reported and reported:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — repeat delete matched {reported2} again (not idempotent)")
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
