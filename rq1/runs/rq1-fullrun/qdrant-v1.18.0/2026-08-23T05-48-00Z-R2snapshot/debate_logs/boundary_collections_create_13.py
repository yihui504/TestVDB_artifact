#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: state boundary (strategy 1 applied to a state constraint) — duplicate collection
        create must fail with 4xx conflict. Novel vs R2: the state agent's sequential run
        (state_collections_create_001) died with SCRIPT_ERROR and its concurrent twin
        (state_002) hit an all-connection-dead window, so the sequential duplicate behavior
        was never actually observed. This script additionally probes the stricter variant:
        duplicate create with a DIFFERENT config (size/distance) — a 200 there must at least
        leave the original config untouched (mutation = state corruption).
Constraint: qdrant_state_collections_create_001 (PUT existing collection_name => 4xx conflict)
Endpoint: PUT /collections/{collection_name} (contract path: collections+create)
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


def read_config(cname):
    s, b, raw = safe_request("GET", f"/collections/{cname}")
    if s != 200 or not isinstance(b, dict):
        return None, raw
    cfg = ((b.get("result") or {}).get("config") or {})
    vectors = (cfg.get("params") or {}).get("vectors")
    return vectors, raw


def main():
    cname = "bnd_c2of2_dup"
    defect = False

    # Arrange: baseline create (idempotent pre-clean first).
    try:
        safe_request("DELETE", f"/collections/{cname}")
    except Exception:
        pass
    s, b, raw = safe_request("PUT", f"/collections/{cname}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"CREATE baseline: status={s} body={raw[:200]}")
    if s == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        sys.exit(2)
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — baseline create rejected: {raw[:200]}")
        try:
            safe_request("DELETE", f"/collections/{cname}")
        except Exception:
            pass
        sys.exit(2)

    # Act 1: exact duplicate create (same body).
    s1, b1, raw1 = safe_request("PUT", f"/collections/{cname}",
                                json={"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"CASE duplicate create (same config): status={s1} body={raw1[:300]}")
    if s1 == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        try:
            safe_request("DELETE", f"/collections/{cname}")
        except Exception:
            pass
        sys.exit(2)
    if s1 in (200, 201):
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — duplicate create of existing "
              f"collection accepted with {s1} (contract: 4xx conflict)")
        defect = True
    elif s1 not in (400, 409, 422):
        print(f"NOTE — duplicate create returned unexpected status {s1}")

    # Act 2: duplicate create with DIFFERENT config.
    s2, b2, raw2 = safe_request("PUT", f"/collections/{cname}",
                                json={"vectors": {"size": 8, "distance": "Euclid"}})
    print(f"CASE duplicate create (different config size=8 Euclid): status={s2} body={raw2[:300]}")
    if s2 in (200, 201):
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — duplicate create with different "
              f"config accepted with {s2} (contract: 4xx conflict)")
        defect = True

    # Assert: original config must be intact regardless of duplicate-create outcomes.
    vectors, draw = read_config(cname)
    print(f"DESCRIBE vectors after duplicates: {vectors}")
    if isinstance(vectors, dict):
        size_ok = vectors.get("size") == 4
        dist_ok = vectors.get("distance") == "Cosine"
        if not (size_ok and dist_ok):
            print("VERDICT: DEFECT_FOUND (Type3_StateCorruption) — original config mutated by "
                  f"duplicate create: {vectors}")
            defect = True

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{cname}")
    except Exception:
        pass

    if defect:
        return
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
