#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_get_006
# strategy: strategy6_resource_limit
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-07 (Resource Exhaustion Blindspot) + BS-04 (Boundary Default Optimism)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 resource-limit x qdrant_behavioral_collections_get_001 (implementation-layer resource boundary of the describe face: overlong NEVER-CREATED collection_name path values at 256/1024/8192 chars - the contract pins 404 for missing collections, so accepting/handling large identifiers is legal and the defect signal is a crash, hang, or memory blow-up, not acceptance)
Oracle: control first: a short never-created b6cget_* name returns 404 (proves the face is live and pins the baseline channel); then for each overlong never-created name (256/1024/8192 chars): HTTP 404 = no defect (unknown name), HTTP 400/414/422 = no defect (explicit length/parse rejection), HTTP 2xx = Type1_IllegalSuccess (config for a nonexistent collection), HTTP 5xx = Type3_RuntimeFailure; a request-specific transport failure re-checked via GET /healthz: healthz dead = Type3 (server crashed under the request), healthz alive AND the control probe still 404s = Type3 (this face hangs/DoS on the value), otherwise SCRIPT_ERROR per G8
Constraint (bare id): qdrant_behavioral_collections_get_001
  expected_behavior: "missing collection: HTTP 404 with an error message,
  never 200 with config"
  evidence_tier: explicit; level: endpoint.
Strategy-6 key distinction from strategy-1: here 200-acceptance of a huge
identifier would be a CONTRACT violation (Type1 leg kept), but the primary
defect class is Type3 - OOM/panic/hang from unbounded path-parameter
buffering (qdrant #8406-class allocator pressure, applied to the name channel
of the describe face). Read-only lookup of a large identifier is cheap and
legal; only a crash is the defect.

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  collections+get -> GET /collections/{collection_name}
  healthz         -> GET /healthz
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
PATH_GET = "/collections/{collection_name}"   # collections+get

TS = int(time.time())
CONTROL = f"b6cget_ctrl_{TS}"                 # short, never-created
OVERLONG = [
    ("len_256",  "b6cget_r_" + "a" * 256 + f"_{TS}"),
    ("len_1024", "b6cget_r_" + "b" * 1024 + f"_{TS}"),
    ("len_8192", "b6cget_r_" + "c" * 8192 + f"_{TS}"),
]


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


def control_probe_ok():
    """Re-run the short never-created control probe; True iff it still cleanly 404s."""
    st, _, raw = safe_request("GET", PATH_GET.format(collection_name=CONTROL), timeout=15)
    print(f"control re-probe: status={st} raw={raw[:150]}")
    return st == 404


def main():
    # ---- Control: short never-created name pins the live 404 baseline ----
    st, _, raw = safe_request("GET", PATH_GET.format(collection_name=CONTROL), timeout=15)
    print(f"control probe on '{CONTROL}' -> status={st}")
    print(f"raw: {raw[:200]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on control (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure on control, no defect conclusion")
        return
    if st != 404:
        print(f"VERDICT: SCRIPT_ERROR - control probe did not return the expected live "
              f"baseline 404 (got {st}: {raw[:200]}); refusing to interpret overlong legs")
        return
    print("OK: control = 404 (face live, baseline pinned)")

    # ---- Overlong never-created names: defect signal is crash/hang, not acceptance ----
    for label, name in OVERLONG:
        print(f"--- probe [{label}] name_len={len(name)} ---")
        st, _, raw = safe_request("GET", PATH_GET.format(collection_name=name), timeout=30)
        print(f"status={st}")
        print(f"raw: {raw[:200]}")

        if st == -1:
            # transport branch: liveness re-check via the lightweight health endpoint
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"transport failure on [{label}] (err: {raw[:150]}); healthz status={hs}: {hraw[:150]}")
            if hs == -1 or not (200 <= hs <= 299):
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - healthz dead after "
                      f"the overlong [{label}] describe request (server crashed)")
                return
            if control_probe_ok():
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - request-specific "
                      f"transport failure on [{label}] while healthz is alive and the "
                      f"control probe still 404s: this face hangs/DoSes on the overlong value")
                return
            print("VERDICT: SCRIPT_ERROR - transport failure not attributable to this "
                  "probe (control also failing after healthz recovered)")
            return
        if 500 <= st <= 599:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - overlong name [{label}] "
                  f"triggered server error {st}: {raw[:200]}")
            return
        if 200 <= st <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - overlong never-created "
                  f"name [{label}] returned HTTP {st} (config served for a nonexistent "
                  f"collection: {raw[:200]})")
            return
        if st in (404, 400, 414, 422):
            print(f"OK: [{label}] cleanly handled with {st}")
            continue
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - unexpected channel "
              f"{st} for overlong unknown name [{label}]: {raw[:200]}")
        return

    print("OK: all overlong never-created names handled without crash/hang "
          "(404 or explicit length rejection; never 5xx, never 200-with-config)")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
