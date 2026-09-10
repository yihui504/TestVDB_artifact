# Attack: search_correctness — hybrid alpha weight behavior (weaviate: alpha = vector weight)
# alpha=0 -> pure BM25 (lexical match first); alpha=1 -> pure vector (vector-nearest first);
# default (omitted) alpha=0.75 -> vector-dominant.
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

CLS = "SemHybrid03"
safe_request("DELETE", f"/v1/schema/{CLS}")
status, _, raw = safe_request("POST", "/v1/schema", json={
    "class": CLS, "vectorizer": "none",
    "properties": [{"name": "text", "dataType": ["text"]}]})
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create failed", status, raw[:200]); sys.exit(2)

LEX = "zebra zebra zebra"; VEC = "unrelated prose entirely"
for o in [(LEX, [0.0, 1.0]), (VEC, [1.0, 0.0])]:
    st, _, r = safe_request("POST", "/v1/objects", json={
        "class": CLS, "id": str(uuid.uuid4()), "properties": {"text": o[0]}, "vector": o[1]})
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR - insert failed", st, r[:200]); sys.exit(2)

def hybrid(alpha):
    alpha_arg = "" if alpha is None else ", alpha: %s" % alpha
    q = '{ Get { %s(hybrid: {query: "zebra", vector: [1.0, 0.0]%s}, limit: 2) { text } } }' % (CLS, alpha_arg)
    st, body, raw = safe_request("POST", "/v1/graphql", json={"query": q})
    print(f"alpha={alpha}:", raw[:300])
    if st != 200: return None
    return [r.get("text") for r in body.get("data", {}).get("Get", {}).get(CLS, [])]

checks = [
    (0.0, LEX),   # pure BM25 -> lexical first
    (1.0, VEC),   # pure vector -> vector-nearest first
    (None, VEC),  # default 0.75 -> vector-dominant
]
for alpha, expect_first in checks:
    res = hybrid(alpha)
    if res is None:
        print("VERDICT: SCRIPT_ERROR - hybrid query failed"); sys.exit(2)
    if not res or res[0] != expect_first:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"alpha={alpha}: expected '{expect_first}' first, got {res}"); sys.exit(1)

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
print("VERDICT: NO_DEFECT")
