#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: type_confusion (strategy 2) — sharding_method enum + consistency of per-name sizes (010/011)
Endpoint: PUT /collections/{collection_name} (contract path: collections+create)
Constraint: qdrant_type_collections_create_010 + 011
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


def test_sharding_and_names():
    cases = [
        ("sharding_method=round_robin invalid", {
            "vectors": {"size": 4, "distance": "Cosine"}, "sharding_method": "round_robin"}, "sharding"),
        ("sharding_method=null", {
            "vectors": {"size": 4, "distance": "Cosine"}, "sharding_method": None}, "sharding"),
        ("sharding_method=123", {
            "vectors": {"size": 4, "distance": "Cosine"}, "sharding_method": 123}, "sharding"),
        ("sharding_method='' empty", {
            "vectors": {"size": 4, "distance": "Cosine"}, "sharding_method": ""}, "sharding"),
        # 010: named dense vectors must each have own size; size consistency is per-name
        # (multi-name with different sizes IS allowed per-name — the constraint is about
        #  consistency per name, so create a name given two different config shapes)
        ("vectors map with '' empty name", {
            "vectors": {"": {"size": 4, "distance": "Cosine"}}}, "name"),
        ("vectors map value=null for name a", {
            "vectors": {"a": None}}, "vectors"),
    ]
    defect = False
    counter = 0
    for name, payload, hint in cases:
        counter += 1
        cname = f"bnd_crt_sh_{counter}"
        status, body, raw = safe_request("PUT", f"/collections/{cname}", json=payload)
        print(f"CASE {name}: status={status} body={raw[:300]}")
        if status == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            return
        if status in (200, 201):
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
        test_sharding_and_names()
    finally:
        pass
