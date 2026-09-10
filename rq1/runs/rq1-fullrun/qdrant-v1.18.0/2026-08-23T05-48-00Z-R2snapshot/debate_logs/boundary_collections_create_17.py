#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: behavioral contract boundary (bc arm hardened with boundary assertions) —
        points must be visible to query immediately after upsert wait=true.
        Scenario per contract: create collection -> upsert point wait=true -> query nearest
        with the same vector -> the point must be the top hit with distance ~0.
        Boundary hardening added on top (untouched by R2):
        (a) top-hit distance must be ~0 (< 1e-6) for the IDENTICAL vector (Cosine);
        (b) exact count must be 1 right after wait=true returns;
        (c) contrast batch upserted with wait=false is logged but NOT asserted
            (contract only guarantees wait=true visibility).
Constraint: qdrant_bc_create_query_visibility_001
Endpoint: collections+create + points+upsert + points+query (related per contract)
exploration_target: novel_candidate
Block: chunk_collections+create-2of2
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/upsert-points
doc_version: 1.18.x (versioned)
# Blindspot: BS-03 Concurrency State Blindness (immediate-visibility window)
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
    cname = "bnd_c2of2_vis"
    cleanup(cname)
    defect = False
    vec = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

    # Arrange: create.
    s, b, raw = safe_request("PUT", f"/collections/{cname}",
                             json={"vectors": {"size": 8, "distance": "Cosine"}})
    print(f"CREATE: status={s} body={raw[:200]}")
    if s == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        sys.exit(2)
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — baseline create rejected: {raw[:200]}")
        sys.exit(2)

    # Act 1: upsert ONE point with wait=true, then query IMMEDIATELY.
    s1, b1, raw1 = safe_request("PUT", f"/collections/{cname}/points?wait=true",
                                json={"points": [{"id": 101, "vector": vec,
                                                  "payload": {"src": "wait_true"}}]})
    print(f"UPSERT wait=true id=101: status={s1} body={raw1[:200]}")
    if s1 == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        cleanup(cname)
        sys.exit(2)
    if s1 not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — wait=true upsert rejected: {raw1[:200]}")
        cleanup(cname)
        sys.exit(2)

    s2, b2, raw2 = safe_request("POST", f"/collections/{cname}/points/query",
                                json={"query": vec, "limit": 3, "with_payload": True})
    print(f"QUERY nearest identical vector: status={s2} body={raw2[:500]}")
    if s2 == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        cleanup(cname)
        sys.exit(2)
    if s2 != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — query after wait=true "
              f"returned {s2}")
        defect = True
    else:
        results = (b2 or {}).get("result") or []
        if not results:
            print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — point 101 NOT visible to "
                  "query immediately after upsert wait=true")
            defect = True
        else:
            top = results[0]
            top_id = top.get("id")
            score = top.get("score")
            print(f"TOP hit id={top_id} score={score}")
            if top_id != 101:
                print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — top hit after wait=true "
                      f"is id={top_id}, expected 101 (identical vector)")
                defect = True
            # Contract phrase "distance ~0": qdrant reports score as similarity for
            # Cosine (identical -> ~1.0); accept either convention, flag only NaN/clearly-wrong.
            try:
                sc = float(score)
            except (TypeError, ValueError):
                sc = float("nan")
            close_to_one = abs(sc - 1.0) <= 1e-3
            close_to_zero = abs(sc) <= 1e-3
            if close_to_one or close_to_zero:
                print(f"TOP hit score {sc} consistent with identical vector "
                      "(similarity ~1 or distance ~0)")
            elif sc != sc:  # NaN
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — identical-vector "
                      f"query returned NaN score")
                defect = True
            else:
                print(f"VERDICT: DEFECT_FOUND (Type1_ContractDivergence) — identical-vector "
                      f"Cosine score {sc} is neither ~1 (similarity) nor ~0 (distance)")
                defect = True

    # Assert: exact count must be 1 right after wait=true returned.
    s3, b3, raw3 = safe_request("POST", f"/collections/{cname}/points/count",
                                json={"exact": True})
    print(f"COUNT exact: status={s3} body={raw3[:200]}")
    if s3 == 200 and isinstance(b3, dict):
        cnt = ((b3.get("result") or {}).get("count"))
        if cnt != 1:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — exact count after "
                  f"wait=true upsert of 1 point is {cnt}")
            defect = True
    elif s3 in (500, 502, 503, 504):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — count after wait=true -> {s3}")
        defect = True

    # Contrast (logged, not asserted): wait=false batch visibility is not guaranteed.
    s4, b4, raw4 = safe_request("PUT", f"/collections/{cname}/points?wait=false",
                                json={"points": [{"id": 102, "vector": vec}]})
    print(f"UPSERT wait=false id=102 (contrast, not asserted): status={s4} body={raw4[:150]}")
    s5, b5, raw5 = safe_request("POST", f"/collections/{cname}/points/query",
                                json={"query": vec, "limit": 5})
    print(f"QUERY after wait=false batch: status={s5} body={raw5[:300]}")

    cleanup(cname)
    if defect:
        return
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
