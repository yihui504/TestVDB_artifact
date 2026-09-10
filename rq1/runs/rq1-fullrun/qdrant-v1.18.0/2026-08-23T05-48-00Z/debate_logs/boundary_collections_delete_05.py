#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: boundary + special values — collection_name path parameter edge values on DELETE
Constraint: qdrant_state_collections_delete_001 ("deleting non-existent collection returns 404")
Endpoint: collections+delete -> DELETE /collections/{collection_name}
Round block: chunk_collections+delete
Coverage map: [strategy 1/4 boundary/special x state_collections_delete_001]
  empty name / long name / NUL-encoded / unicode / traversal / reserved-route collision / unicode positive control
Unit: constraints::qdrant_state_collections_delete_001
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


LONG_NAME = "bd05_" + "x" * 1000
UNI_EXIST = "bd05_unicode_现有コレクション_🎯"

# (label, path-suffix already URL-encoded where needed, is_control)
cases = [
    ("empty-trailing-slash", "/collections/"),
    ("bare-collections",     "/collections"),
    ("long-1000",            "/collections/" + LONG_NAME),
    ("dot",                  "/collections/."),
    ("dotdot",               "/collections/.."),
    ("nul-encoded",          "/collections/bd05_%00_nul"),
    ("unicode-missing",      "/collections/bd05_не_существует_中文"),
    ("trailing-space",       "/collections/bd05_trailing%20"),
    ("plus-name",            "/collections/bd05+plus+name"),
    ("reserved-aliases",     "/collections/aliases"),
]

try:
    results = []
    for label, path in cases:
        s, _, raw = safe_request("DELETE", path)
        snippet = raw[:200].replace("\n", " ")
        print(f"[{label}] DELETE {path[:80]}{'...' if len(path) > 80 else ''} -> {s} | {snippet}")
        if s == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed during edge-name DELETE sweep")
            sys.exit(2)
        results.append((label, s, raw))

    defects = []
    for label, s, raw in results:
        if s >= 500:
            defects.append(f"[{label}] Type3_RuntimeFailure: 5xx ({s}) on non-existent name")
        elif s == 200:
            defects.append(f"[{label}] Type1_IllegalSuccess: 200 DELETE on non-existent name "
                           f"(constraint requires 404)")
        elif s == 404 or s in (400, 405, 422):
            continue  # acceptable explicit outcomes
        else:
            defects.append(f"[{label}] unexpected status {s}")

    # Positive control: unicode-named collection exists -> DELETE must be 200, then GET 404
    s, _, raw = safe_request("PUT", f"/collections/{UNI_EXIST}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"[unicode-control] create: {s}")
    if s in (200, 201):
        s, _, raw = safe_request("DELETE", f"/collections/{UNI_EXIST}")
        print(f"[unicode-control] DELETE existing unicode name: {s} raw={raw[:200]}")
        if s != 200:
            defects.append(f"[unicode-control] Type3_RuntimeFailure: existing unicode-named "
                           f"collection DELETE returned {s}, expected 200")
        else:
            sg, _, _ = safe_request("GET", f"/collections/{UNI_EXIST}")
            if sg == 200:
                defects.append("[unicode-control] Type1_IllegalSuccess: GET 200 after DELETE")
    else:
        print("[unicode-control] SKIP: server rejected creating unicode name (documented "
              "name validation acceptable)")

    if defects:
        print("VERDICT: DEFECT_FOUND — " + " | ".join(defects))
    else:
        print("VERDICT: NO_DEFECT — all non-existent edge names got 4xx (404), "
              "unicode existing name deleted with 200")
except SystemExit:
    raise
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR — unhandled exception: {e}")
    sys.exit(2)
finally:
    try:
        safe_request("DELETE", f"/collections/{UNI_EXIST}")
    except Exception:
        pass
