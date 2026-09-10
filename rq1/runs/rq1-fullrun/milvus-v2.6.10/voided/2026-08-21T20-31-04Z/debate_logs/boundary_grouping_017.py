#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.10 (REST v2 /v2/vectordb; contract '+' path translated to '/')
Attack: grouping boundary - groupSize extremes + strictGroupSize type confusion (strategy 1/6)
Constraint: milvus_range_entities_search_001 (adjacent groupSize semantics)
Endpoint: entities+search
Blindspot: BS-01 Parameter Coercion Trust / BS-04 Boundary Default Optimism
Note: Milvus v2 success envelope = HTTP 200 + JSON code==0 (v1 legacy code==200).
      Error = HTTP 200 + nonzero JSON code (e.g. 1100 invalid param). Verdict uses JSON code.
"""

import requests
import json
import sys
import os
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    BASE_URL = "http://localhost:19530"
    print("FALLBACK_TRIGGERED: TESTVDB_DB_URL not set, defaulting to contract live instance")
    print("[FALLBACK_JUSTIFIED: raw_knowledge.md Document Sources #13 'live instance http://localhost:19530']")
AUTH = os.environ.get("TESTVDB_AUTH_HEADER", "Bearer root:Milvus")
API = BASE_URL.rstrip("/") + "/v2/vectordb"
DIM = 8
TS = str(int(time.time()))


def safe_request(method, endpoint, payload=None, timeout=90):
    """endpoint uses contract '+' form, translated to '/'. Returns (http_status, body, raw_text)."""
    url = "%s/%s" % (API, endpoint.replace("+", "/"))
    try:
        r = requests.request(method, url, json=payload,
                             headers={"Content-Type": "application/json",
                                      "Authorization": AUTH},
                             timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)


def is_ok(body):
    """Milvus v2 success envelope: code==0 (or v1 legacy 200)."""
    return isinstance(body, dict) and body.get("code") in (0, 200)


def is_err_code(body, *codes):
    return isinstance(body, dict) and body.get("code") in codes


def cleanup_drop(coll):
    try:
        safe_request("POST", "collections+drop", {"collectionName": coll})
    except Exception:
        pass


def setup_quick(coll, dim=DIM):
    """Quick-mode create + insert + load + flush-ish wait. Returns (ok, msg)."""
    st, b, raw = safe_request("POST", "collections+create",
                              {"collectionName": coll, "dimension": dim})
    if not is_ok(b):
        return False, "create failed: " + raw[:300]
    st, b, raw = safe_request("POST", "entities+insert",
                              {"collectionName": coll,
                               "data": [{"id": 1, "vector": [0.1] * dim}]})
    if not is_ok(b):
        return False, "insert failed: " + raw[:300]
    for _ in range(30):
        st, b, raw = safe_request("POST", "collections+load", {"collectionName": coll})
        if is_ok(b):
            return True, "ready"
        time.sleep(1)
    return False, "load timeout"


COLL = "bnd_group_" + TS
ok, msg = setup_quick(COLL, DIM)
print("setup: %s" % msg)
cases = [
    ("groupSize 0", {"groupSize": 0}),
    ("groupSize -1", {"groupSize": -1}),
    ("groupSize 1e6", {"groupSize": 1000000}),
    ("groupSize huge+limit huge", {"groupSize": 1000000, "limit": 1000000}),
    ("groupSize str", {"groupSize": "4"}),
    ("groupSize null", {"groupSize": None}),
    ("strictGroupSize str", {"groupSize": 2, "strictGroupSize": "true"}),
    ("strictGroupSize int", {"groupSize": 2, "strictGroupSize": 1}),
    ("groupingField bogus", {"groupingField": "no_such_field"}),
    ("groupingField id", {"groupingField": "id", "groupSize": 2}),
]
for label, extra in cases:
    payload = {"collectionName": COLL, "data": [[0.1] * DIM], "limit": 10}
    payload.update(extra)
    st, b, raw = safe_request("POST", "entities+search", payload)
    ok = is_ok(b)
    code = b.get("code") if isinstance(b, dict) else None
    print("%s -> http=%s code=%s ok=%s raw=%s" % (label, st, code, ok, raw[:220]))
    if st >= 500 or (isinstance(raw, str) and any(
            k in raw.lower() for k in ["panic", "oom", "out of memory", "capacity overflow", "killed"])):
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - %s crashed server" % label)
        sys.exit(1)
st, b, raw = safe_request("POST", "collections+list", {})
alive = is_ok(b)
print("server alive: %s" % alive)
cleanup_drop(COLL)
if not alive:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - server degraded after grouping fuzz")
else:
    print("VERDICT: NO_DEFECT")
