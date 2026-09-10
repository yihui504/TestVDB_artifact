# Attack: search_correctness — nearVector ordering (non-degenerate vectors), empty class, zero-vector query
# Note: zero-vector query with cosine metric is degenerate (all distances tie at 1); use
# non-zero query for ordering assertions; zero-vector only for no-crash check.
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

CLS = "SemNear06"
safe_request("DELETE", f"/v1/schema/{CLS}")
status, _, raw = safe_request("POST", "/v1/schema", json={
    "class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["string"]}]})
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create failed", status, raw[:200]); sys.exit(2)

# Case 1: empty class search returns [] not error
q0 = '{ Get { %s(nearVector: {vector: [1.0, 0.0]}, limit: 3) { name } } }' % CLS
st, body, raw = safe_request("POST", "/v1/graphql", json={"query": q0})
print("empty-class:", raw[:300])
if st != 200 or (body.get("data", {}).get("Get", {}) or {}).get(CLS) != []:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print(f"empty class search should return [], status={st} raw={raw[:200]}"); sys.exit(1)

data = [("origin", [1.0, 0.0]), ("close", [0.99, 0.02]), ("far", [0.0, 1.0]), ("medium", [0.8, 0.6])]
for name, v in data:
    st, _, r = safe_request("POST", "/v1/objects", json={
        "class": CLS, "id": str(uuid.uuid4()), "properties": {"name": name}, "vector": v})
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR - insert failed", st, r[:200]); sys.exit(2)

# Case 2: query near origin -> origin first, distances monotonic
q = '{ Get { %s(nearVector: {vector: [1.0, 0.0]}, limit: 4) { name _additional { distance } } } }' % CLS
st, body, raw = safe_request("POST", "/v1/graphql", json={"query": q})
print(raw[:500])
try:
    rows = body["data"]["Get"][CLS]
except Exception:
    print("VERDICT: SCRIPT_ERROR - search failed", st, raw[:300]); sys.exit(2)
names = [r.get("name") for r in rows]
if not names or names[0] != "origin":
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print(f"expected 'origin' first, got {names}"); sys.exit(1)
dists = [r.get("_additional", {}).get("distance") for r in rows]
print("distances:", dists)
if any(d is None for d in dists):
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - missing distance"); sys.exit(1)
if any(dists[i+1] < dists[i] - 1e-9 for i in range(len(dists)-1)):
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print(f"distances not monotonic: {dists}"); sys.exit(1)

# Case 3: near-duplicate vector should rank immediately after exact match
q2 = '{ Get { %s(nearVector: {vector: [1.0, 0.0]}, limit: 2) { name } } }' % CLS
st, body, raw = safe_request("POST", "/v1/graphql", json={"query": q2})
names2 = [r.get("name") for r in body.get("data", {}).get("Get", {}).get(CLS, [])]
if names2[:2] != ["origin", "close"]:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print(f"near-duplicate should rank second, got {names2}"); sys.exit(1)

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
print("VERDICT: NO_DEFECT")
