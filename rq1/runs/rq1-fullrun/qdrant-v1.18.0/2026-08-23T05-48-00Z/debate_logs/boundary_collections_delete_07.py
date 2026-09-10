#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: behavioral isolation regression — delete one collection must not touch the other
Constraint: qdrant_bc_collection_delete_isolation_001
  ("two collections with points; delete one" -> "deleted collection GET => 404; other count unchanged")
Endpoint: collections+delete (+ collections+get, points+count as witnesses)
Round block: chunk_collections+delete
Coverage map: [isolation regression x bc_collection_delete_isolation_001] core scenario
Unit: behavioral_contracts::qdrant_bc_collection_delete_isolation_001
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


A = "bd07_col_a"   # victim: 3 points
B = "bd07_col_b"   # survivor: 5 points


def create_with_points(name, ids):
    s, _, raw = safe_request("PUT", f"/collections/{name}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}})
    if s not in (200, 201):
        print(f"setup failed for {name}: {s} {raw[:200]}")
        return False
    pts = [{"id": i, "vector": [0.01 * i, 0.02 * i, 0.03 * i, 0.04 * i],
            "payload": {"col": name}} for i in ids]
    s, _, raw = safe_request("PUT", f"/collections/{name}/points?wait=true",
                             json={"points": pts})
    print(f"upsert {name}: {s}")
    return s == 200


def exact_count(name):
    s, b, raw = safe_request("POST", f"/collections/{name}/points/count",
                             json={"exact": True})
    if s == 200 and isinstance(b, dict):
        r = b.get("result")
        if isinstance(r, dict) and "count" in r:
            return s, r["count"]
    return s, None


try:
    if not create_with_points(A, [1, 2, 3]):
        print("VERDICT: SCRIPT_ERROR — fixture A setup failed")
        sys.exit(2)
    if not create_with_points(B, [1, 2, 3, 4, 5]):
        print("VERDICT: SCRIPT_ERROR — fixture B setup failed")
        sys.exit(2)

    sa, ca_before = exact_count(A)
    sb, cb_before = exact_count(B)
    print(f"pre-delete counts: A={ca_before} (status {sa}), B={cb_before} (status {sb})")
    if ca_before != 3 or cb_before != 5:
        print("VERDICT: SCRIPT_ERROR — fixture counts unexpected "
              f"(A={ca_before}, B={cb_before})")
        sys.exit(2)

    # Act: delete A
    s, _, raw = safe_request("DELETE", f"/collections/{A}")
    print(f"DELETE {A}: status={s} raw={raw[:200]}")
    if s != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — DELETE existing collection "
              f"returned {s}, expected 200")
        sys.exit(0)

    defects = []
    # Witness 1: A GET => 404
    sg, _, rawg = safe_request("GET", f"/collections/{A}")
    print(f"GET {A} after delete: {sg} raw={rawg[:200]}")
    if sg != 404:
        defects.append(f"Type1_IllegalSuccess: deleted collection GET returned {sg}, expected 404")

    # Witness 2: A count => 404
    sc, ca_after, rawc = exact_count(A)
    print(f"count {A} after delete: {sc} raw={rawc[:200]}")
    if sc != 404:
        defects.append(f"Type1_IllegalSuccess: count on deleted collection returned {sc}, expected 404")

    # Witness 3: B count unchanged (exact)
    sb2, cb_after = exact_count(B)
    print(f"count {B} after A delete: status={sb2} count={cb_after} (was {cb_before})")
    if sb2 != 200:
        defects.append(f"Type3_RuntimeFailure: survivor collection count returned {sb2}")
    elif cb_after != cb_before:
        defects.append(f"Type4_StateLogicViolation: survivor count changed "
                       f"{cb_before} -> {cb_after} after deleting the OTHER collection")

    # Witness 4: B point still readable
    sp, _, rawp = safe_request("GET", f"/collections/{B}/points/1")
    print(f"GET {B}/points/1: {sp}")
    if sp != 200:
        defects.append(f"Type3_RuntimeFailure: survivor point read returned {sp}, expected 200")

    if defects:
        print("VERDICT: DEFECT_FOUND — " + " | ".join(defects))
    else:
        print("VERDICT: NO_DEFECT — victim fully gone (404s), survivor count and points intact")
except SystemExit:
    raise
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR — unhandled exception: {e}")
    sys.exit(2)
finally:
    for c in (A, B):
        try:
            safe_request("DELETE", f"/collections/{c}")
        except Exception:
            pass
