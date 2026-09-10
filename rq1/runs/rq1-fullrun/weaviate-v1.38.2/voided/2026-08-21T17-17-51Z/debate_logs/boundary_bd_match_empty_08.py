#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2
Attack: Strategy 2 — DELETE /batch/objects degenerate bodies
Constraint: weaviate_type_batch_delete_match_001 (family)
Cases: {} empty body, {"match":{}}, {"match":null}, match as string/array,
       output missing (match alone), where = empty object.
expected_defect_type: Type3_RuntimeFailure (500) / Type1_IllegalSuccess / Type2
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

CLS = "BdBdEmpty8"
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
safe_request("POST", "/v1/schema", json={"class": CLS,
    "properties": [{"name": "name", "dataType": ["string"]}]})

cases = [
    ("empty object", {}),
    ("match empty obj", {"match": {}}),
    ("match null", {"match": None}),
    ("match as string", {"match": "x"}),
    ("match as array", {"match": [1]}),
    ("where empty object", {"match": {"class": CLS, "where": {}}}),
    ("where null", {"match": {"class": CLS, "where": None}}),
    ("where bad operator", {"match": {"class": CLS,
        "where": {"operator": "Bogus", "path": ["name"], "valueText": "x"}}}),
]
defect = False
for label, payload in cases:
    st, body, raw = safe_request("DELETE", "/v1/batch/objects", json=payload)
    print(f"{label}: {st} {raw[:200]}")
    if st == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed"); sys.exit(2)
    if st >= 500:
        print(f"  DEFECT-SIGNAL: 5xx on {label}")
        defect = True
    elif st == 200:
        print(f"  DEFECT-SIGNAL: degenerate body accepted 200 on {label}")
        defect = True

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass

if defect:
    print("VERDICT: DEFECT_FOUND — see signals above (Type3 5xx or Type1 illegal-200 on degenerate batch-delete body)"); sys.exit(1)
print("VERDICT: NO_DEFECT — degenerate bodies rejected with 4xx")
