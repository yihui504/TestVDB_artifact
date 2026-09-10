# Attack: aggregation groupBy totalCount semantics + pagination correctness
# Strategy: behavioral_contract (aggregation semantics)
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

CLS = "SemAgg05"
safe_request("DELETE", f"/v1/schema/{CLS}")
status, _, raw = safe_request("POST", "/v1/schema", json={
    "class": CLS, "vectorizer": "none",
    "properties": [{"name": "grp", "dataType": ["string"]},
                   {"name": "score", "dataType": ["int"]}]})
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create failed", status, raw[:200]); sys.exit(2)

# 3 groups: A=1 obj, B=2 objs, C=3 objs
groups = {"A": 1, "B": 2, "C": 3}
n = 0
for g, cnt in groups.items():
    for i in range(cnt):
        n += 1
        st, _, r = safe_request("POST", "/v1/objects", json={
            "class": CLS, "id": str(uuid.uuid4()),
            "properties": {"grp": g, "score": i}, "vector": [float(n), 1.0]})
        if st not in (200, 201):
            print("VERDICT: SCRIPT_ERROR - insert failed", st, r[:200]); sys.exit(2)

q = '{ Aggregate { %s(groupBy: ["grp"]) { groupedBy { value } score { count } } } }' % CLS
st, body, raw = safe_request("POST", "/v1/graphql", json={"query": q})
print(raw[:600])
try:
    rows = body["data"]["Aggregate"][CLS]
except Exception:
    print("VERDICT: SCRIPT_ERROR - aggregate failed", st, raw[:300]); sys.exit(2)

counts = {}
for row in rows:
    g = row.get("groupedBy", {}).get("value")
    c = row.get("score", {}).get("count")
    counts[g] = c
if counts != groups:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print(f"groupBy counts expected {groups}, got {counts}"); sys.exit(1)

# totalCount semantic: non-grouped aggregate count should equal total objects
q2 = '{ Aggregate { %s { meta { count } } } }' % CLS
st, body, raw = safe_request("POST", "/v1/graphql", json={"query": q2})
try:
    total = body["data"]["Aggregate"][CLS][0]["meta"]["count"]
except Exception:
    print("VERDICT: SCRIPT_ERROR - meta count failed", raw[:300]); sys.exit(2)
if total != 6:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print(f"total meta count expected 6, got {total}"); sys.exit(1)

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
print("VERDICT: NO_DEFECT")
