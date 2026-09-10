#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2
Attack: Strategy 2 — POST /v1/batch/references degenerate bodies
Cases: {} object body, empty array, null, missing from/to fields,
       wrong beacon format (control: valid-looking beacon).
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

CLS = "BdBdRef13"
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
safe_request("POST", "/v1/schema", json={"class": CLS,
    "properties": [{"name": "name", "dataType": ["string"]},
                   {"name": "ref", "dataType": [CLS]}]})

cases = [
    ("object body", {}),
    ("null body", None),
    ("empty array", []),
    ("missing from", [{"to": f"weaviate://localhost/{CLS}/00000000-0000-0000-0000-000000000001",
                       "from": ""}]),
    ("bad beacon", [{"from": "garbage", "to": "also garbage"}]),
    ("to empty str", [{"from": f"weaviate://localhost/{CLS}/00000000-0000-0000-0000-000000000002/ref",
                       "to": ""}]),
]
defect = False
for label, payload in cases:
    kw = {} if payload is None else {"json": payload}
    st, body, raw = safe_request("POST", "/v1/batch/references", **kw)
    print(f"{label}: {st} {raw[:220]}")
    if st == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed"); sys.exit(2)
    if st >= 500:
        print(f"  DEFECT-SIGNAL: 5xx on {label}"); defect = True
    if st in (200, 201) and label in ("object body", "null body"):
        print(f"  DEFECT-SIGNAL: non-array body accepted on {label}"); defect = True

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass

if defect:
    print("VERDICT: DEFECT_FOUND — see signals above"); sys.exit(1)
print("VERDICT: NO_DEFECT — degenerate reference batches rejected cleanly")
