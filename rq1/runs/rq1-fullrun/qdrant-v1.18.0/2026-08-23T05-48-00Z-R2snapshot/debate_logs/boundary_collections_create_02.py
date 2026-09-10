#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: type_confusion (strategy 2) — quantization_config enums (product.compression / scalar.type+quantile / binary.encoding)
Constraint: qdrant_type_collections_create_004 + 005 + 006
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


def test_quantization_enums():
    cases = [
        ("product.compression=x2 invalid", {**BASE, "quantization_config": {"product": {"compression": "x2"}}}, "compression"),
        ("product.compression=null", {**BASE, "quantization_config": {"product": {"compression": None}}}, "compression"),
        ("product.compression=8 int", {**BASE, "quantization_config": {"product": {"compression": 8}}}, "compression"),
        ("scalar.type=int16 invalid", {**BASE, "quantization_config": {"scalar": {"type": "int16", "quantile": 0.8}}}, "type"),
        ("scalar.type=null", {**BASE, "quantization_config": {"scalar": {"type": None, "quantile": 0.8}}}, "type"),
        ("scalar.quantile=0.4 below min", {**BASE, "quantization_config": {"scalar": {"type": "int8", "quantile": 0.4}}}, "quantile"),
        ("scalar.quantile=1.1 above max", {**BASE, "quantization_config": {"scalar": {"type": "int8", "quantile": 1.1}}}, "quantile"),
        ("scalar.quantile='0.8' string", {**BASE, "quantization_config": {"scalar": {"type": "int8", "quantile": "0.8"}}}, "quantile"),
        ("binary.encoding=four_bits invalid", {**BASE, "quantization_config": {"binary": {"encoding": "four_bits"}}}, "encoding"),
        ("binary.encoding=null", {**BASE, "quantization_config": {"binary": {"encoding": None}}}, "encoding"),
        ("quantization_config='scalar' string", {**BASE, "quantization_config": "scalar"}, "quantization"),
        ("quantization_config=[] array", {**BASE, "quantization_config": []}, "quantization"),
    ]
    defect = False
    counter = 0
    used = []
    for name, payload, hint in cases:
        counter += 1
        cname = f"bnd_crt_qz_{counter}"
        used.append(cname)
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
        test_quantization_enums()
    finally:
        pass
