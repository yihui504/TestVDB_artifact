#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2
Attack: Strategy 2 — GraphQL cursor (after:) & offset type/boundary confusion
Endpoint: POST /v1/graphql (raw body)
Cases: after: 123 (int), after: "" , after: "garbage", offset: -1, offset: 0,
       autocut with negative, hybrid alpha out of [0,1], nearVector distance negative.
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
        r = requests.request(method, BASE_URL + path, timeout=60, **kw)
        try: body = r.json()
        except Exception: body = None
        return r.status_code, body, r.text
    except Exception as e:
        return 0, None, str(e)

CLS = "BdGqlCur12"
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass
safe_request("POST", "/v1/schema", json={"class": CLS,
    "properties": [{"name": "name", "dataType": ["string"]}]})
for i in range(3):
    safe_request("POST", "/v1/objects", json={"class": CLS,
        "id": str(uuid.uuid4()), "properties": {"name": f"n{i}"}, "vector": [0.1]*4})

def gql(inner):
    q = {"query": "{ Get { %s(%s) { name } } }" % (CLS, inner)}
    return safe_request("POST", "/v1/graphql",
        data=json.dumps(q).encode(), headers={"Content-Type": "application/json"})

cases = [
    ("after int", 'after: 123, limit: 2'),
    ("after empty str", 'after: "", limit: 2'),
    ("after garbage", 'after: "not-a-uuid-order", limit: 2'),
    ("after null", 'after: null, limit: 2'),
    ("offset -1", 'offset: -1, limit: 2'),
    ("offset 0", 'offset: 0, limit: 2'),
    ("autocut -1", 'autocut: -1, limit: 2'),
    ("hybrid alpha 5", 'hybrid: {query: "n", alpha: 5}, limit: 2'),
    ("nearVector dist -1", 'nearVector: {vector: [0.1,0.1,0.1,0.1], distance: -1}, limit: 2'),
]
defect = False
for label, inner in cases:
    st, _, raw = gql(inner)
    print(f"{label}: {st} {raw[:220]}")
    if st == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed"); sys.exit(2)
    if st >= 500:
        print(f"  DEFECT-SIGNAL: HTTP 5xx on {label}"); defect = True

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass

if defect:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 5xx on GraphQL boundary input"); sys.exit(1)
print("VERDICT: NO_DEFECT — GraphQL boundary inputs handled without 5xx")
