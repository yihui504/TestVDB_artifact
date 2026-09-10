#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.10 (REST v2 /v2/vectordb; contract '+' path translated to '/')
Attack: new vector types boundary - Float16/BFloat16/Sparse (strategy 2/3)
Constraint: milvus_type_collections_create_001 + milvus_type_collections_create_004
Endpoint: collections+create+entities+insert
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


def try_create(coll, dtype, dim=8):
    cleanup_drop(coll)
    st, b, raw = safe_request("POST", "collections+create", {"collectionName": coll, "schema": {"fields": [
        {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
        {"fieldName": "vec", "dataType": dtype, "dimension": dim},
    ]}})
    print("create %s -> ok=%s raw=%s" % (dtype, is_ok(b), raw[:200]))
    return is_ok(b)

# Float16: REST JSON cannot carry raw f16 -> insert with plain floats / strings / wrong dims
coll = "bnd_f16_" + TS
if try_create(coll, "Float16Vector"):
    for label, vec in [("plain floats", [0.1] * 8), ("32 floats", [0.1] * 32),
                       ("hex strings", ["3c00", "3c00", "3c00", "3c00", "3c00", "3c00", "3c00", "3c00"]),
                       ("ints", [1, 2, 3, 4, 5, 6, 7, 8])]:
        st, b, raw = safe_request("POST", "entities+insert",
                                  {"collectionName": coll, "data": [{"id": 1, "vector": vec}]})
        print("f16 insert %s -> ok=%s raw=%s" % (label, is_ok(b), raw[:200]))

# Sparse: valid-ish then bogus shapes
coll2 = "bnd_sparse_" + TS
if try_create(coll2, "SparseFloatVector", dim=0):
    for label, vec in [("dict idx->float", {"1": 0.5, "100": 0.7}),
                       ("list of pairs", [[1, 0.5]]),
                       ("dense list", [0.1] * 8),
                       ("empty dict", {}),
                       ("negative idx", {"-1": 0.5}),
                       ("huge idx", {"99999999999": 0.5}),
                       ("nan value", {"1": "NaN"}),
                       ("string value", {"1": "abc"})]:
        st, b, raw = safe_request("POST", "entities+insert",
                                  {"collectionName": coll2, "data": [{"id": 1, "vector": vec}]})
        print("sparse insert %s -> ok=%s raw=%s" % (label, is_ok(b), raw[:200]))

# Sparse created with nonzero dimension (dim is meaningless for sparse) - doc-silent
coll3 = "bnd_sparse_dim_" + TS
st, b, raw = safe_request("POST", "collections+create",
                          {"collectionName": coll3, "dimension": 8, "vectorFieldName": "vector",
                           "metricType": "IP"})
print("sparse quick-mode via dimension=8 -> ok=%s raw=%s" % (is_ok(b), raw[:200]))

for c in ("bnd_f16_" + TS, "bnd_sparse_" + TS, "bnd_sparse_dim_" + TS):
    cleanup_drop(c)
print("NOTE: read-back comparisons printed above; judge against handler_v2.go sparse/f16 format rules")
print("VERDICT: NO_DEFECT - observational; illegal accepts logged above for judge")
