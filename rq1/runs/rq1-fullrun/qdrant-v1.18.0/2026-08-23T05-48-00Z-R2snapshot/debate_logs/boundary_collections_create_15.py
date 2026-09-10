#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: boundary_value + response-shape (strategy 1 + behavioral assertion) —
        (a) success response shape: create must return HTTP 200 with body keys
            {result, status="ok", time} (CollectionOperationResponse per contract);
        (b) timeout query parameter boundary: contract documents timeout as
            "query: min 1; seconds to wait" — timeout=0 / timeout=-1 / timeout=0.5
            must be rejected (4xx) while timeout=1 is legal. Untouched by R2.
Constraint: qdrant_behavioral_collections_create_002 (200 {result, status ok, time})
            + timeout param (min 1) from contract collections+create parameters
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


BODY = {"vectors": {"size": 4, "distance": "Cosine"}}


def main():
    defect = False

    # (a) success response shape on a minimal legal create.
    cname = "bnd_c2of2_shape_ok"
    try:
        safe_request("DELETE", f"/collections/{cname}")
    except Exception:
        pass
    s, b, raw = safe_request("PUT", f"/collections/{cname}", json=BODY)
    print(f"CREATE minimal legal: status={s} body={raw[:300]}")
    if s == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        sys.exit(2)
    if s in (200, 201):
        if not isinstance(b, dict):
            print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — 200 response is not JSON: "
                  + raw[:200])
            defect = True
        else:
            missing = [k for k in ("result", "status", "time") if k not in b]
            if missing:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — 200 response missing "
                      f"contract keys {missing}: {raw[:200]}")
                defect = True
            elif b.get("status") != "ok":
                print(f"NOTE — status field is {b.get('status')!r}, contract says 'ok'")
    else:
        print(f"VERDICT: SCRIPT_ERROR — minimal legal create rejected with {s}: {raw[:200]}")
        sys.exit(2)
    try:
        safe_request("DELETE", f"/collections/{cname}")
    except Exception:
        pass

    # (b) timeout query param boundary (contract: min 1).
    timeout_cases = [
        ("timeout=0 (min-1)", "0", True),
        ("timeout=-1", "-1", True),
        ("timeout=0.5 (non-integer)", "0.5", True),
        ("timeout=1 (min, legal)", "1", False),
    ]
    counter = 0
    for label, tval, should_reject in timeout_cases:
        counter += 1
        cname = f"bnd_c2of2_to_{counter}"
        try:
            safe_request("DELETE", f"/collections/{cname}")
        except Exception:
            pass
        s, b, raw = safe_request("PUT", f"/collections/{cname}?timeout={tval}", json=BODY)
        print(f"CASE {label}: status={s} body={raw[:300]}")
        if s == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            sys.exit(2)
        if should_reject and s in (200, 201):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — create with ?timeout={tval} "
                  f"accepted with {s} (contract: timeout min 1)")
            defect = True
        try:
            safe_request("DELETE", f"/collections/{cname}")
        except Exception:
            pass

    if defect:
        return
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
