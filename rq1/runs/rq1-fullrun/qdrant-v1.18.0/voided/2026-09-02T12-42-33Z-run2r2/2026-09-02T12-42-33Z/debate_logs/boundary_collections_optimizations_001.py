#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_optimizations_001
# strategy: strategy1_boundary_behavioral_positive
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the live face must answer the documented
#            status readout at the zero-data boundary, not just after writes)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value / behavioral-positive x qdrant_behavioral_collections_optimizations_001
(G4 positive branch + response-shape closure at the zero-data boundary): a freshly created,
never-written collection must still answer GET /collections/{name}/optimizations with HTTP 200
carrying the documented optimizer-status envelope result.summary{queued_optimizations,
queued_segments, queued_points, idle_segments} (integers) + result.running — the "existing
collection -> HTTP 200 with optimizer status per shard" promise holds from the very first
instant of existence.
Oracle: after a successful PUT create of a b1opt1p_* collection (vectors size=4
distance=Cosine), GET /collections/{name}/optimizations returns HTTP 200 where result is an
object whose summary is an object with keys queued_optimizations/queued_segments/
queued_points/idle_segments each typed integer and a running key typed array (list) when
present; 404/422 on the live collection = Type1_IllegalRejection, any other non-200 4xx =
Type4_StateLogicViolation, 5xx = Type3_RuntimeFailure, missing result/summary object or
present-but-wrong-typed summary field/running field = Type4_StateLogicViolation
Constraint: qdrant_behavioral_collections_optimizations_001 (bare id) — "returns 200 with
optimizer status per shard; 404 for a missing collection" (evidence_tier: explicit; level:
endpoint; expected_behavior: "existing collection: HTTP 200 with per-shard optimizer status;
missing collection: HTTP 404").

[coverage: strategy1 x qdrant_behavioral_collections_optimizations_001; unit assertions::qdrant_behavioral_collections_optimizations_001]
Shape anchor (D3b + R14 standing lesson — shape oracles cross-checked against the published
OpenAPI; spec wins): the contract api_endpoints['collections+optimizations'].response_shape
is self-consistent with this face (result.summary object with the four integer queue/idle
counters, result.running array of per-optimization objects, queued/completed/idle_segments
array-or-null) — no cross-endpoint extraction artifact (unlike the collections+list face).
Adjudication keys off envelope result.<field> with present-group typing: present-but-wrong-
typed = shape conflict judged Type4; absent optional groups are printed, not judged; the
summary aggregation object itself is the documented "optimizer status" readout and is gated
present on a live collection. Error-message fields are not gated (threat-model by-design
list: error structure is implementation detail).

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  collections+optimizations -> GET    /collections/{collection_name}/optimizations
  collections+create        -> PUT    /collections/{collection_name}
  collections+delete        -> DELETE /collections/{collection_name}
  healthz                   -> GET    /healthz
"""

import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

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
PATH_OPTIMIZATIONS = "/collections/{collection_name}/optimizations"   # collections+optimizations
PATH_CREATE = "/collections/{collection_name}"                        # collections+create
PATH_DELETE = "/collections/{collection_name}"                        # collections+delete


def safe_request(method, endpoint, json=None, timeout=10, data=None, params=None):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md),
    extended per R14/R15 standing lessons to forward raw bodies (data=) and query params
    (params=) exactly. Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, data=data, params=params,
            headers=headers, timeout=timeout
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


COLL = "b1opt1p_" + uuid.uuid4().hex[:10]   # unique-prefix discipline: only this script's resource


def cleanup():
    """Teardown: best-effort delete of ONLY the collection this script created."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")), timeout=30)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    # ---- Arrange: create a live collection at its zero-data boundary ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
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

    # ---- Act: the documented status readout on the live (never-written) collection ----
    st, body, raw = safe_request("GET", PATH_OPTIMIZATIONS.format(collection_name=quote(COLL, safe="")),
                                 timeout=30)
    print(f"GET optimizations on {COLL} -> status={st}")
    print(f"raw: {raw[:800]}")

    # ---- Assert (declare expectation first, then compare) ----
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on optimizations probe (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - optimizations readout on a live "
              f"collection returned server error {st}")
        return
    if st in (404, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) - optimizations on the live "
              f"collection {COLL} returned {st}; assertion requires HTTP 200 with per-shard "
              f"optimizer status")
        return
    if not (200 <= st <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - expected HTTP 200 for an "
              f"existing collection, got {st}")
        return

    # 200 branch: envelope + shape closure per contract response_shape
    if not isinstance(body, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - response body is not a "
              f"JSON object: {raw[:300]}")
        return
    result = body.get("result")
    if not isinstance(result, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result is not an object; "
              f"got {type(result).__name__}: {raw[:300]}")
        return
    summary = result.get("summary")
    if not isinstance(summary, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.summary (the "
              f"documented per-shard optimizer-status aggregation) is missing or not an "
              f"object; got {type(summary).__name__}: {raw[:300]}")
        return
    int_keys = ("queued_optimizations", "queued_segments", "queued_points", "idle_segments")
    for k in int_keys:
        v = summary.get(k)
        if v is not None and (type(v) is not int):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.summary.{k} is "
                  f"present but not an integer (got {type(v).__name__}={v!r}): {raw[:300]}")
            return
    running = result.get("running")
    if running is not None and not isinstance(running, list):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.running is present "
              f"but not an array (got {type(running).__name__}): {raw[:300]}")
        return
    for k in ("queued", "completed", "idle_segments"):
        v = result.get(k)
        if v is not None and not isinstance(v, list):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.{k} is present "
                  f"but not an array-or-null (got {type(v).__name__}): {raw[:300]}")
            return

    print(f"observed summary: {json.dumps(summary)}")
    print(f"observed running/queued/completed/idle_segments presence: "
          f"running={'present' if 'running' in result else 'absent'}, "
          f"queued={'present' if 'queued' in result else 'absent'}, "
          f"completed={'present' if 'completed' in result else 'absent'}, "
          f"idle_segments={'present' if 'idle_segments' in result else 'absent'}")
    print("OK: live collection -> 200 with result object + summary aggregation + typed groups")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
