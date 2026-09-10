#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2
Attack: Strategy 2 (type confusion) — string/float in integer HNSW fields
Constraints: weaviate_type_create_collection_001/002/003
Endpoint: POST /v1/schema
expected_defect_type: Type3_RuntimeFailure (5xx on unmarshal failure) / Type2
"""
import requests, json, sys, os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set"); sys.exit(2)

def safe_request(method, path, **kw):
    try:
        r = requests.request(method, BASE_URL + path, timeout=60, **kw)
        try: body = r.json()
        except Exception: body = None
        return r.status_code, body, r.text
    except Exception as e:
        return 0, None, str(e)

cases = [
    ("dynamicEfMin", "100"),      # string
    ("dynamicEfMin", 100.7),      # fractional float
    ("dynamicEfMax", [100]),      # array
    ("flatSearchCutoff", {"v": 1}),  # object
    ("dynamicEfMin", None),       # explicit null
]
cls_base = "BdEfType"
defect = False
for field, val in cases:
    cls = cls_base + str(abs(hash((field, str(val)))) % 10000)
    try: safe_request("DELETE", f"/v1/schema/{cls}")
    except Exception: pass
    st, body, raw = safe_request("POST", "/v1/schema",
        json={"class": cls, "vectorIndexConfig": {field: val}})
    print(f"{field}={val!r} ({type(val).__name__}): {st} {raw[:180]}")
    if st >= 500:
        print(f"  DEFECT-SIGNAL: 5xx on {field}={val!r}")
        defect = True
    if st in (200, 201):
        # read back: if value silently dropped/normalized, Type2; if persisted wrong type, Type1
        st2, b2, _ = safe_request("GET", f"/v1/schema/{cls}")
        got = ((b2 or {}).get("vectorIndexConfig") or {}).get(field, "<dropped>")
        print(f"  read-back {field} = {got!r}")
        if isinstance(val, str) and got == val:
            print("  DEFECT-SIGNAL: string persisted verbatim in int field")
            defect = True
    try: safe_request("DELETE", f"/v1/schema/{cls}")
    except Exception: pass

if defect:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure/Type1_IllegalSuccess) — see signals above"); sys.exit(1)
print("VERDICT: NO_DEFECT — all type confusions rejected cleanly")
