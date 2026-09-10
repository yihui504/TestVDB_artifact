#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: boundary_value (strategy 1) — hnsw_config.ef_construct >= 4 on the HnswConfigDiff
        update path (collections+update PATCH) + min-value persistence read-back.
        R2 (boundary_collections_create_05) covered the create-side values 3/4/0/-1 only;
        the PATCH diff arm and the persistence read-back of the spec-min value are novel.
Constraint: qdrant_range_collections_create_002 (hnsw_config.ef_construct >= 4)
Endpoint: PUT /collections/{collection_name} (contract path: collections+create)
          + PATCH /collections/{collection_name} (contract path: collections+update, diff arm)
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


BASE = {"vectors": {"size": 4, "distance": "Cosine"},
        "hnsw_config": {"ef_construct": 16}}


def describe_ef_construct(cname):
    """Read back persisted ef_construct from GET /collections/{name}."""
    s, b, raw = safe_request("GET", f"/collections/{cname}")
    if s != 200 or not isinstance(b, dict):
        return None, raw
    cfg = (b.get("result") or {}).get("config") or {}
    hnsw = cfg.get("hnsw_config") or {}
    return hnsw.get("ef_construct"), raw


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
    cname = "bnd_c2of2_efc_patch"
    defect = False

    # Arrange: create with a legal ef_construct (16), then drive the diff arm.
    s, b, raw = safe_request("PUT", f"/collections/{cname}", json=BASE)
    print(f"CREATE ef_construct=16: status={s} body={raw[:200]}")
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

    # Act + Assert: PATCH diff-path boundary values.
    cases = [
        ("PATCH ef_construct=3 (below min 4)", {"hnsw_config": {"ef_construct": 3}}, True),
        ("PATCH ef_construct=4 (spec min)", {"hnsw_config": {"ef_construct": 4}}, False),
        ("PATCH ef_construct=0", {"hnsw_config": {"ef_construct": 0}}, True),
        ("PATCH ef_construct=4.5 float", {"hnsw_config": {"ef_construct": 4.5}}, True),
    ]
    for name, payload, should_reject in cases:
        s, b, raw = safe_request("PATCH", f"/collections/{cname}", json=payload)
        print(f"CASE {name}: status={s} body={raw[:300]}")
        if s == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            defect = None
            break
        if should_reject and s in (200, 201):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {name} accepted with {s}")
            defect = True
        if not should_reject and s in (200, 201):
            # Persistence check (with retry to rule out async config apply):
            # accepted spec-min must actually persist as 4.
            persisted, saw = describe_with_retry(
                cname, lambda n: describe_ef_construct(n)[0], 4)
            print(f"  PERSISTED ef_construct={persisted} saw_expected={saw}")
            if not saw:
                print("VERDICT: DEFECT_FOUND (Type1_PersistMismatch) — PATCH ef_construct=4 "
                      f"returned 200 but describe shows {persisted}")
                defect = True
        elif not should_reject:
            print(f"NOTE — spec-min ef_construct=4 rejected on PATCH with {s}")

    # Create-side min persistence (R2 printed describe but never asserted it).
    cname2 = "bnd_c2of2_efc_min"
    s2, b2, raw2 = safe_request("PUT", f"/collections/{cname2}",
                                json={"vectors": {"size": 4, "distance": "Cosine"},
                                      "hnsw_config": {"ef_construct": 4}})
    print(f"CREATE ef_construct=4: status={s2} body={raw2[:200]}")
    if s2 in (200, 201):
        persisted2, saw2 = describe_with_retry(
            cname2, lambda n: describe_ef_construct(n)[0], 4)
        print(f"  PERSISTED ef_construct={persisted2} saw_expected={saw2}")
        if not saw2:
            print("VERDICT: DEFECT_FOUND (Type1_PersistMismatch) — create ef_construct=4 "
                  f"accepted but describe shows {persisted2}")
            defect = True

    # Cleanup
    for c in (cname, cname2):
        try:
            safe_request("DELETE", f"/collections/{c}")
        except Exception:
            pass

    if defect is True:
        return
    if defect is None:
        return  # SCRIPT_ERROR already printed
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
