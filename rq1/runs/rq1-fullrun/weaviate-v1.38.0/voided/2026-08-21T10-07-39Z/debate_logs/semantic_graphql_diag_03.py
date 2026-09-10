# Attack: GraphQL error diagnosis quality — does the error message name the real cause?
# Target: weaviate v1.38.0 | Endpoint: POST /v1/graphql | Strategy: diagnosis_quality (Type2)
# Contract: weaviate_behavioral_graphql_query_001
# Blindspot: BS-02 Error Message Negligence
import os, sys, json
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
BASE = BASE.rstrip("/")
CLS = "SemGqlDiag03"

def safe_request(method, path, json_body=None, data=None):
    headers = {"Content-Type": "application/json"}
    try:
        r = requests.request(method, BASE + path, json=json_body, data=data, headers=headers, timeout=30)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, str(e)

safe_request("DELETE", f"/v1/schema/{CLS}")
schema = {"class": CLS, "vectorizer": "none",
          "properties": [{"name": "name", "dataType": ["text"]},
                         {"name": "score", "dataType": ["number"]},
                         {"name": "tags", "dataType": ["text[]"]}]}
status, _, raw = safe_request("POST", "/v1/schema", json_body=schema)
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create class failed:", status, raw[:300]); sys.exit(2)

def gql(query):
    status, body, raw = safe_request("POST", "/v1/graphql", data=json.dumps({"query": query}))
    errs = None
    if body and isinstance(body, dict):
        errs = body.get("errors")
    return status, errs, raw

def check_error_quality(errs, expected_terms):
    """Type-2 rubric: message must name the offending element + real cause, not generic."""
    if not errs:
        return -1
    msg = json.dumps(errs).lower()
    score = 0
    # Criterion 1: names a specific field/property/operator (any expected term)
    if any(t.lower() in msg for t in expected_terms):
        score += 1
    # Criterion 2: format/location hint
    if any(h in msg for h in ["must be", "expected", "should", "invalid", "unknown", "cannot", "no such", "not found", "does not exist", "valid", "type"]):
        score += 1
    # Criterion 3: actionable hint
    if any(h in msg for h in ["use", "try", "instead", "provide", "check", "correct", "available"]):
        score += 1
    return score

tests = [
    # (name, query, expected terms that a good diagnostic should mention)
    ("nonexistent property", '{ Get { %s(where: {path: ["ghost"], operator: Equal, valueString: "x"}) { name } } }' % CLS,
     ["ghost", "property"]),
    ("nonexistent class", '{ Get { SemGhostXYZ { name } } }', ["semghostxyz", "class", "collection"]),
    ("bad operator", '{ Get { %s(where: {path: ["name"], operator: Equals, valueString: "x"}) { name } } }' % CLS,
     ["equals", "operator"]),
    ("type confusion text vs number", '{ Get { %s(where: {path: ["score"], operator: Equal, valueText: "abc"}) { name } } }' % CLS,
     ["score", "number", "text", "value"]),
    ("wrong value type on text prop", '{ Get { %s(where: {path: ["name"], operator: Equal, valueNumber: 42}) { name } } }' % CLS,
     ["name", "text", "number", "value"]),
    ("malformed syntax", '{ Get { %s(where: {path: ["name"], operator: Equal, valueString "x"}) { name } } }' % CLS,
     ["syntax", "expected", "string"]),
    ("array prop with non-array operator", '{ Get { %s(where: {path: ["tags"], operator: Equal, valueString: "x"}) { name } } }' % CLS,
     ["tags", "array", "containsany", "contains"]),
    ("aggregate on text mean", '{ Aggregate { %s(groupBy: ["name"]) { name { mean } } } }' % CLS,
     ["mean", "text", "number", "aggregate", "name"]),
]

weak = []
for tname, q, terms in tests:
    status, errs, raw = gql(q)
    score = check_error_quality(errs, terms)
    print(f"[{tname}] status={status} score={score}/3 errs={json.dumps(errs)[:200] if errs else raw[:200]}")
    if status == 200 and not errs:
        # query unexpectedly succeeded with no error -> potential Type1/Type4
        weak.append((tname, "no error raised", raw[:200]))
    elif score is not None and score >= 0 and score < 2:
        weak.append((tname, f"score={score}/3", json.dumps(errs)[:250] if errs else raw[:250]))

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if weak:
    print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
    for w in weak: print("WEAK:", w)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
