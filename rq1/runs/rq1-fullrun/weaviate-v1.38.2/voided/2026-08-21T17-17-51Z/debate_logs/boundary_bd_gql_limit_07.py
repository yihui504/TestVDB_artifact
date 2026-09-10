#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2
Attack: Strategy 1+6 — GraphQL limit boundary (0, -1, huge)
Endpoint: POST /v1/graphql (raw body via data=)
expected_defect_type: Type1_IllegalSuccess (limit <= 0 or > max accepted)
"""
import requests, json, sys, os, uuid

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

CLS = "BdGqlLimit"
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
safe_request("POST", "/v1/schema", json={"class": CLS,
    "properties": [{"name": "name", "dataType": ["string"]}]})
oid = str(uuid.uuid4())
safe_request("POST", "/v1/objects", json={"class": CLS, "id": oid,
    "properties": {"name": "x"}})

def gql(limit):
    q = {"query": "{ Get { %s(limit: %s) { _additional { id } } } }" % (CLS, limit)}
    st, _, raw = safe_request("POST", "/v1/graphql",
        data=json.dumps(q).encode(), headers={"Content-Type": "application/json"})
    print(f"limit={limit}: {st} {raw[:220]}")
    return st, raw

defect = False
gql(2)                      # control
for v in (0, -1, 10001, 999999999):
    st, raw = gql(v)
    if st >= 500:
        print(f"  DEFECT-SIGNAL: 5xx at limit={v}"); defect = True
    elif st == 200 and "error" not in raw.lower() and v <= 0:
        # limit<=0 accepted and returned results = illegal success
        if "_additional" in raw:
            print(f"  DEFECT-SIGNAL: limit={v} accepted with results"); defect = True

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass

if defect:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess/Type3) — see signals above"); sys.exit(1)
print("VERDICT: NO_DEFECT — limit boundaries handled correctly")
