#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: state isolation (lifecycle boundary) — recreate same name after delete must start EMPTY
Constraint: qdrant_bc_collection_delete_isolation_001 ("deleting a collection removes its points")
Endpoint: collections+delete -> DELETE /collections/{collection_name} (+ create/get/count/scroll)
Round block: chunk_collections+delete
Coverage map: [state resurrection probe x bc_collection_delete_isolation_001] recreate-same-name
Unit: behavioral_contracts::qdrant_bc_collection_delete_isolation_001
Rationale: if old points survive recreate (WAL/segment resurrection), "deleting a collection
removes its points" is violated even though both DELETE and CREATE returned 200.
"""

import requests, json, sys, os, time

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


C = "bd08_recreate"

def create_col():
    return safe_request("PUT", f"/collections/{C}",
                        json={"vectors": {"size": 4, "distance": "Cosine"}})

def exact_count():
    s, b, raw = safe_request("POST", f"/collections/{C}/points/count", json={"exact": True})
    if s == 200 and isinstance(b, dict):
        r = b.get("result")
        if isinstance(r, dict) and "count" in r:
            return r["count"]
    return None

try:
    # lifecycle 1: create + 4 points
    s, _, raw = create_col()
    print(f"create#1: {s}")
    if s not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — initial create failed")
        sys.exit(2)
    pts = [{"id": i, "vector": [0.1 * i, 0.2, 0.3, 0.4], "payload": {"gen": 1}} for i in (1, 2, 3, 4)]
    s, _, raw = safe_request("PUT", f"/collections/{C}/points?wait=true", json={"points": pts})
    print(f"upsert gen1: {s}")
    c1 = exact_count()
    print(f"count#1 = {c1}")
    if c1 != 4:
        print("VERDICT: SCRIPT_ERROR — fixture count unexpected")
        sys.exit(2)

    # lifecycle 2: delete (must be 200 + gone)
    s, _, raw = safe_request("DELETE", f"/collections/{C}")
    print(f"delete: {s} raw={raw[:150]}")
    if s != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — DELETE returned {s}, expected 200")
        sys.exit(0)
    sg, _, _ = safe_request("GET", f"/collections/{C}")
    if sg != 404:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — GET after DELETE = {sg}, expected 404")
        sys.exit(0)

    # lifecycle 3: recreate SAME name immediately
    s, _, raw = create_col()
    print(f"create#2 (same name): {s} raw={raw[:200]}")
    if s not in (200, 201):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — recreate after delete returned "
              f"{s}; name should be reusable per lifecycle")
        sys.exit(0)

    # allow async cleanup to settle before judging (no zombie segments)
    time.sleep(3)

    c2 = exact_count()
    print(f"count#2 (after recreate) = {c2} (expected 0)")

    # old-id visibility probes
    sp, _, rawp = safe_request("GET", f"/collections/{C}/points/1")
    print(f"GET old point 1 after recreate: {sp} raw={rawp[:200]}")
    ss, b, raws = safe_request("POST", f"/collections/{C}/points/scroll",
                               json={"limit": 10, "with_payload": True})
    n_scroll = 0
    if ss == 200 and isinstance(b, dict):
        n_scroll = len(b.get("result", {}).get("points", []) or [])
    print(f"scroll after recreate: status={ss} points={n_scroll}")

    defects = []
    if c2 is not None and c2 > 0:
        defects.append(f"Type4_StateLogicViolation: recreated collection count={c2}, "
                       f"old points resurrected (expected 0)")
    if sp == 200:
        defects.append("Type4_StateLogicViolation: old point id readable after recreate "
                       "(point get 200, expected 404)")
    if ss == 200 and n_scroll > 0:
        defects.append(f"Type4_StateLogicViolation: scroll returned {n_scroll} resurrected points")

    if defects:
        print("VERDICT: DEFECT_FOUND — " + " | ".join(defects))
    elif c2 is None:
        print("VERDICT: SCRIPT_ERROR — count unreadable after recreate")
        sys.exit(2)
    else:
        print("VERDICT: NO_DEFECT — recreated collection starts empty; no resurrection")
except SystemExit:
    raise
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR — unhandled exception: {e}")
    sys.exit(2)
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
