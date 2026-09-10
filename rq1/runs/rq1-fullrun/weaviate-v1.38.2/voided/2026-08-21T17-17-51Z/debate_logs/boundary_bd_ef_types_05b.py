#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2 (follow-up: functional impact of silent-drop)
Attack: Strategy 2 + read-back functional probe — type-confused HNSW fields
Constraints: weaviate_type_create_collection_001/002/003
Endpoint: POST /v1/schema
Script 05 found: string "100" / [100] / {"v":1} in dynamicEfMin/Max/flatSearchCutoff
are accepted 200 then silently coerced to 0 at read-back (silent-drop channel,
NOT rejected). 0 is OUTSIDE the documented valid range (default 100/500/40000,
must be positive int). This script confirms the functional impact: a nearVector
search on a class created with dynamicEfMin="100" exercises the corrupted config.
expected_defect_type: Type1_IllegalSuccess (silent coercion to invalid value 0)
"""
import requests, json, sys, os, uuid

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set"); sys.exit(2)

def safe_request(method, path, **kw):
    try:
        r = requests.request(method, BASE_URL + path, timeout=90, **kw)
        try: body = r.json()
        except Exception: body = None
        return r.status_code, body, r.text
    except Exception as e:
        return 0, None, str(e)

CLS = "BdEfDrop2"
try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass

# attack: string "100" in dynamicEfMin — accepted, silently becomes 0
st, body, raw = safe_request("POST", "/v1/schema", json={"class": CLS,
    "vectorIndexConfig": {"dynamicEfMin": "100"}})
print(f"ATTACK dynamicEfMin='100' (string): {st}")
st2, b2, _ = safe_request("GET", f"/v1/schema/{CLS}")
got = ((b2 or {}).get("vectorIndexConfig") or {}).get("dynamicEfMin", "<absent>")
print(f"read-back dynamicEfMin = {got!r} (default is 100; 0 is invalid)")

# functional probe: insert + nearVector — does corrupted ef config break search?
ids = []
for i in range(3):
    oid = str(uuid.uuid4())
    ids.append(oid)
    st3, _, raw3 = safe_request("POST", "/v1/objects", json={
        "class": CLS, "id": oid, "vector": [0.1 * (i + 1)] * 8})
    print(f"insert {i}: {st3}")

q = {"query": "{ Get { %s(nearVector: {vector: [0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1]}, limit: 3) { _additional { id } } } }" % CLS}
st4, _, raw4 = safe_request("POST", "/v1/graphql", data=json.dumps(q).encode(),
                            headers={"Content-Type": "application/json"})
print(f"nearVector search: {st4} {raw4[:300]}")

try: safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception: pass

if st in (200, 201) and got == 0:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — string in dynamicEfMin accepted 200, "
          "silently coerced to invalid 0 (valid default 100), no diagnostic")
    sys.exit(1)
if st in (200, 201) and isinstance(got, str):
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — string persisted verbatim in int field"); sys.exit(1)
print("VERDICT: NO_DEFECT — field rejected or correctly defaulted")
