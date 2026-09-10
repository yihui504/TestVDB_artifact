#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: special_value (strategy 4 on a behavioral contract) — Cosine collections normalize
        vectors during upload (by-design per doc). Novel boundary probe of the normalization
        itself at magnitude extremes, since no R2 script touched normalization:
        (a) legal magnitudes (norm 5 / norm 50) must be stored with unit norm (~1.0);
        (b) zero vector [0,0,0,0] — norm 0 makes normalization a division by zero; expect a
            clean 4xx rejection. Defect signals: 5xx/panic, or silent accept followed by
            NaN scores / missing results in search;
        (c) subnormal-magnitude vector (1e-40 components, f32 subnormal territory) —
            underflow probe, logged for judge.
Constraint: qdrant_behavioral_collections_create_003 (Cosine => stored vectors normalized
            during upload, by-design)
Endpoint: PUT /collections/{collection_name} (collections+create) + points+upsert/get/search
exploration_target: novel_candidate
Block: chunk_collections+create-2of2
source_url: https://qdrant.tech/documentation/concepts/collections/
doc_version: 1.18.x (versioned)
# Blindspot: BS-04 Boundary Default Optimism
"""

import math
import requests
import json
import sys
import os

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
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
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


def cleanup(cname):
    try:
        safe_request("DELETE", f"/collections/{cname}")
    except Exception:
        pass


def main():
    cname = "bnd_c2of2_cosnorm"
    cleanup(cname)
    defect = False

    # Arrange: Cosine collection.
    s, b, raw = safe_request("PUT", f"/collections/{cname}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"CREATE Cosine: status={s} body={raw[:200]}")
    if s == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        sys.exit(2)
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — baseline create rejected: {raw[:200]}")
        sys.exit(2)

    # Act 1: legal magnitudes, wait=true.
    legal = [
        {"id": 1, "vector": [3.0, 4.0, 0.0, 0.0]},      # norm 5
        {"id": 2, "vector": [30.0, 40.0, 0.0, 0.0]},    # norm 50
        {"id": 3, "vector": [1e-8, 1e-8, 1e-8, 1e-8]},  # tiny but f32-normal
    ]
    s1, b1, raw1 = safe_request("PUT", f"/collections/{cname}/points?wait=true",
                                json={"points": legal})
    print(f"UPSERT legal magnitudes: status={s1} body={raw1[:200]}")
    if s1 == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        cleanup(cname)
        sys.exit(2)
    if s1 not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — legal upsert rejected: {raw1[:200]}")
        cleanup(cname)
        sys.exit(2)

    # Assert: stored vectors must have unit norm.
    s2, b2, raw2 = safe_request("POST", f"/collections/{cname}/points/get",
                                json={"ids": [1, 2, 3], "with_vector": True,
                                      "with_payload": False})
    print(f"GET with_vector: status={s2} body={raw2[:500]}")
    if s2 == 200 and isinstance(b2, dict):
        pts = {p.get("id"): p.get("vector") for p in (b2.get("result") or [])}
        for pid in (1, 2, 3):
            vec = pts.get(pid)
            if not isinstance(vec, list) or len(vec) != 4:
                print(f"NOTE — point {pid} vector not readable as list: {vec}")
                continue
            norm = math.sqrt(sum(float(x) * float(x) for x in vec))
            print(f"NORM id={pid}: {norm}")
            if any(math.isnan(float(x)) for x in vec) or math.isnan(norm):
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — stored vector id={pid} "
                      "contains NaN after Cosine normalization")
                defect = True
            elif abs(norm - 1.0) > 1e-3:
                print(f"VERDICT: DEFECT_FOUND (Type1_ContractDivergence) — stored vector "
                      f"id={pid} norm={norm} != 1.0 (doc: vectors normalized on upload)")
                defect = True

    # Act 2: zero vector — must be cleanly rejected (or safely handled).
    s3, b3, raw3 = safe_request("PUT", f"/collections/{cname}/points?wait=true",
                                json={"points": [{"id": 4, "vector": [0.0, 0.0, 0.0, 0.0]}]})
    print(f"UPSERT zero vector: status={s3} body={raw3[:300]}")
    if s3 == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        cleanup(cname)
        sys.exit(2)
    if s3 >= 500:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — zero-vector upsert triggered 5xx")
        defect = True
    elif s3 in (200, 201):
        # Accepted: search with the same zero vector must stay finite and not 5xx.
        s4, b4, raw4 = safe_request("POST", f"/collections/{cname}/points/search",
                                    json={"vector": [0.0, 0.0, 0.0, 0.0], "limit": 3,
                                          "with_payload": False})
        print(f"SEARCH zero vector: status={s4} body={raw4[:400]}")
        if s4 == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            cleanup(cname)
            sys.exit(2)
        if s4 >= 500:
            print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — zero-vector search "
                  f"triggered {s4}")
            defect = True
        elif s4 == 200 and "nan" in raw4.lower():
            print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — zero-vector search "
                  "returned NaN scores")
            defect = True
        else:
            print("NOTE — zero vector accepted with 200 (judge: doc does not declare "
                  "zero-vector policy; scores observed above)")

    # Act 3: subnormal magnitude probe (f32 underflow territory), logged for judge.
    s5, b5, raw5 = safe_request("PUT", f"/collections/{cname}/points?wait=true",
                                json={"points": [{"id": 5,
                                                  "vector": [1e-40, 1e-40, 1e-40, 1e-40]}]})
    print(f"UPSERT subnormal 1e-40: status={s5} body={raw5[:300]}")
    if s5 >= 500:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — subnormal upsert triggered 5xx")
        defect = True

    cleanup(cname)
    if defect:
        return
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
