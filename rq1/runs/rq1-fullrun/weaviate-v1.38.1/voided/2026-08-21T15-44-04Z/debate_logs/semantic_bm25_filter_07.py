# Attack: search_correctness — BM25 + where filter fusion; objectLimit requires near*/hybrid
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

CLS = "SemBM25F07"
safe_request("DELETE", f"/v1/schema/{CLS}")
status, _, raw = safe_request("POST", "/v1/schema", json={
    "class": CLS, "vectorizer": "none",
    "properties": [{"name": "text", "dataType": ["text"]},
                   {"name": "grp", "dataType": ["string"]}]})
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create failed", status, raw[:200]); sys.exit(2)

docs = [
    ("zebra alpha", "A"), ("zebra beta", "B"), ("zebra gamma", "A"),
    ("zebra delta", "B"), ("zebra epsilon", "A"),
]
for t, g in docs:
    st, _, r = safe_request("POST", "/v1/objects", json={
        "class": CLS, "id": str(uuid.uuid4()), "properties": {"text": t, "grp": g},
        "vector": [1.0, 0.0]})
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR - insert failed", st, r[:200]); sys.exit(2)

# Case 1: BM25 + where filter grp=A -> only 3 A docs
q1 = ('{ Get { %s(bm25: {query: "zebra"}, where: {operator: Equal, path: ["grp"], valueText: "A"}, '
      'limit: 10) { text grp } } }') % CLS
st, body, raw = safe_request("POST", "/v1/graphql", json={"query": q1})
print("case1:", raw[:400])
rows = body.get("data", {}).get("Get", {}).get(CLS, []) if isinstance(body, dict) else []
if len(rows) != 3 or any(r["grp"] != "A" for r in rows):
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print(f"bm25+where expected 3 grp-A docs, got {[(r['text'],r['grp']) for r in rows]}"); sys.exit(1)

# Case 2: limit=2 respected with filter
q2 = ('{ Get { %s(bm25: {query: "zebra"}, where: {operator: Equal, path: ["grp"], valueText: "A"}, '
      'limit: 2) { text } } }') % CLS
st, body, raw = safe_request("POST", "/v1/graphql", json={"query": q2})
rows = body.get("data", {}).get("Get", {}).get(CLS, [])
if len(rows) != 2:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print(f"limit=2 with filter returned {len(rows)}"); sys.exit(1)

# Case 3: objectLimit without near*/hybrid should be rejected with clear error (documented constraint)
q3 = '{ Get { %s(bm25: {query: "zebra"}, limit: 10, objectLimit: 3) { text } } }' % CLS
st, body, raw = safe_request("POST", "/v1/graphql", json={"query": q3})
print("case3:", raw[:400])
if st == 200 and not (body or {}).get("errors"):
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - objectLimit accepted without near*/hybrid")
    sys.exit(1)

# Case 4: no near/bm25 at all -> plain Get returns all 5
q4 = '{ Get { %s(limit: 10) { text } } }' % CLS
st, body, raw = safe_request("POST", "/v1/graphql", json={"query": q4})
rows = body.get("data", {}).get("Get", {}).get(CLS, [])
if len(rows) != 5:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    print(f"plain Get expected 5, got {len(rows)}"); sys.exit(1)

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
print("VERDICT: NO_DEFECT")
