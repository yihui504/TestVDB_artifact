# state_tenant_visibility_003 — tenant lifecycle vs object visibility consistency
# + tenant-identifier transport inconsistency (header vs query param vs body)
# Attack: tenants<->objects cross-state consistency; MT lifecycle ACTIVE->INACTIVE->ACTIVE->delete
# Deliberate tenant-isolation test script (allowed exception).
# Probe facts (v1.38.0): object reads accept ?tenant=t1; X-Weaviate-Tenant-Header is NOT
# honored on GET /objects (422 "without tenant"); writes accept tenant in body.
import os, sys, time, requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE = BASE.rstrip("/") + "/v1"
S = requests.Session()

def safe_request(method, path, body=None, hdrs=None):
    try:
        r = S.request(method, BASE + path, json=body, headers=hdrs or {}, timeout=60)
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, r.text
    except Exception as e:
        return -1, None, str(e)

CLS = "StT003"
OID = "33333333-3333-3333-3333-333333333333"
CLS_BODY = {"class": CLS, "vectorizer": "none",
            "multiTenancyConfig": {"enabled": True},
            "properties": [{"name": "name", "dataType": ["text"]}]}

safe_request("DELETE", f"/schema/{CLS}")
time.sleep(1.5)
s, b, raw = safe_request("POST", "/schema", CLS_BODY)
print("create MT class:", s); assert s in (200, 201)

s, b, raw = safe_request("POST", f"/schema/{CLS}/tenants",
    [{"name": "t1", "activityStatus": "ACTIVE"}])
print("create tenant:", s)

s, b, raw = safe_request("POST", "/objects",
    {"class": CLS, "id": OID, "tenant": "t1", "properties": {"name": "x"}, "vector": [0.1]})
print("insert obj(t1):", s)
assert s in (200, 201), "setup fail"

defect = False
s, b, raw = safe_request("GET", f"/objects/{CLS}/{OID}?tenant=t1")
print("GET ?tenant ACTIVE (expect 200):", s)
if s != 200:
    print("DEFECT Type4: object unreadable while tenant ACTIVE"); defect = True

# --- transport inconsistency: documented header vs working query param ---
s, b, raw = safe_request("GET", f"/objects/{CLS}/{OID}",
    hdrs={"X-Weaviate-Tenant-Header": "t1"})
print("GET X-Weaviate-Tenant-Header:", s, raw[:120])
if s == 422 and "without tenant" in raw:
    print("DEFECT Type2-diagnostic: X-Weaviate-Tenant-Header silently ignored on object GET "
          "(says 'request was without tenant') while ?tenant=t1 works — inconsistent tenant transport")
    defect = True

# --- INACTIVE lifecycle ---
s, b, raw = safe_request("PUT", f"/schema/{CLS}/tenants",
    [{"name": "t1", "activityStatus": "INACTIVE"}])
print("set INACTIVE:", s, raw[:80])
time.sleep(1)
s, b, raw = safe_request("GET", f"/objects/{CLS}/{OID}?tenant=t1")
print("GET ?tenant INACTIVE:", s, raw[:100])
if s == 200:
    print("DEFECT Type4: object visible while tenant INACTIVE"); defect = True
if s >= 500:
    print("DEFECT Type3: 5xx on inactive-tenant read"); defect = True

# --- reactivate: object must survive intact ---
s, b, raw = safe_request("PUT", f"/schema/{CLS}/tenants",
    [{"name": "t1", "activityStatus": "ACTIVE"}])
print("reactivate:", s)
time.sleep(2)
s, b, raw = safe_request("GET", f"/objects/{CLS}/{OID}?tenant=t1")
print("GET ?tenant reactivated (expect 200):", s)
if s != 200:
    print("DEFECT Type4: object lost across INACTIVE->ACTIVE cycle"); defect = True
elif ((b or {}).get("properties") or {}).get("name") != "x":
    print("DEFECT Type4: object mutated across cycle"); defect = True

# --- delete tenant: no resurrection after recreate ---
s, b, raw = safe_request("DELETE", f"/schema/{CLS}/tenants", ["t1"])
print("delete tenant:", s)
time.sleep(1)
s, b, raw = safe_request("GET", f"/objects/{CLS}/{OID}?tenant=t1")
print("GET after tenant delete:", s)
if s == 200:
    print("DEFECT Type4: object outlives tenant deletion"); defect = True
if s >= 500:
    print("DEFECT Type3: 5xx after tenant delete"); defect = True

s, b, raw = safe_request("POST", f"/schema/{CLS}/tenants",
    [{"name": "t1", "activityStatus": "ACTIVE"}])
print("recreate tenant:", s)
time.sleep(1)
s, b, raw = safe_request("GET", f"/objects/{CLS}/{OID}?tenant=t1")
print("GET after tenant recreate (expect 404):", s)
if s == 200:
    print("DEFECT Type4: object resurrected after tenant recreate"); defect = True

try:
    safe_request("DELETE", f"/schema/{CLS}")
except Exception:
    pass

print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
