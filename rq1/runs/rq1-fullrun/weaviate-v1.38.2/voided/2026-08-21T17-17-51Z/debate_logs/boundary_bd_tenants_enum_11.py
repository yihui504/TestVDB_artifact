#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2 (follow-up: invalid activity enum accepted)
Attack: Strategy 2 + read-back — tenant activityStatus enum validation
Endpoint: POST /v1/schema/{class}/tenants
Prior run: activityStatus "HOT" accepted 200 and persisted verbatim ("HOT");
documented enum is ACTIVE/INACTIVE/OFFLOADING/HOT (4 values). This script
probes whether ARBITRARY strings are persisted (enum completely unvalidated)
and whether the read-back API can still parse them.
expected_defect_type: Type1_IllegalSuccess (arbitrary enum persisted verbatim)
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

CLS = "BdTenantEnum11"
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
safe_request("POST", "/v1/schema", json={"class": CLS,
    "multiTenancyConfig": {"enabled": True}})

# attack: arbitrary enum value
st, body, raw = safe_request("POST", f"/v1/schema/{CLS}/tenants",
    json=[{"name": "tBogus", "activityStatus": "DELETED_BOGUS"}])
print(f"ATTACK activityStatus=DELETED_BOGUS: {st} {raw[:200]}")

# read-back: value persisted verbatim?
st2, b2, raw2 = safe_request("GET", f"/v1/schema/{CLS}/tenants")
print(f"read-back: {st2} {raw2[:300]}")
persisted = any((t or {}).get("name") == "tBogus" and
                t.get("activityStatus") == "DELETED_BOGUS"
                for t in (b2 if isinstance(b2, list) else []))

# can we still use the tenant (object write)?
st3, _, raw3 = safe_request("POST", "/v1/objects", json={
    "class": CLS, "tenant": "tBogus", "properties": {"name": "x"}} if False else
    {"class": CLS, "tenant": "tBogus", "properties": {}})
print(f"object write to bogus tenant: {st3} {raw3[:200]}")

# cleanup
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass

if st in (200, 201) and persisted:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — arbitrary activityStatus "
          "accepted and persisted verbatim (enum unvalidated)"); sys.exit(1)
print("VERDICT: NO_DEFECT — invalid enum rejected or normalized")
