# Attack: filter_semantics — where filter + nearVector combination result correctness
# Strategy: filter_semantics | Blindspot: BS-05
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

CLS = "SemFilter02"
safe_request("DELETE", f"/v1/schema/{CLS}")
status, _, raw = safe_request("POST", "/v1/schema", json={
    "class": CLS, "vectorizer": "none",
    "properties": [{"name": "category", "dataType": ["string"]},
                   {"name": "score", "dataType": ["int"]}]})
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create failed", status, raw[:200]); sys.exit(2)

objs = [
    {"category": "A", "score": 10, "v": [1.0, 0.0]},
    {"category": "B", "score": 20, "v": [1.0, 0.01]},
    {"category": "A", "score": 30, "v": [1.0, 0.02]},
]
ids = []
for o in objs:
    oid = str(uuid.uuid4()); ids.append(oid)
    st, _, r = safe_request("POST", "/v1/objects", json={
        "class": CLS, "id": oid, "properties": {"category": o["category"], "score": o["score"]},
        "vector": o["v"]})
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR - insert failed", st, r[:200]); sys.exit(2)

GQL = """
{ Get { %s(nearVector: {vector: [1.0, 0.0]}, limit: 10,
      where: {operator: Equal, path: ["category"], valueText: "A"}) {
      category score _additional { id } } } }
""" % CLS

st, body, raw = safe_request("POST", "/v1/graphql", json={"query": GQL})
print(raw[:500])
try:
    results = body["data"]["Get"][CLS]
except Exception:
    results = None
if st != 200 or results is None:
    print("VERDICT: SCRIPT_ERROR - graphql failed", st, raw[:300]); sys.exit(2)
cats = [r.get("category") for r in results]
if len(results) != 2 or any(c != "A" for c in cats):
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print(f"filter+nearVector expected 2 category-A results, got {len(results)} cats={cats}"); sys.exit(1)

# range filter score > 15 (should exclude id with score 10)
GQL2 = """
{ Get { %s(nearVector: {vector: [1.0, 0.0]}, limit: 10,
      where: {operator: GreaterThan, path: ["score"], valueInt: 15}) {
      score _additional { id } } } }
""" % CLS
st, body, raw = safe_request("POST", "/v1/graphql", json={"query": GQL2})
print(raw[:500])
try:
    results = body["data"]["Get"][CLS]
except Exception:
    results = None
scores = sorted([r.get("score") for r in results or []])
if scores != [20, 30]:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print(f"score>15 filter expected [20,30], got {scores}"); sys.exit(1)

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
print("VERDICT: NO_DEFECT")
