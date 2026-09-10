#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: boundary_value + schema-persist (strategy 1 + describe read-back, mode B' style) —
        strict_mode_config.max_resident_memory_percent IN [1,100]:
        (a) create-time accepted values must persist into the described collection config
            (R2 boundary_06 accepted 1/50/100 with 200 but never verified describe read-back —
            in 1.18 this field is deprecated in favour of node-wide quotas, so a silent drop
            of an accepted schema field is the novel probe);
        (b) PATCH collections+update diff arm must enforce the same [1,100] range (untested).
Constraint: qdrant_range_collections_create_004
Endpoint: PUT /collections/{collection_name} (collections+create)
          + PATCH /collections/{collection_name} (collections+update)
exploration_target: novel_candidate
Block: chunk_collections+create-2of2
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned)
# Blindspot: BS-04 Boundary Default Optimism
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
    cname = "bnd_c2of2_smc_persist"
    defect = False

    # Arrange: create with an in-range value (50) — R2 proved this is accepted with 200.
    s, b, raw = safe_request("PUT", f"/collections/{cname}",
                             json={"vectors": {"size": 4, "distance": "Cosine"},
                                   "strict_mode_config": {"enabled": True,
                                                          "max_resident_memory_percent": 50}})
    print(f"CREATE strict_mode max_resident_memory_percent=50: status={s} body={raw[:200]}")
    if s == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        sys.exit(2)
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — legal baseline create rejected: {raw[:200]}")
        try:
            safe_request("DELETE", f"/collections/{cname}")
        except Exception:
            pass
        sys.exit(2)

    # Assert (a): accepted schema value must be observable in describe (silent-drop probe).
    s2, b2, raw2 = safe_request("GET", f"/collections/{cname}")
    print(f"DESCRIBE: status={s2} body={raw2[:900]}")
    has_field = "max_resident_memory_percent" in raw2
    has_section = "strict_mode_config" in raw2
    print(f"PERSIST check: strict_mode_config present={has_section}, "
          f"max_resident_memory_percent present={has_field}")
    if not has_field:
        print("VERDICT: DEFECT_FOUND (Type1_SilentDrop) — create accepted "
              "strict_mode_config.max_resident_memory_percent=50 with 200 but the persisted "
              "collection config does not expose the field (silent drop; note: field is "
              "deprecated by node-wide quotas in 1.18 — judge to adjudicate deprecation "
              "vs silent-drop semantics)")
        defect = True

    # Assert (b): PATCH diff arm range enforcement.
    cases = [
        ("PATCH max_resident_memory_percent=101 (max+1)",
         {"strict_mode_config": {"enabled": True, "max_resident_memory_percent": 101}}, True),
        ("PATCH max_resident_memory_percent=0 (min-1)",
         {"strict_mode_config": {"enabled": True, "max_resident_memory_percent": 0}}, True),
        ("PATCH max_resident_memory_percent=100 (max)",
         {"strict_mode_config": {"enabled": True, "max_resident_memory_percent": 100}}, False),
    ]
    for name, payload, should_reject in cases:
        s3, b3, raw3 = safe_request("PATCH", f"/collections/{cname}", json=payload)
        print(f"CASE {name}: status={s3} body={raw3[:300]}")
        if s3 == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            defect = None
            break
        if should_reject and s3 in (200, 201):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {name} accepted with {s3}")
            defect = True
        if not should_reject and s3 in (200, 201) and has_field:
            s4, b4, raw4 = safe_request("GET", f"/collections/{cname}")
            if '"max_resident_memory_percent":100' not in raw4.replace(" ", ""):
                print("NOTE — PATCH 100 returned 200 but describe read-back mismatch: "
                      + raw4[:400])

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{cname}")
    except Exception:
        pass

    if defect is True:
        return
    if defect is None:
        return  # SCRIPT_ERROR already printed
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
