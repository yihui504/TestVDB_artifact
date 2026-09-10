# semantic_filterdiag_04 — filter expression error diagnosis quality on delete/query/search
# Attack: constraint milvus_type_entities_delete_001 (filter boolean expr)
#   × strategy diagnosis_quality (Type2): unknown field / type mismatch / syntax error
# Blindspot: BS-02 Error Message Negligence
import os, sys, time, json, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set"); sys.exit(2)
AUTH = {"Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ.get("TESTVDB_MILVUS_TOKEN", "root:Milvus")}

def safe_request(method, endpoint, json_body=None, timeout=15):
    try:
        r = requests.request(method, BASE_URL + endpoint, json=json_body, headers=AUTH, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)

def check_error_quality(body, expected_token):
    """Type-2 rubric: param/field named (1) + format/valid hint (1) + actionable (1)."""
    msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    if expected_token.lower() in msg:
        score += 1
    if any(h in msg for h in ["must be", "expected", "should be", "valid", "range", "type",
                              "cannot", "can not", "not exist", "unknown", "invalid", "unexpected"]):
        score += 1
    if any(h in msg for h in ["correct", "try", "use ", "change", "specify", "provide", "supported"]):
        score += 1
    return score, msg

COL = "sem_fdiag_04"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass

st, body, raw = safe_request("POST", "/v2/vectordb/collections/create", {
    "collectionName": COL, "dimension": 8})
print("create:", st, raw[:200])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed"); sys.exit(2)

st, body, raw = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
print("load:", st, raw[:200])
time.sleep(2)

# insert one row with typed scalar
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert",
                             {"collectionName": COL, "data": [{"id": 1, "vector": [0.1] * 8}]})
print("insert:", st, raw[:200])

cases = [
    # (label, filter_expr, expected-token-to-name, endpoint)
    ("unknown field",  "nonexistent_field == 1",  "nonexistent_field", "query"),
    ("type mismatch",  "id == \"not_an_int\"",    "id",                "query"),
    ("syntax error",   "id == ",                  "id",                "query"),
    ("unknown field delete", "ghost == 'x'",      "ghost",             "delete"),
    ("unknown field search", "phantom > 5",       "phantom",           "search"),
]
worst = 3
for label, fexpr, token, ep in cases:
    payload = {"collectionName": COL, "filter": fexpr}
    if ep == "search":
        payload["data"] = [[0.0] * 8]; payload["limit"] = 1
    if ep == "query":
        payload["outputFields"] = ["id"]
    st, body, raw = safe_request("POST", "/v2/vectordb/entities/%s" % ep, payload)
    code = body.get("code") if isinstance(body, dict) else None
    print("[%s/%s] HTTP=%s code=%r raw=%s" % (ep, label, st, code, raw[:250]))
    if st != 200 or code in (None, 0):
        # silently accepted invalid filter is a Type1 defect on delete/query/search
        if code == 0 and label != "type mismatch":
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — invalid filter %r accepted with code 0" % fexpr)
            sys.exit(1)
    score, msg = check_error_quality(body, token)
    print("  diagnosis score: %d/3" % score)
    if score == 0:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — filter error for %r names neither cause nor hint: %s" % (fexpr, msg[:300]))
        sys.exit(1)
    worst = min(worst, score)

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
print("diagnosis min score across cases: %d/3" % worst)
print("VERDICT: NO_DEFECT")
