#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Attack Vein - Range Filter Condition (shardingConfig numeric boundary)

Target: weaviate v1.37.4
Endpoint: POST /v1/schema (create class) -> shardingConfig.desiredCount
Condition: range_filter - negative desiredCount (invalid numeric boundary)

Defect hypothesis: POST /v1/schema with shardingConfig.desiredCount < 0 returns
HTTP 200 with an EMPTY body (no class echo, no error), but the created class is
a "phantom": GET /v1/schema/{class} returns 404, the class is absent from the
schema list, POST /v1/schema/{class}/properties fails with 422 "class is nil:
not found", and GraphQL cannot see it -- until the first object is written into
it, after which the class becomes visible. The API claims success for a class
that is not actually usable as a schema (submit-persist consistency break).

Controls:
  - desiredCount=0  -> 422 with explicit error ("failed to read sharding state")
    proving the validation path for invalid desiredCount EXISTS.
  - desiredCount=1  -> 200 with full class echo + GET 200 (normal behavior).
So negative values bypass validation and silently produce a phantom class.

Root finding chain: R1 found replicationConfig.factor=-1/0 is silently
normalized to 1 (by-design, source Factor<1->1, response discloses echo).
R2 deep-dive asks whether the POST response discloses normalization/accepted
state. Factor DOES disclose (echoes 1). shardingConfig.desiredCount<0 does NOT
disclose (empty body) AND yields an inconsistent phantom state.

Strategy: vein_range_filter
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
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

CLASS_NAME = f"VeinShardingZombie{os.getpid()}"


def safe_request(method, path, json=None, timeout=15):
    """Resilient HTTP wrapper -> (status_code, body_or_None, raw_text)."""
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.request(method=method, url=url, json=json,
                                headers=headers, timeout=timeout)
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


def cleanup():
    try:
        status, body, raw = safe_request("DELETE", f"/v1/schema/{CLASS_NAME}")
        if status not in (200, 204, 404):
            print(f"Cleanup warning: DELETE returned {status}: {raw[:200]}")
    except Exception as e:
        print(f"Cleanup warning: {e}")


def _verdict(v, msg):
    print(f"VERDICT: {v}: {msg}")
    sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)


def main():
    # ============ Act: create class with negative desiredCount ============
    payload = {
        "class": CLASS_NAME,
        "vectorizer": "none",
        "shardingConfig": {"desiredCount": -3}
    }
    status, body, raw = safe_request("POST", "/v1/schema", json=payload)
    print(f"POST create (desiredCount=-3) Status: {status}")
    print(f"POST create raw: '{raw[:300]}'")

    if status == 0:
        _verdict("SCRIPT_ERROR", "connection failed")

    # Phantom checks immediately after create (before any object write)
    gstatus, gbody, graw = safe_request("GET", f"/v1/schema/{CLASS_NAME}")
    print(f"GET schema immediately: {gstatus} body='{graw[:150]}'")

    pstatus, pbody, praw = safe_request(
        "POST", f"/v1/schema/{CLASS_NAME}/properties",
        json={"name": "title", "dataType": ["text"]})
    print(f"POST add-property immediately: {pstatus} {praw[:150]}")

    # ---- Controls (distinct class names to avoid residue collision) ----
    ctrl_zero_cls = f"VeinShardingCtrlZero{os.getpid()}"
    c0, c0b, c0r = safe_request("POST", "/v1/schema",
        json={"class": ctrl_zero_cls, "vectorizer": "none",
              "shardingConfig": {"desiredCount": 0}})
    c0g, c0gb, c0gr = safe_request("GET", f"/v1/schema/{ctrl_zero_cls}")
    print(f"CONTROL desiredCount=0 -> {c0}: {c0r[:200]}")
    print(f"CONTROL desiredCount=0 residue GET={c0g} (class exists after 422?)")
    if c0g == 200:
        safe_request("DELETE", f"/v1/schema/{ctrl_zero_cls}")

    ctrl_one_cls = f"VeinShardingCtrlOne{os.getpid()}"
    c1, c1b, c1r = safe_request("POST", "/v1/schema",
        json={"class": ctrl_one_cls, "vectorizer": "none",
              "shardingConfig": {"desiredCount": 1}})
    c1g, c1gb, c1gr = safe_request("GET", f"/v1/schema/{ctrl_one_cls}")
    print(f"CONTROL desiredCount=1 -> {c1} body_len={len(c1r)} GET={c1g}")
    safe_request("DELETE", f"/v1/schema/{ctrl_one_cls}")

    # ---- Judgment ----
    created_ok = status in (200, 201)
    empty_or_no_echo = (raw.strip() == "") or (body is None)
    phantom = (gstatus == 404) or (pstatus in (404, 422) and "class is nil" in praw)

    if created_ok and empty_or_no_echo and phantom and c0 in (400, 422):
        _verdict("DEFECT_FOUND",
            f"Type1_IllegalSuccess/Type2: POST /v1/schema with "
            f"shardingConfig.desiredCount=-3 returned HTTP {status} with EMPTY "
            f"body (no class echo, no error). The 'created' class is a phantom: "
            f"GET /v1/schema/{CLASS_NAME} -> {gstatus} (class not readable), "
            f"POST properties -> {pstatus} 'class is nil: not found' (schema API "
            f"cannot extend it), until an object write forces registration. "
            f"Control desiredCount=0 -> {c0} (explicit rejection) proves the "
            f"validation path exists; negative values bypass it and silently "
            f"produce an inconsistent phantom state, and the 200 response "
            f"discloses nothing (empty body).")
    elif created_ok and not phantom:
        _verdict("NO_DEFECT",
            f"HTTP {status} but class is immediately readable (GET {gstatus}), "
            f"no phantom state observed.")
    elif c0 not in (400, 422):
        _verdict("NO_DEFECT",
            f"control desiredCount=0 returned {c0} (not rejected) -> negative "
            f"acceptance may be part of a broader design; no defect asserted.")
    else:
        _verdict("NO_DEFECT",
            f"unexpected combination status={status} empty={empty_or_no_echo} "
            f"phantom={phantom} c0={c0}")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
