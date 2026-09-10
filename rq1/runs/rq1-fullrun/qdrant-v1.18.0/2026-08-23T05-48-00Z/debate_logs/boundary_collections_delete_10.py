#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: zombie-operation surface after delete — every data/schema op on deleted name must 404
Constraint: qdrant_bc_collection_delete_isolation_001 ("deleting a collection removes its points")
  + qdrant_state_collections_delete_001 (404 semantics)
Endpoint: collections+delete (witnesses: points+count/upsert/delete/query/scroll, index+create, point+get)
Round block: chunk_collections+delete
Coverage map: [zombie surface x bc_collection_delete_isolation_001] post-delete op sweep
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


C = "bd10_zombie"

try:
    s, _, raw = safe_request("PUT", f"/collections/{C}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"create: {s}")
    if s not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — fixture create failed")
        sys.exit(2)
    s, _, raw = safe_request("PUT", f"/collections/{C}/points?wait=true",
                             json={"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]},
                                              {"id": 2, "vector": [0.4, 0.3, 0.2, 0.1]}]})
    print(f"upsert: {s}")
    if s != 200:
        print("VERDICT: SCRIPT_ERROR — fixture upsert failed")
        sys.exit(2)

    s, _, raw = safe_request("DELETE", f"/collections/{C}")
    print(f"DELETE: {s} raw={raw[:150]}")
    if s != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — DELETE returned {s}")
        sys.exit(0)

    ops = [
        ("points+count",   "POST", f"/collections/{C}/points/count", {"exact": True}),
        ("points+upsert",  "PUT",  f"/collections/{C}/points?wait=true",
         {"points": [{"id": 9, "vector": [0.1, 0.1, 0.1, 0.1]}]}),
        ("points+delete",  "POST", f"/collections/{C}/points/delete?wait=true", {"points": [1]}),
        ("points+query",   "POST", f"/collections/{C}/points/query",
         {"query": {"nearest": [0.1, 0.2, 0.3, 0.4]}, "limit": 1}),
        ("points+scroll",  "POST", f"/collections/{C}/points/scroll", {"limit": 10}),
        ("point+get",      "GET",  f"/collections/{C}/points/1", None),
        ("index+create",   "PUT",  f"/collections/{C}/index?wait=true",
         {"field_name": "f", "field_schema": "keyword"}),
    ]

    defects = []
    for label, method, path, payload in ops:
        if payload is None:
            s, _, raw = safe_request(method, path)
        else:
            s, _, raw = safe_request(method, path, json=payload)
        print(f"[{label}] -> {s} raw={raw[:180].replace(chr(10), ' ')}")
        if s == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed during zombie sweep")
            sys.exit(2)
        if s == 200:
            defects.append(f"Type1_IllegalSuccess: {label} returned 200 on deleted collection")
        elif s >= 500:
            defects.append(f"Type3_RuntimeFailure: {label} returned {s} on deleted collection")
        elif s != 404:
            print(f"NOTE: {label} returned {s} (404 expected per contract; judge to weigh)")

    if defects:
        print("VERDICT: DEFECT_FOUND — " + " | ".join(defects))
    else:
        print("VERDICT: NO_DEFECT — all operations on deleted collection return 404 (no zombies)")
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
