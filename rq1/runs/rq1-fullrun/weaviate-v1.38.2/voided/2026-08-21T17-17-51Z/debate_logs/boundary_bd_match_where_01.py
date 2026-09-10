#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2
Attack: Strategy 2 (type boundary / required-field missing)
Constraint: weaviate_type_batch_delete_match_001
Endpoint: DELETE /v1/batch/objects
Blindspot: BS-01 Parameter Validation Optimism
expected_defect_type: Type3_RuntimeFailure (500 on missing required field — GT #12041 channel)
"""
import requests, json, sys, os, uuid

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

CLS = "BoundaryBdWhere1"

# --- setup: create class + one object (baseline control) ---
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
st, _, raw = safe_request("POST", "/v1/schema", json={"class": CLS,
    "properties": [{"name": "name", "dataType": ["string"]}]})
print(f"setup create class: {st} {raw[:200]}")
st, _, raw = safe_request("POST", "/v1/objects", json={"class": CLS,
    "properties": {"name": "target"}, "id": str(uuid.uuid4())})
print(f"setup insert: {st} {raw[:150]}")

# --- control: valid match (class + where) ---
ok_st, _, ok_raw = safe_request("DELETE", "/v1/batch/objects", json={
    "match": {"class": CLS, "where": {"operator":"Equal","path":["name"],"valueText":"target"}}})
print(f"CONTROL valid match: {ok_st} {ok_raw[:200]}")

# --- attack: match present but where MISSING (docs mark required) ---
st, body, raw = safe_request("DELETE", "/v1/batch/objects", json={
    "match": {"class": CLS}})
print(f"ATTACK match.where missing: {st}")
print(f"Body: {raw[:500]}")

if st == 0:
    print("VERDICT: SCRIPT_ERROR — connection failed"); sys.exit(2)
if st >= 500:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — missing match.where returns 5xx, expected 4xx"); sys.exit(1)
if st in (400, 422):
    if "where" in raw.lower() or "match" in raw.lower():
        print("VERDICT: NO_DEFECT — correctly rejected with informative error")
    else:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — rejected but error does not identify missing field"); sys.exit(1)
else:
    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — missing match.where accepted with {st}"); sys.exit(1)

# cleanup
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
