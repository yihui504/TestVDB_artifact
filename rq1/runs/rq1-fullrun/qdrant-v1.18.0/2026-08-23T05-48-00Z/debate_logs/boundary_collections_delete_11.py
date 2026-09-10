#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: resource-limit extremes (strategy 6) — timeout query param at/above integer domain limits
Constraint: qdrant_state_collections_delete_001 (endpoint contract; timeout: integer min 1)
Endpoint: collections+delete -> DELETE /collections/{collection_name}?timeout=
Round block: chunk_collections+delete
Coverage map: [strategy 6 resource_limit x state_collections_delete_001]
  timeout=INT_MAX / u64_MAX / 23-digit overflow string
Unit: constraints::qdrant_state_collections_delete_001
Note: 200 (accepted) or 4xx are both non-defects here; 5xx/OOM/panic = Type3 DoS signal.
Out-of-domain values accepted with 200 are flagged Type1 (violates documented integer domain).
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


PANIC_KEYS = ("panic", "out of memory", "oom", "overflow", "internal error")

def create_col(name):
    return safe_request("PUT", f"/collections/{name}",
                        json={"vectors": {"size": 4, "distance": "Cosine"}})

def get_status(name):
    s, _, _ = safe_request("GET", f"/collections/{name}")
    return s

try:
    # value, label, is_out_of_domain
    cases = [
        (2147483647, "int32-max", False),
        (9223372036854775807, "u64-max", False),
        ("99999999999999999999999", "23-digit-overflow", True),
    ]
    names = ["bd11_intmax", "bd11_u64max", "bd11_overflow"]

    setup_failed = False
    for n in names:
        s, _, _ = create_col(n)
        print(f"setup {n}: {s}")
        if s not in (200, 201):
            setup_failed = True
    if setup_failed:
        print("VERDICT: SCRIPT_ERROR — fixture creation failed")
        sys.exit(2)

    defects = []
    for (val, label, out_of_domain), name in zip(cases, names):
        s, _, raw = safe_request("DELETE", f"/collections/{name}", params={"timeout": val})
        shown = val if not isinstance(val, str) else val[:26]
        print(f"[{label}] timeout={shown} -> status={s} raw={raw[:250]}")
        if s == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            sys.exit(2)
        low = raw.lower()
        if s >= 500 or any(k in low for k in PANIC_KEYS):
            defects.append(f"[{label}] Type3_RuntimeFailure: {s}/crash keywords on extreme timeout")
        elif s == 200:
            g = get_status(name)
            print(f"[{label}] post-200 GET={g}")
            if out_of_domain and g != 200:
                defects.append(f"[{label}] Type1_IllegalSuccess: out-of-domain timeout accepted, "
                               f"delete executed (collection gone)")
        elif s in (400, 422):
            g = get_status(name)
            print(f"[{label}] rejected 4xx; collection intact={g == 200}")
        else:
            defects.append(f"[{label}] unexpected status {s}")

    if defects:
        print("VERDICT: DEFECT_FOUND — " + " | ".join(defects))
    else:
        print("VERDICT: NO_DEFECT — extreme timeout values handled without 5xx/crash; "
              "out-of-domain rejected or benign")
except SystemExit:
    raise
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR — unhandled exception: {e}")
    sys.exit(2)
finally:
    for n in ("bd11_intmax", "bd11_u64max", "bd11_overflow"):
        try:
            safe_request("DELETE", f"/collections/{n}")
        except Exception:
            pass
