# Attack: upsert idempotence — same ID re-POST/PUT must not duplicate (upsert_idempotence)
import os, sys, uuid, time
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

CLS = "StateUpsert04"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass
s, _, raw = safe_request("POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["text"]}]})
print("create:", s)

oid = str(uuid.uuid4())
for i in range(5):
    body = {"class": CLS, "id": oid, "properties": {"name": f"v{i}"}, "vector": [0.1, 0.2]}
    s1, _, _ = safe_request("POST", "/v1/objects", json=body)      # POST = upsert in weaviate
    s2, _, _ = safe_request("PUT", f"/v1/objects", json=body)       # PUT /v1/objects same body
    print(f"iter {i}: POST={s1} PUT={s2}")

time.sleep(2)
s, b, raw = safe_request("POST", "/v1/graphql", json={"query": f"{{ Aggregate {{ {CLS} {{ meta {{ count }} }} }} }}"})
count = None
try:
    count = b["data"]["Aggregate"][CLS][0]["meta"]["count"]
except Exception:
    print(raw[:200])
print(f"count after 5x duplicate-id upserts = {count} (expect 1)")
s, b, raw = safe_request("GET", f"/v1/objects/{CLS}/{oid}")
final_name = None
try:
    final_name = b["properties"]["name"]
except Exception:
    print(raw[:200])
print("final value:", final_name)

# idempotent delete: delete twice, second should be 404 (or 204 both — check for 500)
s1, _, r1 = safe_request("DELETE", f"/v1/objects/{CLS}/{oid}")
s2, _, r2 = safe_request("DELETE", f"/v1/objects/{CLS}/{oid}")
print(f"delete twice: {s1}, {s2} | {r2[:120]}")

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if count != 1:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — duplicate-id upserts produced count {count}")
    sys.exit(1)
if s2 >= 500 or s2 == -1:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — double delete returned {s2}")
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
