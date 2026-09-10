#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value (collection_name unknown-value branch) × qdrant_behavioral_aliases_collection_list_001 — negative direction of the assertion's 404 promise (Blindspot: BS-01 Parameter Validation Optimism / BS-04 Boundary Default Optimism)
Oracle: GET alias-list with a well-formed but nonexistent collection_name → 404 per assertion (a 200-with-list would be Type1_IllegalSuccess, a 5xx Type3_RuntimeFailure)
Constraint: qdrant_behavioral_aliases_collection_list_001 (behavioral assertion: "returns 200 with a list of {alias, collection_name}; 404 for an unknown collection")
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collection-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""

import json
import os
import sys
import uuid
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
    # Act: a well-formed collection_name that no collection can match
    # (random suffix makes a name clash with a sandbox collection impossible).
    unknown = "bacl4missing_" + uuid.uuid4().hex
    s, _, raw = safe_request("GET", f"/collections/{unknown}/aliases", timeout=30)
    print(f"GET /collections/{unknown}/aliases -> status={s}")
    print(f"raw: {raw[:600]}")

    # Assert: assertion promises 404 for an unknown collection
    if s <= 0:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on probe (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
        return
    if 500 <= s <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — alias-list GET on unknown "
              f"collection triggered server error {s} (promise: 404)")
        return
    if s == 404:
        print("OK: unknown collection rejected with 404 as the assertion promises")
        print("VERDICT: NO_DEFECT")
        return
    if 200 <= s <= 399:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — unknown collection returned "
              f"{s} with a body instead of the promised 404: {raw[:300]}")
        return
    # Other 4xx (e.g. 400): still a clean rejection; status nuance recorded for the judge
    print(f"NOTE: unknown collection rejected with {s} (not the promised 404 but a clean "
          f"4xx rejection; raw above for judge)")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
