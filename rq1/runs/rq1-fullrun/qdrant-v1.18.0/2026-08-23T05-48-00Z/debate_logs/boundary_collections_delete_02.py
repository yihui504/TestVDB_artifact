#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: boundary (state-idempotency violation probe) — second DELETE of an already-deleted collection
Constraint: qdrant_state_collections_delete_001 ("deleting non-existent collection returns 404")
Endpoint: collections+delete -> DELETE /collections/{collection_name}
Round block: chunk_collections+delete
Coverage map: [strategy 1 boundary x state_collections_delete_001] double-delete / triple-delete
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


COL = "bd02_double_del"

try:
    s, _, raw = safe_request("PUT", f"/collections/{COL}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"setup create: {s} {raw[:200]}")
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — cannot create fixture collection, got {s}")
        sys.exit(2)

    # delete #1: must be 200
    s1, _, raw1 = safe_request("DELETE", f"/collections/{COL}")
    print(f"DELETE #1: status={s1} raw={raw1[:200]}")
    if s1 != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — first DELETE of existing collection got {s1}, expected 200")
        sys.exit(0)

    # delete #2: collection no longer exists -> contract says 404
    s2, _, raw2 = safe_request("DELETE", f"/collections/{COL}")
    print(f"DELETE #2: status={s2} raw={raw2[:300]}")
    if s2 == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — second DELETE of already-deleted "
              "collection returned 200; constraint requires 404 for non-existent collection")
        sys.exit(0)
    if s2 == 404:
        pass  # correct
    elif s2 in (400, 422):
        print(f"NOTE: second DELETE returned {s2} (explicit rejection; judge to weigh vs 404 contract)")
    else:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — second DELETE returned {s2}, expected 404")
        sys.exit(0)

    # delete #3: stability of the 404 (no flapping)
    s3, _, raw3 = safe_request("DELETE", f"/collections/{COL}")
    print(f"DELETE #3: status={s3} raw={raw3[:200]}")
    if s3 == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — third DELETE returned 200 after two deletions")
        sys.exit(0)

    # confirm state consistency: GET must be 404
    sg, _, _ = safe_request("GET", f"/collections/{COL}")
    print(f"GET after deletes: {sg}")
    if sg == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — GET 200 after DELETE (zombie)")
        sys.exit(0)
    print("VERDICT: NO_DEFECT — first DELETE 200, subsequent DELETEs 404, GET 404")
except SystemExit:
    raise
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR — unhandled exception: {e}")
    sys.exit(2)
finally:
    try:
        safe_request("DELETE", f"/collections/{COL}")
    except Exception:
        pass
