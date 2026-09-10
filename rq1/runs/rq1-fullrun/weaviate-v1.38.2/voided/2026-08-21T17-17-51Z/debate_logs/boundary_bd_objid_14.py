#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2
Attack: Strategy 4 (special values) — object id format boundaries
Endpoint: POST /v1/objects, GET /v1/objects/{class}/{id}
Cases: id empty string, NUL byte in id (raw data=), lone-surrogate in property
       value (raw data=), control: valid uuid.
expected_defect_type: Type3_RuntimeFailure / Type1_IllegalSuccess (silent accept)
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

CLS = "BdObjId14"
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
safe_request("POST", "/v1/schema", json={"class": CLS,
    "properties": [{"name": "name", "dataType": ["string"]}]})

defect = False

# control: valid uuid
st, _, raw = safe_request("POST", "/v1/objects", json={
    "class": CLS, "id": str(uuid.uuid4()), "properties": {"name": "ok"}})
print(f"CONTROL valid uuid: {st}")

# id empty string
st, _, raw = safe_request("POST", "/v1/objects", json={
    "class": CLS, "id": "", "properties": {"name": "x"}})
print(f"id empty string: {st} {raw[:200]}")
if st >= 500: defect = True

# NUL byte in id — raw bytes to bypass client serialization
raw_body = (b'{"class":"' + CLS.encode() + b'","id":"a\x00b",'
            b'"properties":{"name":"nul"}}')
st, _, raw = safe_request("POST", "/v1/objects", data=raw_body,
                          headers={"Content-Type": "application/json"})
print(f"id with NUL byte: {st} {raw[:200]}")
if st >= 500:
    print("  DEFECT-SIGNAL: 5xx on NUL id"); defect = True
elif st in (200, 201):
    try:
        got = json.loads(raw)
        rid = got.get("id", "")
        st2, _, raw2 = safe_request("GET", f"/v1/objects/{CLS}/{rid}")
        print(f"  read-back NUL id: {st2} {raw2[:150]}")
        print("  DEFECT-SIGNAL: NUL byte in id silently accepted (Type1 candidate, judge-doc)")
        defect = True
    except Exception:
        pass

# lone surrogate in property value — raw bytes
raw_body = (b'{"class":"' + CLS.encode() +
            b'","properties":{"name":"bad\\ud800surrogate"}}')
st, _, raw = safe_request("POST", "/v1/objects", data=raw_body,
                          headers={"Content-Type": "application/json"})
print(f"lone surrogate value: {st} {raw[:200]}")
if st >= 500:
    print("  DEFECT-SIGNAL: 5xx on lone surrogate"); defect = True

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass

if defect:
    print("VERDICT: DEFECT_FOUND — see signals above"); sys.exit(1)
print("VERDICT: NO_DEFECT — id/value special boundaries handled without 5xx")
