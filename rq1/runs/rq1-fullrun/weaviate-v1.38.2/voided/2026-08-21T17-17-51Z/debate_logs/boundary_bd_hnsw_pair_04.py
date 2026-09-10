#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2
Attack: Strategy 1 (paired range boundary) — dynamicEfMin <= dynamicEfMax
Constraint: weaviate_range_create_collection_001
Endpoint: POST /v1/schema
expected_defect_type: Type1_IllegalSuccess + read-back verification
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

CLS = "BdEfPair"
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass

# attack: dynamicEfMin > dynamicEfMax
st, body, raw = safe_request("POST", "/v1/schema", json={"class": CLS,
    "vectorIndexConfig": {"dynamicEfMin": 500, "dynamicEfMax": 100}})
print(f"ATTACK efMin=500 > efMax=100: {st}")
print(f"Body: {raw[:300]}")

defect = False
if st in (200, 201):
    st2, b2, raw2 = safe_request("GET", f"/v1/schema/{CLS}")
    cfg = (b2 or {}).get("vectorIndexConfig") or {}
    print(f"read-back efMin={cfg.get('dynamicEfMin')} efMax={cfg.get('dynamicEfMax')}")
    if cfg.get("dynamicEfMin", 0) > cfg.get("dynamicEfMax", 0):
        print("read-back confirms inverted pair persisted verbatim")
        defect = True
    else:
        print("pair was normalized on read-back (Type2 candidate — silent rewrite)")
        defect = "norm"
elif st >= 500:
    defect = True

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass

if defect is True:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — dynamicEfMin > dynamicEfMax accepted/persisted"); sys.exit(1)
if defect == "norm":
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — inverted pair accepted then silently rewritten at read-back"); sys.exit(1)
print("VERDICT: NO_DEFECT — inverted ef pair rejected")
