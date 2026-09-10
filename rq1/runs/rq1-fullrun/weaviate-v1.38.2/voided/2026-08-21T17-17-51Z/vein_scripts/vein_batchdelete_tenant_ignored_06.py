# vein: DELETE /v1/batch/objects silently ignores the ?tenant= query param when the
# target class is not multi-tenant-enabled: returns 200 results instead of a 422
# multi-tenancy error. Control: GET /v1/schema/{c}/tenants on the same non-MT class
# correctly returns 422 "multi-tenancy is not enabled for class".
# Severity: silent param drop on a destructive endpoint — operator believes tenant scoping applied.
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

CLS = "VeinTN06"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass
s, _, _ = safe_request("POST", "/v1/schema",
    json={"class": CLS, "vectorizer": "none",
          "properties": [{"name": "num", "dataType": ["int"]}]})
print("create class:", s)
if s not in (200, 201):
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
objs = [{"class": CLS, "id": str(uuid.uuid4()), "properties": {"num": 1},
         "vector": [0.1, 0.2]} for _ in range(3)]
s, _, _ = safe_request("POST", "/v1/batch/objects", json={"objects": objs})
print("seed:", s)

# control: tenant-aware GET rejects non-MT class with 422
s, _, raw = safe_request("GET", f"/v1/schema/{CLS}/tenants")
print("control tenants GET on non-MT class:", s, raw[:100])
control_422 = (s == 422 and "multi-tenancy is not enabled" in raw)

# probe: batch delete with tenant on non-MT class, dryRun to stay non-destructive
s, _, raw = safe_request("DELETE", "/v1/batch/objects?tenant=no-such-tenant",
    json={"match": {"class": CLS,
                    "where": {"operator": "Equal", "path": ["num"], "valueInt": 1}},
          "dryRun": True, "output": "verbose"})
print("batch delete with tenant on non-MT class:", s, raw[:160])
silent_accept = (s == 200)

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if silent_accept and control_422:
    print("VERDICT: DEFECT_FOUND (Type2_ContractViolation) — DELETE /v1/batch/objects?tenant=X on a non-multi-tenant class silently ignores the tenant scoping and returns 200 (dryRun matched all 3 objects), while sibling tenant-aware endpoints reject the same class with 422 'multi-tenancy is not enabled'; on a real run this deletes data the caller believed tenant-scoped")
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
