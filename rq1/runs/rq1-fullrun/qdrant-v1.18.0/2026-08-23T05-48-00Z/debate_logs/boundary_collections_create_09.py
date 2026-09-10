#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: special_value (strategy 4) — collection_name path parameter boundaries
Constraint: qdrant_type_collections_create_009 (name semantics) + create schema path param
Endpoint: PUT /collections/{collection_name} (contract path: collections+create)
exploration_target: novel_candidate
Block: chunk_collections+create-1of2
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned)
# Blindspot: BS-01
"""

import requests
import json
import sys
import os
import urllib.parse

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


VECTORS = {"vectors": {"size": 4, "distance": "Cosine"}}


def test_collection_names():
    names = [
        "bnd_crt_name_normal",          # control, should be 200
        "",                              # empty name -> 4xx (URL /collections/)
        " ",                             # single space
        "a" * 300,                       # very long name
        "bnd_crt_name_中文🎯",            # unicode
        "bnd_crt_name_%00nul",           # encoded NUL in path
        "bnd_crt_name_../../etc",        # traversal-ish
        "bnd_crt_name_'OR'1'='1",        # injection-ish
        "bnd_crt_name_𝕏́‍",        # RTL + combining + ZWJ
    ]
    defect = False
    for n in names:
        enc = urllib.parse.quote(n, safe="")
        status, body, raw = safe_request("PUT", f"/collections/{enc}", json=VECTORS)
        if status == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            return
        print(f"CASE name={n[:40]!r}: status={status} body={raw[:200]}")
        if status in (500, 502, 503, 504):
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — name={n[:40]!r} triggered 5xx")
            defect = True
        elif status in (200, 201) and n in ("", " ", "bnd_crt_name_%00nul"):
            # empty/space/NUL names accepted = Type1 (no valid identifier semantics)
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — name={n!r} accepted")
            defect = True
        if status in (200, 201):
            try:
                safe_request("DELETE", f"/collections/{enc}")
            except Exception:
                pass
    if not defect:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        test_collection_names()
    finally:
        pass
