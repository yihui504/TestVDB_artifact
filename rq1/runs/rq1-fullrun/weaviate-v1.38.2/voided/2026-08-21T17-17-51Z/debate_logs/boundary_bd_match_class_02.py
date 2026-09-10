#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2
Attack: Strategy 2 (required-field missing)
Constraint: weaviate_type_batch_delete_match_001
Endpoint: DELETE /v1/batch/objects — match.class missing
expected_defect_type: Type3_RuntimeFailure / Type1_IllegalSuccess
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

CLS = "BoundaryBdClass2"
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
st, _, raw = safe_request("POST", "/v1/schema", json={"class": CLS,
    "properties": [{"name": "name", "dataType": ["string"]}]})
print(f"setup: {st}")
st, _, raw = safe_request("POST", "/v1/objects", json={"class": CLS,
    "properties": {"name": "target"}, "id": str(uuid.uuid4())})
print(f"insert: {st}")

# attack: where present, class missing
st, body, raw = safe_request("DELETE", "/v1/batch/objects", json={
    "match": {"where": {"operator":"Equal","path":["name"],"valueText":"target"}}})
print(f"ATTACK match.class missing: {st}")
print(f"Body: {raw[:500]}")

if st == 0:
    print("VERDICT: SCRIPT_ERROR — connection failed"); sys.exit(2)
if st >= 500:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — missing match.class returns 5xx"); sys.exit(1)
if st in (400, 422):
    print("VERDICT: NO_DEFECT — correctly rejected")
else:
    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — missing match.class accepted with {st}"); sys.exit(1)

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
