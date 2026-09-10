#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: type boundary (strategy 2) — invalid vectors config variants NOT covered by R2:
        R2 (boundary_01/semantic_003/semantic_004) covered the unnamed-form enum/size
        confusion (distance=Bogus, size types, vectors null/{}/missing). Novel here:
        (a) invalid enum INSIDE a named-vectors map (nested oneOf path);
        (b) partial configs (missing distance only / missing size only);
        (c) top-level scalar/array vectors values.
        Expected per contract: HTTP 400 "Format error in JSON body: data did not match any
        variant of untagged enum VectorsConfig"; Type2 rubric checks the error names the
        offending construct.
Constraint: qdrant_behavioral_collections_create_001 (invalid vectors config => 400
            with JSON format error naming VectorsConfig)
Endpoint: PUT /collections/{collection_name} (contract path: collections+create)
exploration_target: novel_candidate
Block: chunk_collections+create-2of2
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned)
# Blindspot: BS-01 Parameter Type Coercion Trust
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


def main():
    cases = [
        # (label, body, expected-reject, Type2 hint tokens)
        ("named map img.distance=Bogus (nested enum)",
         {"vectors": {"img": {"size": 4, "distance": "Bogus"}}}, True, ["vectors", "distance"]),
        ("named map img missing distance",
         {"vectors": {"img": {"size": 4}}}, True, ["vectors", "distance"]),
        ("named map img missing size",
         {"vectors": {"img": {"distance": "Cosine"}}}, True, ["vectors", "size"]),
        ("unnamed missing distance",
         {"vectors": {"size": 4}}, True, ["vectors", "distance"]),
        ("unnamed missing size",
         {"vectors": {"distance": "Cosine"}}, True, ["vectors", "size"]),
        ("vectors=4 scalar",
         {"vectors": 4}, True, ["vectors"]),
        ("vectors=[] empty array",
         {"vectors": []}, True, ["vectors"]),
        ("vectors=[{size,distance}] array-of-params",
         {"vectors": [{"size": 4, "distance": "Cosine"}]}, True, ["vectors"]),
    ]
    defect = False
    type2_notes = 0
    counter = 0
    for label, body, should_reject, hints in cases:
        counter += 1
        cname = f"bnd_c2of2_vec_{counter}"
        try:
            safe_request("DELETE", f"/collections/{cname}")
        except Exception:
            pass
        s, b, raw = safe_request("PUT", f"/collections/{cname}", json=body)
        print(f"CASE {label}: status={s} body={raw[:300]}")
        if s == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            sys.exit(2)
        if should_reject:
            if s in (200, 201):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label} accepted with {s}")
                defect = True
                # 200 on an invalid config must not leave a live collection behind
                try:
                    safe_request("DELETE", f"/collections/{cname}")
                except Exception:
                    pass
                continue
            if s >= 500:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label} triggered {s}")
                defect = True
                continue
            # Type2: error should name 'vectors' and ideally the inner field.
            low = raw.lower()
            score = sum(1 for h in hints if h in low)
            if score == 0:
                print(f"NOTE Type2 — {label} rejected with {s} but error names neither "
                      f"{hints}: {raw[:200]}")
                type2_notes += 1
        try:
            safe_request("DELETE", f"/collections/{cname}")
        except Exception:
            pass

    if defect:
        return
    if type2_notes >= 3:
        print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — {type2_notes} rejection "
              "messages name neither 'vectors' nor the offending inner field")
        return
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
