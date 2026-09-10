# vein: DELETE /v1/batch/objects validation errors misuse 500 instead of 4xx
# Root cause: usecases/objects/batch_delete.go L128/L132/L136 use plain errors.New
# ("empty match clause"/"empty match.class clause"/"empty match.where clause") instead of
# ErrInvalidUserInput, so adapters/handlers/rest/handlers_batch_objects.go L194-197 falls
# through to InternalServerError. Control: same handler maps ErrInvalidUserInput to 422
# (verified: nonexistent class -> 422 "validate: failed to get class").
import os, sys, json, uuid
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

CLS = "VeinBD01"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

s, _, raw = safe_request("POST", "/v1/schema",
    json={"class": CLS, "vectorizer": "none",
          "properties": [{"name": "name", "dataType": ["text"]}]})
print("create class:", s)
if s not in (200, 201):
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)

cases = {
    "no_match":            {},
    "match_null":          {"match": None},
    "match_empty":         {"match": {}},
    "match_class_only":    {"match": {"class": CLS}},
    "match_where_null":    {"match": {"class": CLS, "where": None}},
}

defect = False
for name, body in cases.items():
    s, b, raw = safe_request("DELETE", "/v1/batch/objects", json=body)
    msg = ""
    try:
        msg = b["error"][0]["message"]
    except Exception:
        pass
    print(f"{name}: HTTP {s} msg={msg[:80]}")
    if s == 500 and "empty match" in msg:
        defect = True

# control: same endpoint, caller-input error correctly mapped to 422
s, b, raw = safe_request("DELETE", "/v1/batch/objects",
    json={"match": {"class": "NoSuchClassVein",
                    "where": {"operator": "Equal", "path": ["name"], "valueText": "x"}}})
print("control nonexistent class:", s, raw[:100])
control_ok = (s == 422)

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if defect and control_ok:
    print("VERDICT: DEFECT_FOUND (Type3_ErrorHandling) — validation errors 'empty match[.class/.where] clause' returned as HTTP 500 while sibling validation errors on the same endpoint use 422; 5xx signals server fault to clients/monitors for a caller-input error")
    sys.exit(1)
elif defect:
    print("VERDICT: DEFECT_FOUND (Type3_ErrorHandling) — empty-match validation errors return 500")
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
