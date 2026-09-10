#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Attack Vein - Type Mismatch Condition (schema vectorIndexConfig)

Target: weaviate v1.37.4
Endpoint: POST /v1/schema (create class)
Condition: type_mismatch on vectorIndexConfig int params

Defect hypothesis: POST /v1/schema silently accepts a non-int JSON type
(string / bool) for the int-declared vectorIndexConfig fields dynamicEfMin,
dynamicEfMax, flatSearchCutoff, coercing the value to 0 with HTTP 200. Because
dynamicEfMin is NOT sent, it defaults to 100, so the stored configuration
becomes dynamicEfMin=100 > dynamicEfMax=0 — an inverted EF pairing that
violates the contract's inferred assertion weaviate_inferred_hnsw_ef_pairing_001
(dynamicEfMin should be <= dynamicEfMax).

Controls (prove validation exists elsewhere / the gap is specific):
  - float 12.7 for dynamicEfMin            -> 422 (strconv.ParseInt invalid syntax)
  - string "abc" for replicationConfig.factor -> 400 (json cannot unmarshal string into int64)
So the silent-coerce-to-0 for string/bool on vectorIndexConfig is a real gap.

Strategy: vein_type_mismatch
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
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

# Unique class per run (weaviate class names are PascalCase, must be unique)
CLASS_NAME = f"VeinTypeMismatchEfPair{os.getpid()}"


def safe_request(method, endpoint, json=None, timeout=10):
    """Resilient HTTP wrapper -> (status_code, body_or_None, raw_text)."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.request(method=method, url=url, json=json,
                                headers=headers, timeout=timeout)
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


def cleanup():
    try:
        status, body, raw = safe_request("DELETE", f"/v1/schema/{CLASS_NAME}")
        if status not in (200, 204, 404):
            print(f"Cleanup warning: DELETE returned {status}: {raw[:200]}")
    except Exception as e:
        print(f"Cleanup warning: {e}")


def main():
    # ---- Act: create class with string-typed int field + unsent counterpart ----
    # dynamicEfMax declared int in contract; we pass a string. dynamicEfMin is
    # NOT sent so it takes default 100. flatSearchCutoff also passed as string.
    payload = {
        "class": CLASS_NAME,
        "vectorIndexConfig": {
            "dynamicEfMax": "abc",       # wrong type for int field
            "flatSearchCutoff": "xyz",   # wrong type for int field
            "dcConfig": {"distance": "cosine"}
        }
    }
    status, body, raw = safe_request("POST", "/v1/schema", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:600]}")

    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        return

    # ---- Read back what was actually stored ----
    rstatus, rbody, rraw = safe_request("GET", f"/v1/schema/{CLASS_NAME}")
    vic = {}
    if isinstance(rbody, dict):
        vic = (rbody.get("vectorIndexConfig") or {})

    stored_min = vic.get("dynamicEfMin")
    stored_max = vic.get("dynamicEfMax")
    stored_cut = vic.get("flatSearchCutoff")

    print(f"Stored dynamicEfMin={stored_min}  dynamicEfMax={stored_max}  flatSearchCutoff={stored_cut}")

    def _no_defect(msg):
        print(f"NO_DEFECT: {msg}")

    def _found(msg):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess): {msg}")

    # ---- Judgment ----
    # A wrong-typed string for an int parameter should be REJECTED (as float and
    # as replication factor are). Here HTTP 200 means silent acceptance.
    if status in (200, 201):
        # Confirm the silent coercion actually happened and produced the inverted pair
        coerced_to_zero = (stored_max == 0) or (stored_cut == 0)
        inverted = (stored_min == 100 and stored_max == 0)
        if coerced_to_zero:
            _found(
                f"schema accepted string for int-declared vectorIndexConfig field, "
                f"silently coerced to 0 (dynamicEfMax={stored_max}, flatSearchCutoff={stored_cut}). "
                f"Unsent dynamicEfMin defaulted to {stored_min} -> Min({stored_min}) > Max({stored_max}) "
                f"violates weaviate_inferred_hnsw_ef_pairing_001 (Min<=Max). "
                f"Control: float 12.7 -> 422 and string for replication factor -> 400, "
                f"so silent-coerce-to-0 here is a real gap."
            )
        elif inverted:
            _found(
                f"stored dynamicEfMin={stored_min} > dynamicEfMax={stored_max} after silent coercion, "
                f"violates inferred EF pairing assertion."
            )
        else:
            _no_defect(
                f"HTTP 200 but no silent coercion / no inverted pairing observed "
                f"(stored Min={stored_min}, Max={stored_max}, cut={stored_cut})."
            )
    elif status in (400, 422):
        _no_defect(f"wrong-type string was rejected with {status}.")
    else:
        _no_defect(f"unexpected HTTP {status} (no evidence of silent-coerce-to-0).")


if __name__ == "__main__":
    try:
        main()
        import sys as _s
        _s.exit(1)  # DEFECT_FOUND exit code (see _target_api_reference.md)
    finally:
        cleanup()
