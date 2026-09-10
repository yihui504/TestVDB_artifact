#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-input / character-boundary (NUL %00, lone-surrogate %ED%A0%80, encoded-slash %2F, control char %01 in collection_name) × qdrant_behavioral_aliases_collection_list_001 (endpoint aliases+collection+list; GET /collections/{collection_name}/aliases) (Blindspot: BS-01 Parameter Type Coercion Trust)
Oracle: each malformed/encoded collection_name → clean 4xx reject; any 5xx/panic = Type3_RuntimeFailure, any 2xx acceptance = Type1_IllegalSuccess (none of these names can legally exist)
Constraint: qdrant_behavioral_aliases_collection_list_001 (behavioral assertion: "returns 200 with a list of {alias, collection_name}; 404 for an unknown collection" — malformed names must not crash the list endpoint nor resolve to a phantom 200)
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


# Names that no collection can legally own, pushed through the path segment
# as raw URL-escaped bytes so the server (not the client) does the decoding:
PROBES = [
    ("nul-byte",      "a%00b"),          # NUL byte inside the name
    ("lone-surrogate", "x%ED%A0%80y"),   # UTF-16 lone surrogate (illegal Unicode)
    ("encoded-slash", "a%2Fb"),          # '/' smuggled through percent-encoding
    ("control-char",  "c%01d"),          # control char inside the name
]


def main():
    verdict = None  # set on the first defect; all-clean -> NO_DEFECT
    for label, enc_name in PROBES:
        s, _, raw = safe_request("GET", f"/collections/{enc_name}/aliases", timeout=30)
        print(f"probe [{label}] name={enc_name!r} -> status={s}")
        print(f"raw: {raw[:400]}")
        if s <= 0:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"transport failure on probe [{label}] (healthz status={hs}: {hraw[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — malformed collection_name "
                  f"[{label}] triggered server error {s} (should be a clean 4xx)")
            return
        if 200 <= s <= 399:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — malformed collection_name "
                  f"[{label}] accepted with {s} (name cannot legally exist; expected 4xx)")
            return
        print(f"OK: probe [{label}] rejected with {s} (4xx)")
    if verdict is None:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
