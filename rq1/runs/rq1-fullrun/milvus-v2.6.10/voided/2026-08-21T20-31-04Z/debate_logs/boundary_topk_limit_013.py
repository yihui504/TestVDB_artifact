#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.10 (REST v2 /v2/vectordb; contract '+' path translated to '/')
Attack: range boundary - limit/offset in [1,16384] (strategy 1 + 6)
Constraint: milvus_range_entities_search_001
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


COLL = "bnd_topk_" + TS
ok, msg = setup_quick(COLL, DIM)
print("setup: %s" % msg)
qvec = [0.1] * DIM

cases = [(0, 0), (1, 0), (-1, 0), (16383, 0), (16384, 0), (16385, 0), (100000, 0),
         (2147483647, 0), (1000000, 1000000), (10, 16374), (10, 16375), (10, 1000000),
         ("100", 0), (None, 0), (1.5, 0)]
results = []
for limit, offset in cases:
    payload = {"collectionName": COLL, "data": [qvec]}
    if limit is not None:
        payload["limit"] = limit
    if offset:
        payload["offset"] = offset
    st, b, raw = safe_request("POST", "entities+search", payload)
    ok = is_ok(b)
    code = b.get("code") if isinstance(b, dict) else None
    print("limit=%r offset=%r -> http=%s code=%s ok=%s raw=%s" % (limit, offset, st, code, ok, raw[:180]))
    if st >= 500 or (isinstance(raw, str) and any(
            k in raw.lower() for k in ["oom", "panic", "out of memory", "killed"])):
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - limit=%r offset=%r crashed" % (limit, offset))
        sys.exit(1)
    results.append((limit, offset, ok))
cleanup_drop(COLL)
bad = []
for limit, offset, ok in results:
    if not ok:
        continue
    if isinstance(limit, int) and not isinstance(limit, bool) and limit < 1:
        bad.append((limit, offset))
    if isinstance(limit, str) or limit is None:
        bad.append((limit, offset))
    if isinstance(limit, int) and limit + (offset or 0) > 16384:
        bad.append((limit, offset))
if bad:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - out-of-range limit/offset accepted: %r" % bad)
else:
    print("VERDICT: NO_DEFECT")
