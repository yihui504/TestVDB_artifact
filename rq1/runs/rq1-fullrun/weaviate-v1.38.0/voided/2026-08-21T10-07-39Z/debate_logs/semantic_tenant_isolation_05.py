# Attack: tenant isolation semantics — cross-tenant visibility, inactive tenant query behavior
# Target: weaviate v1.38.0 | Endpoints: /v1/schema/{c}/tenants, /v1/graphql, /v1/objects | Strategy: behavioral_contract
import os, sys, json, uuid
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
BASE = BASE.rstrip("/")
CLS = "SemTenant05"
T1, T2 = "tenantA", "tenantB"

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
          "multiTenancyConfig": {"enabled": True},
          "properties": [{"name": "name", "dataType": ["text"]}]}
status, _, raw = safe_request("POST", "/v1/schema", json_body=schema)
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create class failed:", status, raw[:300]); sys.exit(2)

status, _, raw = safe_request("POST", f"/v1/schema/{CLS}/tenants",
    json_body=[{"name": T1, "activityStatus": "ACTIVE"}, {"name": T2, "activityStatus": "ACTIVE"}])
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create tenants failed:", status, raw[:300]); sys.exit(2)

def add(tenant, name):
    return safe_request("POST", "/v1/objects",
        json_body={"class": CLS, "tenant": tenant, "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, CLS + tenant + name)),
                   "properties": {"name": name}, "vector": [1.0, 0.0]})

for t, n in [(T1, "alpha"), (T2, "beta")]:
    status, _, raw = add(t, n)
    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR - insert {t}/{n} failed:", status, raw[:300]); sys.exit(2)

import time; time.sleep(1)
failures = []

def gql_get(tenant=None, name_filter=None):
    hdr = '{ name }'
    where = f', where: {{path: ["name"], operator: Equal, valueString: "{name_filter}"}}' if name_filter else ''
    ten = f', tenant: "{tenant}"' if tenant else ''
    q = '{ Get { %s(limit: 10%s%s) { name } } }' % (CLS, where, ten)
    return safe_request("POST", "/v1/graphql", data=json.dumps({"query": q}))

# T1: tenant A sees only alpha
st, b, raw = gql_get(T1)
got = sorted(o["name"] for o in (b or {}).get("data", {}).get("Get", {}).get(CLS, []) or [])
print("T1 tenantA sees:", st, got)
if got != ["alpha"]:
    failures.append(("T1 tenant isolation", got, raw[:300]))

# T2: tenant B sees only beta
st, b, raw = gql_get(T2)
got = sorted(o["name"] for o in (b or {}).get("data", {}).get("Get", {}).get(CLS, []) or [])
print("T2 tenantB sees:", st, got)
if got != ["beta"]:
    failures.append(("T2 tenant isolation", got, raw[:300]))

# T3: query WITHOUT tenant on a MT class — must not silently return cross-tenant data
st, b, raw = gql_get()
got = sorted(o["name"] for o in (b or {}).get("data", {}).get("Get", {}).get(CLS, []) or [])
errs = (b or {}).get("errors")
print("T3 no-tenant query:", st, "results:", got, "errors:", json.dumps(errs)[:200] if errs else None)
if not errs and got:
    failures.append(("T3 missing tenant silently returns cross-tenant objects", got, raw[:300]))

# T4: nonexistent tenant — should error clearly, not return data, not 500
st, b, raw = gql_get("ghostTenantX")
got = (b or {}).get("data", {}).get("Get", {}).get(CLS, []) or []
errs = (b or {}).get("errors")
print("T4 ghost tenant:", st, "results:", len(got), "errors:", json.dumps(errs)[:250] if errs else raw[:250])
if st == 200 and not errs and got:
    failures.append(("T4 nonexistent tenant returns data without error", got, raw[:300]))

# T5: deactivate tenant A, then query it — behavior must be a clear error or empty, not stale success
status, _, raw = safe_request("PUT", f"/v1/schema/{CLS}/tenants",
    json_body=[{"name": T1, "activityStatus": "INACTIVE"}])
print("T5 deactivate:", status, raw[:150])
import time as _t; _t.sleep(1)
st, b, raw = gql_get(T1)
got = (b or {}).get("data", {}).get("Get", {}).get(CLS, []) or []
errs = (b or {}).get("errors")
print("T5 query inactive tenantA:", st, "results:", [o["name"] for o in got],
      "errors:", json.dumps(errs)[:250] if errs else None)
# offloading is async; allow "empty or error". Flag only if stale data silently served AND no error
if st == 200 and not errs and [o["name"] for o in got] == ["alpha"]:
    print("OBS: inactive tenant still serves data after 1s — may be async offloading grace; re-check")
    _t.sleep(5)
    st, b, raw = gql_get(T1)
    got = (b or {}).get("data", {}).get("Get", {}).get(CLS, []) or []
    errs = (b or {}).get("errors")
    print("T5 recheck:", st, [o["name"] for o in got], "errors:", json.dumps(errs)[:200] if errs else None)
    if st == 200 and not errs and [o["name"] for o in got] == ["alpha"]:
        failures.append(("T5 inactive tenant silently serves full data", "alpha", raw[:300]))

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if failures:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    for f in failures: print("FAIL:", f)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
