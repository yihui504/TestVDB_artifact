#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2
Attack: Strategy 1+2 — DELETE /batch/objects resources & match fields
Cases: resources not object, resources null, match.class nonexistent class
       (control: existing class), match.class empty string, match.where wrong type.
expected_defect_type: Type3_RuntimeFailure / Type1_IllegalSuccess / Type2
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

CLS = "BdBdRes9"
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
safe_request("POST", "/v1/schema", json={"class": CLS,
    "properties": [{"name": "name", "dataType": ["string"]}]})

WHERE = {"operator": "Equal", "path": ["name"], "valueText": "zzz-no-match-zzz"}
cases = [
    ("resources as string", {"match": {"class": CLS, "where": WHERE}, "resources": "x"}),
    ("resources as array", {"match": {"class": CLS, "where": WHERE}, "resources": [1]}),
    ("resources null", {"match": {"class": CLS, "where": WHERE}, "resources": None}),
    ("resources empty", {"match": {"class": CLS, "where": WHERE}, "resources": {}}),
    ("nonexistent class", {"match": {"class": "NopeDoesNotExist", "where": WHERE}}),
    ("class empty string", {"match": {"class": "", "where": WHERE}}),
    ("where as string", {"match": {"class": CLS, "where": "not-a-filter"}}),
    ("where as array", {"match": {"class": CLS, "where": [WHERE]}}),
]
defect = False
for label, payload in cases:
    st, body, raw = safe_request("DELETE", "/v1/batch/objects", json=payload)
    print(f"{label}: {st} {raw[:200]}")
    if st == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed"); sys.exit(2)
    if st >= 500:
        print(f"  DEFECT-SIGNAL: 5xx on {label}"); defect = True

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass

if defect:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 5xx on degenerate batch-delete input"); sys.exit(1)
print("VERDICT: NO_DEFECT — all degenerate inputs rejected with 4xx")
