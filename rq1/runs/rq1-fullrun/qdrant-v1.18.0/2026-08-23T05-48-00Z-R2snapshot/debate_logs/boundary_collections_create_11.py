#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: boundary_value (strategy 1) — hnsw_config.full_scan_threshold diff arm
        (HnswConfigDiff via collections+update PATCH must enforce >= 10) +
        create-side min persistence read-back. R2 covered create-side -1/0/-10 only.
        NOTE: R2 observed create-time value 0 rejected with "must be 10 or larger" while the
        contract asserts create >= 0 / diff >= 10 — the PATCH arm is where the two variants
        are allowed to diverge, so the 9/10 boundary on PATCH is the novel probe.
Constraint: qdrant_range_collections_create_003 (full_scan_threshold >= 0 create / >= 10 diff)
Endpoint: PUT /collections/{collection_name} (collections+create)
          + PATCH /collections/{collection_name} (collections+update, diff arm)
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


def describe_fst(cname):
    s, b, raw = safe_request("GET", f"/collections/{cname}")
    if s != 200 or not isinstance(b, dict):
        return None, raw
    cfg = (b.get("result") or {}).get("config") or {}
    hnsw = cfg.get("hnsw_config") or {}
    return hnsw.get("full_scan_threshold"), raw


def describe_with_retry(cname, reader, expected, tries=3, delay=1.0):
    """Read back a config value; retry briefly to avoid async-apply races.
    Returns (value, saw_expected)."""
    import time as _t
    value = None
    for _ in range(tries):
        value = reader(cname)
        if value == expected:
            return value, True
        _t.sleep(delay)
    return value, False


def main():
    cname = "bnd_c2of2_fst_patch"
    defect = False

    # Arrange: create with explicit legal value, then drive PATCH diff boundary.
    s, b, raw = safe_request("PUT", f"/collections/{cname}",
                             json={"vectors": {"size": 4, "distance": "Cosine"},
                                   "hnsw_config": {"full_scan_threshold": 10000}})
    print(f"CREATE full_scan_threshold=10000: status={s} body={raw[:200]}")
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

    cases = [
        ("PATCH full_scan_threshold=9 (diff min-1)", {"hnsw_config": {"full_scan_threshold": 9}}, True),
        ("PATCH full_scan_threshold=10 (diff min)", {"hnsw_config": {"full_scan_threshold": 10}}, False),
        ("PATCH full_scan_threshold=0", {"hnsw_config": {"full_scan_threshold": 0}}, True),
        ("PATCH full_scan_threshold=-1", {"hnsw_config": {"full_scan_threshold": -1}}, True),
    ]
    for name, payload, should_reject in cases:
        s, b, raw = safe_request("PATCH", f"/collections/{cname}", json=payload)
        print(f"CASE {name}: status={s} body={raw[:300]}")
        if s == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            try:
                safe_request("DELETE", f"/collections/{cname}")
            except Exception:
                pass
            sys.exit(2)
        if should_reject and s in (200, 201):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {name} accepted with {s}")
            defect = True
        if not should_reject and s in (200, 201):
            persisted, saw = describe_with_retry(
                cname, lambda n: describe_fst(n)[0], 10)
            print(f"  PERSISTED full_scan_threshold={persisted} saw_expected={saw}")
            if not saw:
                print("VERDICT: DEFECT_FOUND (Type1_PersistMismatch) — PATCH "
                      f"full_scan_threshold=10 returned 200 but describe shows {persisted}")
                defect = True
        elif not should_reject:
            print(f"NOTE — diff-min full_scan_threshold=10 rejected on PATCH with {s}")

    # Create-side persistence at the observed effective minimum (10).
    cname2 = "bnd_c2of2_fst_min"
    s2, b2, raw2 = safe_request("PUT", f"/collections/{cname2}",
                                json={"vectors": {"size": 4, "distance": "Cosine"},
                                      "hnsw_config": {"full_scan_threshold": 10}})
    print(f"CREATE full_scan_threshold=10: status={s2} body={raw2[:200]}")
    if s2 in (200, 201):
        persisted2, saw2 = describe_with_retry(
            cname2, lambda n: describe_fst(n)[0], 10)
        print(f"  PERSISTED full_scan_threshold={persisted2} saw_expected={saw2}")
        if not saw2:
            print("VERDICT: DEFECT_FOUND (Type1_PersistMismatch) — create "
                  f"full_scan_threshold=10 accepted but describe shows {persisted2}")
            defect = True
    elif s2 in (400, 422):
        print("NOTE — create full_scan_threshold=10 rejected "
              "(contract asserts create-side minimum 0; over-strict if so): " + raw2[:200])

    # Cleanup
    for c in (cname, cname2):
        try:
            safe_request("DELETE", f"/collections/{c}")
        except Exception:
            pass

    if defect:
        return
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
