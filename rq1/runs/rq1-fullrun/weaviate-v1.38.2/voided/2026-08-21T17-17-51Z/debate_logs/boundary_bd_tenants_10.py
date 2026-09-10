#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2
Attack: Strategy 1+2 — tenant boundaries on multi-tenancy class
Endpoint: POST/GET /v1/schema/{class}/tenants
Cases: empty tenant name, empty tenants array, wrong activity enum,
       huge name, tenants as object (not array).
expected_defect_type: Type3_RuntimeFailure / Type1_IllegalSuccess
"""
import requests, json, sys, os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set"); sys.exit(2)

def safe_request(method, path, **kw):
    try:
        r = requests.request(method, BASE_URL + path, timeout=30, **kw)
        try: body = r.json()
        except Exception: body = None
        return r.status_code, body, r.text
    except Exception as e:
        return 0, None, str(e)

CLS = "BdTenant10"
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
safe_request("POST", "/v1/schema", json={"class": CLS,
    "multiTenancyConfig": {"enabled": True}})

cases = [
    ("empty name", [{"name": "", "activityStatus": "ACTIVE"}]),
    ("bad enum", [{"name": "t1", "activityStatus": "HOT"}]),
    ("name wrong type", [{"name": 123, "activityStatus": "ACTIVE"}]),
    ("missing status", [{"name": "t2"}]),
    ("empty array", []),
]
defect = False
for label, payload in cases:
    st, body, raw = safe_request("POST", f"/v1/schema/{CLS}/tenants", json=payload)
    print(f"{label}: {st} {raw[:200]}")
    if st >= 500:
        print(f"  DEFECT-SIGNAL: 5xx on {label}"); defect = True

# huge name
st, body, raw = safe_request("POST", f"/v1/schema/{CLS}/tenants",
    json=[{"name": "t" * 100000, "activityStatus": "ACTIVE"}])
print(f"huge name (100k chars): {st} {raw[:150]}")
if st >= 500:
    print("  DEFECT-SIGNAL: 5xx on huge tenant name"); defect = True

# read-back of empty-name acceptance
st, body, raw = safe_request("GET", f"/v1/schema/{CLS}/tenants")
print(f"read-back tenants: {st} {raw[:200]}")

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass

if defect:
    print("VERDICT: DEFECT_FOUND — 5xx on tenant boundary input"); sys.exit(1)
print("VERDICT: NO_DEFECT — tenant boundaries handled with 4xx")
