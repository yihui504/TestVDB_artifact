#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.2
Attack: Strategy 1 (range boundary) — shardingConfig.desiredCount
Constraint: weaviate_range_sharding_desired_count_001 (desiredCount >= 1)
Endpoint: POST /v1/schema
expected_defect_type: Type1_IllegalSuccess (negative accepted — GT #11729 channel)
Note: read-back via GET /v1/schema/{class} to verify persisted value.
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

def try_count(value, cls):
    try: safe_request("DELETE", f"/v1/schema/{cls}")
    except Exception: pass
    st, body, raw = safe_request("POST", "/v1/schema", json={
        "class": cls, "shardingConfig": {"desiredCount": value}})
    print(f"desiredCount={value!r}: create -> {st} {raw[:200]}")
    if st in (200, 201):
        st2, b2, raw2 = safe_request("GET", f"/v1/schema/{cls}")
        got = None
        if b2: got = (b2.get("shardingConfig") or {}).get("desiredCount")
        print(f"  read-back desiredCount = {got!r}")
    return st

results = {}
# control valid
results["control_1"] = try_count(1, "BdShardCtl")
# boundary attacks
results["zero"] = try_count(0, "BdShardZero")
results["neg1"] = try_count(-1, "BdShardNeg1")

defect = False
if results.get("zero", 0) in (200, 201):
    print("DEFECT-SIGNAL: desiredCount=0 accepted at create")
    defect = True
if results.get("neg1", 0) in (200, 201):
    print("DEFECT-SIGNAL: desiredCount=-1 accepted at create (GT #11729 channel)")
    defect = True

for cls in ("BdShardCtl", "BdShardZero", "BdShardNeg1"):
    try: safe_request("DELETE", f"/v1/schema/{cls}")
    except Exception: pass

if defect:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — desiredCount < 1 accepted at schema create")
    sys.exit(1)
print("VERDICT: NO_DEFECT — desiredCount < 1 rejected at create")
