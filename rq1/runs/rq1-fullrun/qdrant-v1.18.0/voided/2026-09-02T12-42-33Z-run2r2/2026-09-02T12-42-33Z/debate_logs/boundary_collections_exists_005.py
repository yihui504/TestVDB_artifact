#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_exists_005
# strategy: strategy1_lifecycle_flip
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 lifecycle-flip x qdrant_behavioral_collections_exists_001 (sequential state mutation create -> exists -> DELETE -> exists -> recreate -> exists; the R12 collections+delete tie-in: existence bookkeeping across the delete boundary)
Oracle: every exists probe returns HTTP 200 with result.exists exactly bool (never 404 - "existence is never expressed as HTTP 404" applies most sharply right after DELETE, where REST frameworks default to not-found); flip to true within 2.5s after create, to false within 5s after delete, back to true within 2.5s after recreate; a 404 at any point = Type1_IllegalRejection, a stuck exists=true after delete (5s window) = Type4_StateLogicViolation (stale existence), 5xx = Type3_RuntimeFailure

G6 mutation justification (why DELETE is the mutation most likely to break the
invariant): existence is a membership flag over collection metadata; DELETE is
the only operation that removes a member, and the post-delete state is exactly
where (a) framework default not-found handlers substitute 404 for the promised
200 {exists:false}, and (b) stale/cached metadata keeps reporting true. The
recreate leg verifies the flip is reversible (no poisoned negative cache).

Constraint (bare id): qdrant_behavioral_collections_exists_001
  expected_behavior: "HTTP 200 with result being an object of shape {exists: bool};
  a missing collection yields result.exists=false with HTTP 200 (never 404)"
Shape anchor (D3b rule 2): contract response_shape result: object,
result.exists: boolean (R5 exists-shape lesson).

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url;
R12 lesson: register collections+exists verbatim - established pattern):
  collections+exists -> GET  /collections/{collection_name}/exists
  collections+create -> PUT  /collections/{collection_name}
  collections+delete -> DELETE /collections/{collection_name}
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
PATH_CREATE = "/collections/{collection_name}"          # collections+create
PATH_DELETE = "/collections/{collection_name}"          # collections+delete

POLL_INTERVAL = 0.5
FLIP_TIMEOUT_S = 5.0     # post-delete window to reach exists=false
RISE_TIMEOUT_S = 2.5     # post-create/recreate window to reach exists=true

COLL = f"b5cex_flip_{int(time.time())}"


class Defect(Exception):
    """Carries an already-printed verdict out of the polling helpers."""

    def __init__(self, verdict_printed):
        super().__init__(verdict_printed)
        self.verdict_printed = verdict_printed


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


def cleanup():
    """Teardown: best-effort delete; cleanup failure must never fail the script."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=COLL), timeout=15)
    except Exception:
        pass


def read_exists(phase):
    """One exists probe, adjudicated against the assertion channel contract.
    Returns True/False (the exists value) or raises Defect / returns None on
    conditions that already ended the script."""
    st, body, raw = safe_request("GET", PATH_EXISTS.format(collection_name=COLL), timeout=30)
    print(f"[{phase}] GET exists on {COLL} -> status={st}")
    print(f"[{phase}] raw: {raw[:400]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure in {phase} (healthz status={hs}: {hraw[:200]})")
        raise Defect("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
    if 500 <= st <= 599:
        raise Defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - exists probe in "
                     f"{phase} returned server error {st}")
    if st == 404:
        raise Defect(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) - exists probe in "
                     f"{phase} returned 404; assertion: existence is never expressed as "
                     f"HTTP 404 (post-DELETE is precisely where frameworks default to it)")
    if not (200 <= st <= 299):
        raise Defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - expected HTTP "
                     f"200 in {phase}, got {st}")
    if not isinstance(body, dict):
        raise Defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - body is not a "
                     f"JSON object in {phase}: {raw[:300]}")
    result = body.get("result")
    if not isinstance(result, dict) or "exists" not in result:
        raise Defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result is not "
                     f"{{exists: bool}} in {phase}: {raw[:300]}")
    exists_val = result["exists"]
    if type(exists_val) is not bool:
        raise Defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.exists is "
                     f"not a boolean in {phase} "
                     f"(got {type(exists_val).__name__}={exists_val!r}): {raw[:300]}")
    return exists_val


def poll_exists(phase, want, window_s):
    """Poll exists until it equals `want` within `window_s`.
    Logs intermediate values as observations; raises Defect on channel/shape
    violations or on a stuck value; returns True when the flip is observed."""
    deadline = time.time() + window_s
    observed = []
    while True:
        val = read_exists(phase)
        observed.append(val)
        if val is want:
            print(f"[{phase}] flip to exists={want} observed "
                  f"(poll trace: {observed}, window {window_s}s)")
            return True
        if time.time() >= deadline:
            return False
        time.sleep(POLL_INTERVAL)


def main():
    # ---- 1) create -> exists must become true ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=COLL),
                              json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=30)
    print(f"setup create {COLL}: status={st}")
    print(f"setup raw: {raw[:300]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on setup (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure in setup, no defect conclusion")
        return
    if st not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR - setup failed creating {COLL}: {st} {raw[:300]}")
        return
    try:
        if not poll_exists("post-create", True, RISE_TIMEOUT_S):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - exists stayed "
                  f"false for {RISE_TIMEOUT_S}s after a 200 create of {COLL}")
            return

        # ---- 2) delete -> exists must flip to false, channel must stay 200 ----
        st, _, raw = safe_request("DELETE", PATH_DELETE.format(collection_name=COLL), timeout=30)
        print(f"delete {COLL}: status={st}")
        print(f"delete raw: {raw[:300]}")
        if st == -1:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"transport failure on delete (healthz status={hs}: {hraw[:200]})")
            print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
            return
        if st not in (200, 202):
            print(f"VERDICT: SCRIPT_ERROR - delete of {COLL} failed: {st} {raw[:300]} "
                  f"(setup mutation failed; no defect conclusion on exists)")
            return
        if not poll_exists("post-delete", False, FLIP_TIMEOUT_S):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - exists stayed "
                  f"true for {FLIP_TIMEOUT_S}s after a 200 delete of {COLL} "
                  f"(stale existence bookkeeping)")
            return

        # ---- 3) recreate same name -> exists must flip back to true ----
        st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=COLL),
                                  json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=30)
        print(f"recreate {COLL}: status={st}")
        print(f"recreate raw: {raw[:300]}")
        if st == -1:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"transport failure on recreate (healthz status={hs}: {hraw[:200]})")
            print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
            return
        if st not in (200, 201):
            print(f"VERDICT: SCRIPT_ERROR - recreate of {COLL} failed: {st} {raw[:300]} "
                  f"(setup mutation failed; no defect conclusion on exists)")
            return
        if not poll_exists("post-recreate", True, RISE_TIMEOUT_S):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - exists stayed "
                  f"false for {RISE_TIMEOUT_S}s after recreate of {COLL} "
                  f"(poisoned negative cache after delete)")
            return

        print("OK: exists flipped true -> false -> true across the delete boundary, "
              "channel stayed HTTP 200 with boolean result.exists throughout")
        print("VERDICT: NO_DEFECT")
    except Defect as d:
        print(d.verdict_printed)


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
