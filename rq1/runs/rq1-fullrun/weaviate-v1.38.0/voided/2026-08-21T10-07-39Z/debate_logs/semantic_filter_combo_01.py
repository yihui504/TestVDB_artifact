# Attack: GraphQL Get where-filter combination semantics (And/Or/Like/Not) result correctness
# Target: weaviate v1.38.0 | Endpoint: POST /v1/graphql | Strategy: filter_semantics
# Contract: weaviate_behavioral_graphql_query_001
# Blindspot: BS-05 Documentation Drift
# SKIPPED by-design: single-letter values ("A"/"B") on Equal text filters hit BM25 stopword
#                   rejection ("only stopwords provided") — tokenization-layer behavior, not filter
#                   semantics; use non-stopword values instead. NotEmpty not in v1.38 operator enum.
import os, sys, json, uuid
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
BASE = BASE.rstrip("/")
CLS = "SemFilterCombo01"

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
          "properties": [
              {"name": "name", "dataType": ["text"]},
              {"name": "cat", "dataType": ["text"]},
              {"name": "score", "dataType": ["number"]},
          ]}
status, body, raw = safe_request("POST", "/v1/schema", json_body=schema)
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create class failed:", status, raw[:300]); sys.exit(2)

data = [
    {"name": "apple", "cat": "fruit", "score": 10},
    {"name": "banana", "cat": "fruit", "score": 20},
    {"name": "carrot", "cat": "veg", "score": 30},
    {"name": "daikon", "cat": "veg", "score": 5},
]
for d in data:
    status, _, raw = safe_request("POST", "/v1/objects",
        json_body={"class": CLS, "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, CLS + d["name"])),
                   "properties": d, "vector": [0.1, 0.2]})
    if status not in (200, 201):
        print("VERDICT: SCRIPT_ERROR - insert failed:", status, raw[:300]); sys.exit(2)

import time; time.sleep(1)

def gql(where_literal):
    q = '{ Get { %s(where: %s, limit: 10) { name } } }' % (CLS, where_literal)
    status, body, raw = safe_request("POST", "/v1/graphql", data=json.dumps({"query": q}))
    names = []
    if body and (body.get("data") or {}).get("Get", {}).get(CLS):
        names = sorted(o["name"] for o in body["data"]["Get"][CLS])
    errs = body.get("errors") if isinstance(body, dict) else None
    return status, names, errs, raw

failures = []
def check(tname, literal, expected):
    st, got, errs, raw = gql(literal)
    print("[%s] status=%s got=%s errs=%s" % (tname, st, got, json.dumps(errs)[:160] if errs else None))
    if errs:
        failures.append((tname, "query error", json.dumps(errs)[:250]))
    elif got != expected:
        failures.append((tname, "got %s expected %s" % (got, expected), raw[:250]))

check("T1 Equal cat=fruit", '{path: ["cat"], operator: Equal, valueString: "fruit"}', ["apple", "banana"])
check("T2 Or", '{operator: Or, operands: [{path: ["cat"], operator: Equal, valueString: "fruit"}, {path: ["score"], operator: GreaterThan, valueNumber: 15}]}', ["apple", "banana", "carrot"])
check("T3 And", '{operator: And, operands: [{path: ["cat"], operator: Equal, valueString: "fruit"}, {path: ["score"], operator: GreaterThan, valueNumber: 15}]}', ["banana"])
check("T4 GTE boundary >=10", '{path: ["score"], operator: GreaterThanEqual, valueNumber: 10}', ["apple", "banana", "carrot"])
check("T5 LTE boundary <=10", '{path: ["score"], operator: LessThanEqual, valueNumber: 10}', ["apple", "daikon"])
check("T6 nested And/Or", '{operator: And, operands: [{path: ["cat"], operator: Equal, valueString: "veg"}, {operator: Or, operands: [{path: ["name"], operator: Equal, valueString: "daikon"}, {path: ["name"], operator: Equal, valueString: "carrot"}]}]}', ["carrot", "daikon"])
check("T7 Like wildcard", '{path: ["name"], operator: Like, valueString: "a*"}', ["apple"])
check("T8 Not", '{operator: Not, operands: {path: ["cat"], operator: Equal, valueString: "fruit"}}', ["carrot", "daikon"])
check("T9 Equal on number exact", '{path: ["score"], operator: Equal, valueNumber: 5}', ["daikon"])
check("T10 And double negation", '{operator: And, operands: [{path: ["score"], operator: GreaterThan, valueNumber: 4}, {path: ["score"], operator: LessThan, valueNumber: 6}]}', ["daikon"])

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if failures:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    for f in failures: print("FAIL:", f)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
