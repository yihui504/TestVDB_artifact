#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2
Attack: Strategy 1+2 — replicationFactor boundary + type
Constraint: weaviate_type_create_collection_004
Endpoint: POST /v1/schema
expected_defect_type: Type1_IllegalSuccess (0 / -1 accepted)
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

cases = [(1, "ctl"), (0, "Zero"), (-1, "Neg1"), ("3", "Str")]
defect = False
for val, tag in cases:
    cls = f"BdRepl{tag}"
    try: safe_request("DELETE", f"/v1/schema/{cls}")
    except Exception: pass
    st, body, raw = safe_request("POST", "/v1/schema",
        json={"class": cls, "replicationConfig": {"factor": val}})
    print(f"replicationConfig.factor={val!r}: {st} {raw[:160]}")
    if st in (200, 201):
        st2, b2, _ = safe_request("GET", f"/v1/schema/{cls}")
        got = ((b2 or {}).get("replicationConfig") or {}).get("factor", "<dropped>")
        print(f"  read-back factor = {got!r}")
        if isinstance(val, int) and val < 1 and got == val:
            print("  DEFECT-SIGNAL: illegal factor persisted verbatim")
            defect = True
    try: safe_request("DELETE", f"/v1/schema/{cls}")
    except Exception: pass

if defect:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — replicationConfig.factor < 1 accepted"); sys.exit(1)
print("VERDICT: NO_DEFECT — illegal replication factors rejected")
