#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_exists_006
# strategy: strategy6_resource_limit
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-07 (Resource Exhaustion Blindspot)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 resource-limit on the collection_name path param x qdrant_behavioral_collections_exists_001 (identifier lengths 10k and 100k chars - implementation-layer resource limits on a read-only lookup, distinct from strategy 1's contract min-1 boundary)
Oracle: control short-name probe returns 200 + result.exists bool False first; then for each overlong name: a clean 4xx (e.g. 400/414/404) or HTTP 200 with result.exists exactly bool False = no defect (accepting a large identifier on a read-only lookup is legal; only a crash is the defect); 5xx = Type3_RuntimeFailure; a transport failure with healthz dead = Type3 (server crashed under the request); a request-specific timeout while healthz AND the control probe still succeed = Type3 (endpoint hang/DoS); other transport failures = SCRIPT_ERROR per G8

Resource-limit vs boundary-value distinction (spec v2.2): the contract does not
document an upper bound for collection_name length; we do NOT demand rejection -
we demand graceful degradation (no 5xx, no OOM, no hang) on spec-legal but
resource-extreme identifiers.

Constraint (bare id): qdrant_behavioral_collections_exists_001 (existence must
be answered in the body over the 200 channel for any identifier the server
chooses to accept; {result:{exists:bool}} shape per contract response_shape).

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url;
R12 lesson: register collections+exists verbatim - established pattern):
  collections+exists -> GET /collections/{collection_name}/exists
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    _root = Path(__file__).resolve()
    for _p in (_root, *_root.parents):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or TARGET != "qdrant":
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)

# URL registry - verbatim from raw_knowledge.json api_endpoints[].url
PATH_EXISTS = "/collections/{collection_name}/exists"   # collections+exists

TS = int(time.time())
CONTROL_NAME = f"b6cex_ctrl_{TS}"
LONG_10K = f"b6cex_{'a' * 10000}"
LONG_100K = f"b6cex_{'a' * 100000}"
REQUEST_TIMEOUT = 60


def safe_request(method, endpoint, json=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md).
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, headers=headers, timeout=timeout
        )
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except Exception:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def healthz_alive():
    """G8: transport failures get a lightweight /healthz re-check before any Type3."""
    try:
        st, _, _ = safe_request("GET", "/healthz", timeout=10)
        return st == 200
    except Exception:
        return False


def control_probe_ok():
    """A short-name exists probe that must succeed; used to isolate an
    endpoint-specific hang from a server-wide failure."""
    st, body, raw = safe_request("GET", PATH_EXISTS.format(collection_name=CONTROL_NAME),
                                 timeout=30)
    if st == 200 and isinstance(body, dict):
        result = body.get("result")
        if isinstance(result, dict) and type(result.get("exists")) is bool:
            return True
    print(f"control probe unusable: status={st} raw={raw[:200]}")
    return False


def judge_long_name(label, name):
    """Declare expectation, then compare (graceful-degradation typing)."""
    st, body, raw = safe_request("GET", PATH_EXISTS.format(collection_name=name),
                                 timeout=REQUEST_TIMEOUT)
    print(f"GET exists [{label}] (len={len(name)}) -> status={st}")
    print(f"raw: {raw[:400]}")

    if st == -1:
        # G8: liveness re-check BEFORE any Type3 judgment
        alive = healthz_alive()
        print(f"transport failure on {label} (healthz alive={alive}); failure text: {raw[:200]}")
        if not alive:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - {label} crashed the "
                  f"server (healthz unreachable after the request)")
            return False
        if "timeout" in str(raw).lower() and control_probe_ok():
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - {label} hung the exists "
                  f"endpoint (request timeout while healthz and the short-name control "
                  f"probe still succeed) - endpoint-specific DoS")
            return False
        print("VERDICT: SCRIPT_ERROR - transport failure with live server and failing "
              "control probe, no defect conclusion")
        return False
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - {label} returned server "
              f"error {st} (resource-extreme identifier must degrade gracefully)")
        return False
    if 400 <= st <= 499:
        print(f"OK: {label} cleanly rejected with {st}")
        return True
    if not (200 <= st <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - unexpected status "
              f"{st} for {label}")
        return False
    # 200 branch: shape closure (result: object, result.exists: boolean)
    if not isinstance(body, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - body is not a JSON "
              f"object for {label}: {raw[:300]}")
        return False
    result = body.get("result")
    if not isinstance(result, dict) or "exists" not in result:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result is not "
              f"{{exists: bool}} for {label}: {raw[:300]}")
        return False
    exists_val = result["exists"]
    if type(exists_val) is not bool:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.exists is not "
              f"a boolean for {label} "
              f"(got {type(exists_val).__name__}={exists_val!r}): {raw[:300]}")
        return False
    if exists_val is True:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - {label} reported "
              f"result.exists=true; the name was never created")
        return False
    print(f"OK: {label} -> 200 with result.exists == False (accepted, graceful)")
    return True


def main():
    # ---- control: short unique name must give a clean 200/exists=false baseline ----
    st, body, raw = safe_request("GET", PATH_EXISTS.format(collection_name=CONTROL_NAME),
                                 timeout=30)
    print(f"control GET exists on {CONTROL_NAME} -> status={st}")
    print(f"control raw: {raw[:300]}")
    if st == -1:
        alive = healthz_alive()
        print(f"transport failure on control probe (healthz alive={alive})")
        print("VERDICT: SCRIPT_ERROR - transport failure in control, no defect conclusion")
        return
    if st != 200:
        print(f"VERDICT: SCRIPT_ERROR - control probe returned {st} (expected 200 "
              f"exists=false baseline); cannot adjudicate hang isolation")
        return
    result = body.get("result") if isinstance(body, dict) else None
    if not (isinstance(result, dict) and result.get("exists") is False):
        print(f"VERDICT: SCRIPT_ERROR - control probe shape unexpected: {raw[:200]}")
        return
    print("control baseline OK: 200 / result.exists == False")

    # ---- resource-limit probes: 10k and 100k char identifiers ----
    all_ok = judge_long_name("10k-char name", LONG_10K)
    if all_ok:
        all_ok = judge_long_name("100k-char name", LONG_100K)

    if all_ok:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
