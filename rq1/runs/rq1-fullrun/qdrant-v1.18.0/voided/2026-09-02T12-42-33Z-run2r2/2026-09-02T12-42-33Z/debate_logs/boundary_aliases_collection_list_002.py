#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value (collection_name string boundary min-1: empty segment) × qdrant_behavioral_aliases_collection_list_001 (endpoint aliases+collection+list; GET /collections/{collection_name}/aliases)
Oracle: collection_name='' (GET /collections//aliases) → 4xx reject (route 404 or validation 400); a 2xx/3xx = Type1_IllegalSuccess, a 5xx = Type3_RuntimeFailure
Constraint: qdrant_behavioral_aliases_collection_list_001 (behavioral assertion: "returns 200 with a list of {alias, collection_name}; 404 for an unknown collection" — collection_name is required:true path param, min length 1 so '' is out of the legal domain)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collection-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""

import json
import os
import sys
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap: three-layer fallback (env -> upward walk -> contract target) ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    _root = Path(__file__).resolve()
    for _p in (_root, *list(_root.parents)):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or TARGET != "qdrant":
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)


def safe_request(method, endpoint, json=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.request(
            method=method,
            url=url,
            json=json,
            headers=headers,
            timeout=timeout
        )
        status_code = response.status_code
        raw_text = response.text

        try:
            body = response.json()
        except Exception:
            body = raw_text

        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def main():
    # Act: empty collection_name (length 0 — below the minimum legal name length of 1).
    # The empty path segment must not match any collection; qdrant must reject with 4xx.
    s, _, raw = safe_request("GET", "/collections//aliases", timeout=30)
    print(f"GET /collections//aliases (empty collection_name) -> status={s}")
    print(f"raw: {raw[:600]}")

    # Assert
    if s <= 0:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on probe (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
        return
    if 500 <= s <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — empty collection_name "
              f"triggered server error {s} (should be a clean 4xx)")
        return
    if 200 <= s <= 399:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — empty collection_name "
              f"accepted with {s} (a collection with no name cannot legally exist; "
              f"expected 4xx reject)")
        return
    # 4xx (400/404/...): clean rejection of the empty name
    print("OK: empty collection_name rejected with 4xx as expected")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
