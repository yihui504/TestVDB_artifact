# Attack: diagnosis_quality (Type2) — wrong-typed filter value, invalid sort path, aggregation on text prop
# Strategy: diagnosis_quality | Blindspot: BS-02
import os, sys, json, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
S = requests.Session()

def safe_request(method, path, **kw):
    r = S.request(method, BASE_URL + path, timeout=30, **kw)
    try: body = r.json()
    except Exception: body = None
    return r.status_code, body, r.text

def check_error_quality(body, expected_param):
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    if expected_param.lower() in error_msg: score += 1
    format_hints = ["must be", "expected", "should be", "valid", "range", "type", "positive", "non-zero", "operator", "data type"]
    if any(h in error_msg for h in format_hints): score += 1
    action_hints = ["correct", "try", "use", "change", "specify", "provide", "supported"]
    if any(h in error_msg for h in action_hints): score += 1
    return score

CLS = "SemDiag04"
safe_request("DELETE", f"/v1/schema/{CLS}")
status, _, raw = safe_request("POST", "/v1/schema", json={
    "class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["string"]},
                   {"name": "score", "dataType": ["int"]}]})
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create failed", status, raw[:200]); sys.exit(2)

deficiencies = []

# Case 1: string value against int property (valueString vs int prop)
q1 = '{ Get { %s(where: {operator: Equal, path: ["score"], valueString: "abc"}, limit: 5) { name } } }' % CLS
st, body, raw = safe_request("POST", "/v1/graphql", json={"query": q1})
err = (body or {}).get("errors") or raw
print("case1:", st, str(err)[:300])
sc = check_error_quality(body, "score")
print("case1 score:", sc, "/3")
if sc < 2:
    deficiencies.append(("filter type mismatch (score vs valueString)", sc, str(err)[:200]))

# Case 2: nonexistent sort path
q2 = '{ Get { %s(limit: 5, sort: {path: ["nonexistent_prop"], order: asc}) { name } } }' % CLS
st, body, raw = safe_request("POST", "/v1/graphql", json={"query": q2})
err = (body or {}).get("errors") or raw
print("case2:", st, str(err)[:300])
sc = check_error_quality(body, "nonexistent_prop")
print("case2 score:", sc, "/3")
if sc < 2:
    deficiencies.append(("invalid sort path", sc, str(err)[:200]))

# Case 3: aggregation mean on text property
q3 = '{ Aggregate { %s(groupBy: ["name"]) { name { count } } } }' % CLS
q3b = '{ Aggregate { %s { score { mean } name { mean } } } }' % CLS
st, body, raw = safe_request("POST", "/v1/graphql", json={"query": q3b})
err = (body or {}).get("errors") or raw
print("case3:", st, str(err)[:300])
if st == 200 and body and body.get("data", {}).get("Aggregate", {}).get(CLS):
    # mean on string prop should be rejected with clear diagnostic
    sc = check_error_quality(body, "mean")
    print("case3 score:", sc, "/3")
    if sc < 2:
        deficiencies.append(("aggregate mean on string prop", sc, str(err)[:200]))

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
if deficiencies:
    print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
    for d in deficiencies: print("DEFICIENCY:", d)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
