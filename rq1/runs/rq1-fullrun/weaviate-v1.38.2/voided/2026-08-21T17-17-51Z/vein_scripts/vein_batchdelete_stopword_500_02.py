# vein: DELETE /v1/batch/objects with a stopword-only filter term returns 500
# ("docIds: invalid search term, only stopwords provided") — a caller-input
# condition surfaced as 5xx. Control: GraphQL Aggregate with the same filter returns the
# error as a GraphQL error field (HTTP 200), i.e. the engine classifies it as a query-level
# (user-input) condition, not a server fault.
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

CLS = "VeinBD02"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass
s, _, _ = safe_request("POST", "/v1/schema",
    json={"class": CLS, "vectorizer": "none",
          "properties": [{"name": "name", "dataType": ["text"]}]})
print("create class:", s)
if s not in (200, 201):
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)

objs = [{"class": CLS, "id": str(uuid.uuid4()), "properties": {"name": "zebra"}} for _ in range(3)]
s, _, _ = safe_request("POST", "/v1/batch/objects", json={"objects": objs})
print("seed batch:", s)

# stopword-only term on the filter ('a'/'the' are default English stopwords)
s, b, raw = safe_request("DELETE", "/v1/batch/objects",
    json={"match": {"class": CLS,
                    "where": {"operator": "Equal", "path": ["name"], "valueText": "the"}},
          "dryRun": True})
print("batch delete stopword:", s, raw[:160])
stopword_500 = (s == 500 and "stopwords" in raw)

# control 1: non-stopword term is a clean 200
s, _, raw = safe_request("DELETE", "/v1/batch/objects",
    json={"match": {"class": CLS,
                    "where": {"operator": "Equal", "path": ["name"], "valueText": "nomatch"}},
          "dryRun": True})
print("control non-stopword:", s)
control_ok = (s == 200)

# control 2: same stopword filter via GraphQL surfaces as structured error, not 5xx semantics
s, _, raw = safe_request("POST", "/v1/graphql",
    json={"query": '{ Aggregate { %s(where:{path:["name"],operator:Equal,valueText:"the"}) '
                   '{ meta { count } } } }' % CLS})
gql_structured = ("stopwords" in raw) and (s == 200)
print("control graphql stopword structured:", s, "stopword-err-present:", "stopwords" in raw)

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if stopword_500 and control_ok:
    print("VERDICT: DEFECT_FOUND (Type3_ErrorHandling) — stopword-only filter term on DELETE /v1/batch/objects returns HTTP 500 (docIds: invalid search term...) while the same term is handled as a structured, non-server-fault error on GraphQL; 5xx misclassifies user input as server fault")
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
