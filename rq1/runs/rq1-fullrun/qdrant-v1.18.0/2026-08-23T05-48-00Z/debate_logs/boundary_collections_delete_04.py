#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: type confusion — timeout query param declared integer (min 1) fed non-integer values
Constraint: qdrant_state_collections_delete_001 (endpoint contract; timeout: integer)
Endpoint: collections+delete -> DELETE /collections/{collection_name}?timeout=
Round block: chunk_collections+delete
Coverage map: [strategy 2 type_confusion x state_collections_delete_001] timeout="abc" / 1.5 / true
Unit: constraints::qdrant_state_collections_delete_001
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


def create_col(name):
    return safe_request("PUT", f"/collections/{name}",
                        json={"vectors": {"size": 4, "distance": "Cosine"}})


def get_status(name):
    s, _, _ = safe_request("GET", f"/collections/{name}")
    return s


def try_value(col, value, label):
    s, _, raw = safe_request("DELETE", f"/collections/{col}", params={"timeout": value})
    shown = value if not isinstance(value, str) else value[:32]
    print(f"[{label}] timeout={shown!r} -> status={s} raw={raw[:250]}")
    if s == 0:
        return "SCRIPT_ERROR:0"
    if s in (400, 422):
        g = get_status(col)
        print(f"[{label}] post-reject GET={g}")
        if g != 200:
            return (f"DEFECT_FOUND (Type4_StateLogicViolation): {label} rejected with {s} "
                    f"but collection disappeared (GET={g})")
        return None
    if s == 200:
        g = get_status(col)
        print(f"[{label}] post-200 GET={g} (deleted={g != 200})")
        return (f"DEFECT_FOUND (Type1_IllegalSuccess): {label} — non-integer timeout "
                f"accepted, DELETE executed (collection gone={g != 200})")
    return f"DEFECT_FOUND (Type3_RuntimeFailure): {label} -> unexpected status {s}"


try:
    cases = [
        ("bd04_t_str", "abc", "string"),
        ("bd04_t_float", 1.5, "float"),
        ("bd04_t_bool", True, "bool"),
    ]
    setup_failed = False
    for col, _, _ in cases:
        s, _, raw = create_col(col)
        print(f"setup {col}: {s}")
        if s not in (200, 201):
            setup_failed = True
    if setup_failed:
        print("VERDICT: SCRIPT_ERROR — fixture collection creation failed")
        sys.exit(2)

    verdicts = []
    for col, val, label in cases:
        v = try_value(col, val, label)
        if v:
            verdicts.append(f"[{label}] {v}")

    if any(v.startswith("DEFECT_FOUND") for v in verdicts):
        print("VERDICT: DEFECT_FOUND — " + " | ".join(verdicts))
    elif any(v.startswith("SCRIPT_ERROR") for v in verdicts):
        print("VERDICT: SCRIPT_ERROR — connection failure during test")
        sys.exit(2)
    else:
        print("VERDICT: NO_DEFECT — non-integer timeout values rejected with 4xx, collections intact")
except SystemExit:
    raise
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR — unhandled exception: {e}")
    sys.exit(2)
finally:
    for col in ("bd04_t_str", "bd04_t_float", "bd04_t_bool"):
        try:
            safe_request("DELETE", f"/collections/{col}")
        except Exception:
            pass
