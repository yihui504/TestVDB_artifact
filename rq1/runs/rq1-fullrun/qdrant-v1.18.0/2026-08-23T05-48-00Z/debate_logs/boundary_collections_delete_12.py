#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: boundary (name-matching precision) — case/lookalike names must not delete the real one
Constraint: qdrant_state_collections_delete_001 ("deleting non-existent collection returns 404")
Endpoint: collections+delete -> DELETE /collections/{collection_name}
Round block: chunk_collections+delete
Coverage map: [strategy 1 boundary x state_collections_delete_001] case-sensitivity + lookalike names
Unit: constraints::qdrant_state_collections_delete_001
Rationale: if DELETE of a lookalike (different-case, trailing-space, prefixed) name returns 200
and/or removes the real collection, exact-name matching is broken (over-deletion).
"""

import requests, json, sys, os

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
    req_timeout = kwargs.pop("req_timeout", 60)
    try:
        resp = requests.request(method, url, headers=headers, timeout=req_timeout, **kwargs)
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


REAL = "bd12_Case_A"
LOOKALIKES = [
    ("lower", "/collections/bd12_case_a"),
    ("upper", "/collections/BD12_CASE_A"),
    ("trailing-space", "/collections/bd12_Case_A%20"),
    ("leading-space", "/collections/%20bd12_Case_A"),
    ("prefix", "/collections/xbd12_Case_A"),
]

try:
    s, _, raw = safe_request("PUT", f"/collections/{REAL}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"create {REAL}: {s}")
    if s not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — fixture create failed")
        sys.exit(2)

    defects = []
    for label, path in LOOKALIKES:
        s, _, raw = safe_request("DELETE", path)
        print(f"[{label}] DELETE {path} -> {s} raw={raw[:200].replace(chr(10), ' ')}")
        if s == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            sys.exit(2)
        # the REAL collection must still exist regardless of response
        sg, _, _ = safe_request("GET", f"/collections/{REAL}")
        print(f"[{label}] real collection GET after lookalike delete: {sg}")
        if s == 200:
            defects.append(f"[{label}] Type1_IllegalSuccess: lookalike name returned 200 "
                           f"(non-existent collection must 404)")
        if sg != 200:
            defects.append(f"[{label}] Type4_StateLogicViolation: lookalike DELETE removed the "
                           f"REAL collection (over-deletion)")

    if defects:
        print("VERDICT: DEFECT_FOUND — " + " | ".join(defects))
    else:
        print("VERDICT: NO_DEFECT — lookalike names rejected; exact-name matching holds")
except SystemExit:
    raise
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR — unhandled exception: {e}")
    sys.exit(2)
finally:
    try:
        safe_request("DELETE", f"/collections/{REAL}")
    except Exception:
        pass
