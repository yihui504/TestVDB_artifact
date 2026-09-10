#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: malformed input / strategy 7 — DELETE with raw malformed bodies (spec defines no body)
Constraint: qdrant_state_collections_delete_001 (DELETE existing => 200)
Endpoint: collections+delete -> DELETE /collections/{collection_name}
Round block: chunk_collections+delete
Coverage map: [strategy 7 malformed x state_collections_delete_001]
  truncated JSON / binary NUL bytes / 1MB junk body
Unit: constraints::qdrant_state_collections_delete_001
Rationale: DELETE has no documented request body; malformed bodies must be ignored (200)
or explicitly rejected (4xx) — never 5xx/panic (parser must not trust input).
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


PANIC_KEYS = ("panic", "internal", "serde", "decode", "utf", "overflow", "out of memory", "oom")

def check(label, col, body_bytes, ctype):
    s, _, raw = safe_request("DELETE", f"/collections/{col}",
                             data=body_bytes, headers={"Content-Type": ctype})
    print(f"[{label}] len={len(body_bytes)} ctype={ctype} -> status={s} raw={raw[:250]}")
    if s == 0:
        return "SCRIPT_ERROR:0"
    low = raw.lower()
    if s >= 500 or any(k in low for k in PANIC_KEYS):
        return (f"DEFECT_FOUND (Type3_RuntimeFailure): {label} — malformed body triggered "
                f"{s}/parser-internals leak")
    if s == 200:
        g, _, _ = safe_request("GET", f"/collections/{col}")
        print(f"[{label}] post-200 GET={g} (body was ignored and delete proceeded: {g != 200})")
        return None  # body ignored -> acceptable
    if s in (400, 422):
        return None  # explicit rejection acceptable
    return f"DEFECT_FOUND (Type3_RuntimeFailure): {label} -> unexpected status {s}"


try:
    cols = ["bd06_trunc", "bd06_bin", "bd06_big"]
    setup_failed = False
    for c in cols:
        s, _, _ = create_col(c)
        print(f"setup {c}: {s}")
        if s not in (200, 201):
            setup_failed = True
    if setup_failed:
        print("VERDICT: SCRIPT_ERROR — fixture collection creation failed")
        sys.exit(2)

    verdicts = []
    v = check("truncated-json", "bd06_trunc", b'{"a": 1', "application/json")
    if v:
        verdicts.append(v)
    v = check("binary-nul", "bd06_bin", b"\x00\x01\x02\xff", "application/octet-stream")
    if v:
        verdicts.append(v)
    v = check("1mb-junk", "bd06_big", b"x" * 1048576, "text/plain")
    if v:
        verdicts.append(v)

    if any(x.startswith("DEFECT_FOUND") for x in verdicts):
        print("VERDICT: DEFECT_FOUND — " + " | ".join(verdicts))
    elif any(x.startswith("SCRIPT_ERROR") for x in verdicts):
        print("VERDICT: SCRIPT_ERROR — connection failure during test")
        sys.exit(2)
    else:
        print("VERDICT: NO_DEFECT — malformed DELETE bodies ignored (200) or rejected (4xx); no 5xx")
except SystemExit:
    raise
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR — unhandled exception: {e}")
    sys.exit(2)
finally:
    for c in ("bd06_trunc", "bd06_bin", "bd06_big"):
        try:
            safe_request("DELETE", f"/collections/{c}")
        except Exception:
            pass
