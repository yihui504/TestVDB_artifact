#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: type_confusion (strategy 2) — datatype / sparse_vectors config
Constraint: qdrant_type_collections_create_007 + 008 + 009
Endpoint: PUT /collections/{collection_name} (contract path: collections+create)
exploration_target: novel_candidate
Block: chunk_collections+create-1of2
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned)
# Blindspot: BS-01 Parameter Type Coercion Trust
"""

import requests
import json
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")


def safe_request(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else {}
        except (json.JSONDecodeError, ValueError):
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""


BASE = {"vectors": {"size": 4, "distance": "Cosine"}}


def test_datatype_and_sparse():
    cases = [
        ("datatype=int4 invalid", {**BASE, "datatype": "int4"}, "datatype"),
        ("datatype=null", {**BASE, "datatype": None}, "datatype"),
        ("datatype=123", {**BASE, "datatype": 123}, "datatype"),
        ("turbo4 on sparse vectors (must be rejected)", {
            "vectors": {"size": 4, "distance": "Cosine"},
            "sparse_vectors": {"sp": {"datatype": "turbo4"}}}, "turbo4"),
        ("sparse_vectors.sp.distance=Cosine (sparse must be Dot-only, not settable)", {
            "vectors": {"size": 4, "distance": "Cosine"},
            "sparse_vectors": {"sp": {"distance": "Cosine"}}}, "distance"),
        ("sparse_vectors.sp.size set (sparse has no size)", {
            "vectors": {"size": 4, "distance": "Cosine"},
            "sparse_vectors": {"sp": {"size": 8}}}, "size"),
        ("sparse_vectors=[] array", {**BASE, "sparse_vectors": []}, "sparse"),
        ("sparse_vectors=null", {**BASE, "sparse_vectors": None}, "sparse"),
        # 009: sparse/dense name disjoint — same name for dense map and sparse map
        ("dense+sparse name collision v", {
            "vectors": {"v": {"size": 4, "distance": "Cosine"}},
            "sparse_vectors": {"v": {}}}, "name"),
    ]
    defect = False
    counter = 0
    for name, payload, hint in cases:
        counter += 1
        cname = f"bnd_crt_sp_{counter}"
        status, body, raw = safe_request("PUT", f"/collections/{cname}", json=payload)
        print(f"CASE {name}: status={status} body={raw[:300]}")
        if status == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            return
        # 008 nuance: sparse distance=Dot-settable might be silently ignored (silent-drop)
        # -> if 200, describe back to check persisted value
        if status in (200, 201):
            if name.startswith("sparse_vectors.sp."):
                s2, b2, raw2 = safe_request("GET", f"/collections/{cname}")
                print(f"  DESCRIBE: {raw2[:400]}")
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {name} accepted with 200 (check describe above for persisted value)")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {name} accepted with {status}")
            defect = True
        elif status in (400, 422) and hint.lower() not in raw.lower():
            print(f"NOTE Type2 — {name} rejected but error lacks '{hint}': {raw[:200]}")
        try:
            safe_request("DELETE", f"/collections/{cname}")
        except Exception:
            pass
    if not defect:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        test_datatype_and_sparse()
    finally:
        pass
