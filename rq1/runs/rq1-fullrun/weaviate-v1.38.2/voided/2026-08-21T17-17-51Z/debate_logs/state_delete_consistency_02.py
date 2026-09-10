# Attack: state_invariants weaviate_state_collection_deletion_001 (delete_consistency)
import os, sys, uuid
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

CLS = "StateDel02"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

s, _, raw = safe_request("POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["text"]}]})
print("create:", s)
objs = [{"class": CLS, "id": str(uuid.uuid4()), "properties": {"name": "x"}, "vector": [0.1]} for _ in range(5)]
safe_request("POST", "/v1/batch/objects", json=objs)

s, _, raw = safe_request("DELETE", f"/v1/schema/{CLS}")
print("drop:", s)

# invariant: class must not exist anywhere
checks = [
    ("GET", f"/v1/schema/{CLS}"),
    ("GET", f"/v1/objects/{CLS}?limit=1"),
    ("POST", "/v1/graphql", {"query": f"{{ Get {{ {CLS} {{ name }} }} }}"}),
    ("POST", "/v1/graphql", {"query": f"{{ Aggregate {{ {CLS} {{ meta {{ count }} }} }} }}"}),
]
bad = []
for m, p, body in [(c[0], c[1], c[2] if len(c) > 2 else None) for c in checks]:
    kw = {"json": body} if body else {}
    s, b, raw = safe_request(m, p, **kw)
    print(m, p, "->", s, raw[:150])
    if s == 200:
        # graphql may return errors in body with 200; only flag true success with data
        if "graphql" in p and isinstance(b, dict) and b.get("errors") and not b.get("data"):
            continue
        bad.append((m, p, s))

# recreate same name: state must be fresh (no residual 5 objects)
s, _, raw = safe_request("POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["text"]}]})
print("recreate:", s)
import time
time.sleep(1)
s, b, raw = safe_request("POST", "/v1/graphql", json={"query": f"{{ Aggregate {{ {CLS} {{ meta {{ count }} }} }} }}"})
print("count after recreate:", raw[:200])
residual = None
try:
    residual = b["data"]["Aggregate"][CLS][0]["meta"]["count"]
except Exception:
    pass

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if bad:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — deleted class still accessible: {bad}")
    sys.exit(1)
if residual not in (0, None):
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — residual {residual} objects after drop+recreate")
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
