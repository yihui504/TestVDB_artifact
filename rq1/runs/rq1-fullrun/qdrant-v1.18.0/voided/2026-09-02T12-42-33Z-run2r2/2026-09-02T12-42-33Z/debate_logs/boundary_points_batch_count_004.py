#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_batch_count_004
# strategy: strategy1 boundary-value attack (degenerate operation-count
#           boundary against the "one result entry per operation" promise:
#           0, 1 and 3 identical operations)
# endpoint: points+batch
# constraint_ids: qdrant_behavioral_points_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/batch-update
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the degenerate empty batch
#            and duplicate identical ops are the count boundaries the
#            per-op-result loop is least likely to handle carefully)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 degenerate-count x qdrant_behavioral_points_batch_001 —
  the promise "HTTP 200 with one result entry per operation" is a
  count-coupling between request operations and response result. Faces
  on a LIVE collection:
    F1 empty operations [] — 0 ops must yield 0 result entries: clean
       outcomes are 200 with result == [] (consistent extrapolation of
       one-entry-per-op) or a 400/422 clean rejection of an empty batch;
       200 with a NON-empty or non-array result = count coupling broken;
       5xx = Type3 (an empty batch must not crash).
    F2 single upsert op — 200 with EXACTLY 1 result entry (object with a
       string status per published OpenAPI response_shape result[].status)
       and the point durable on readback (wait=true).
    F3 three IDENTICAL set_payload ops on the same point — 200 with
       EXACTLY 3 result entries ("each operation reports its own result"
       also for duplicates — deduplicating the request silently breaks
       the count promise); final payload == the op's payload (identical
       ops are idempotent), readback-verified.
  [chunk_points+batch coverage: strategy1 degenerate-count x
  qdrant_behavioral_points_batch_001 (this script; order faces in
  boundary_points_batch_order_001/002, operations-type faces in
  boundary_points_batch_ops_003, 404 leg in
  boundary_points_batch_missing_005, nested-domain faces in
  boundary_points_batch_domain_006)]
Oracle: F1 -> 200 with result == [] or 400/422 clean; 200 with non-array
  result or >0 entries = Type1_IllegalSuccess; 5xx with /healthz alive =
  Type3_RuntimeFailure. F2 -> 200, len(result) == 1, entry object with
  string status, point present on readback. F3 -> 200, len(result) == 3,
  payload == {"n": 7} on readback; len(result) != 3 = Type1_IllegalSuccess
  (count coupling broken); wrong payload = Type4_StateLogicViolation;
  4xx on F2/F3 (all-valid batches) = Type1_IllegalSuccess; transport
  failure -> /healthz liveness re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_batch_001).
Constraint: qdrant_behavioral_points_batch_001 (bare id) — "batch update
  returns HTTP 200 with one result entry per operation; 404 when the
  collection is missing" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+batch        -> POST /collections/{collection_name}/points/batch
  points+get          -> POST /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
  (wait is a query parameter on the batch face — passed via params=)
"""

import json
import os
import sys
import uuid
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap: three-layer fallback (env -> upward walk -> contract target) ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    _root = Path(__file__).resolve()
    for _p in (_root, *list(_root.parents)):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or TARGET != "qdrant":
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)

DIM = 4
V1 = [0.1, 0.2, 0.3, 0.4]


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/ordering/timeout) via params= — never stuffed into the body.
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, headers=headers,
            timeout=timeout, params=params,
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
    """Inline liveness probe on the lightweight healthz face."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def transport_dead(where):
    """Transport-branch liveness re-check (lightweight healthz face only)."""
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return False


def batch_status_result(operations):
    """POST one batch, shared transport/5xx handling.
    Returns (status, body, raw) with transport already escalated."""
    s, body, raw = safe_request("POST", f"/collections/{coll}/points/batch",
                                json={"operations": operations},
                                params={"wait": "true"}, timeout=120)
    return s, body, raw


def readback_payload(coll, pid):
    """Readback instrument: POST points+get; returns (payload, status, raw)."""
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points",
        json={"ids": [pid], "with_payload": True, "with_vector": False}, timeout=60)
    if s == 200 and isinstance(body, dict) and isinstance(body.get("result"), list) \
            and body["result"]:
        return body["result"][0].get("payload"), s, raw
    return None, s, raw


coll = ""


def main():
    global coll
    tag = uuid.uuid4().hex[:8]
    coll = "bpbC4" + tag

    # Arrange: own collection (points arrive via the faces themselves)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # ---- F1: empty operations [] (0 ops -> 0 result entries) ----
        s, body, raw = batch_status_result([])
        print(f"F1 empty operations [] -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            transport_dead("F1 empty batch")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F1: empty "
                      f"operations crashed the batch face with {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F1 5xx and healthz down")
            return
        if 200 <= s <= 299:
            result = body.get("result") if isinstance(body, dict) else None
            if not isinstance(result, list):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F1: 200 but "
                      f"result is not an array (response_shape: result array): "
                      f"{raw[:300]}")
                return
            if len(result) != 0:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F1: 0 "
                      f"operations but {len(result)} result entries (one-entry-"
                      f"per-op count coupling broken): {raw[:300]}")
                return
            print("F1: 200 with result == [] (consistent: 0 ops -> 0 entries)")
        elif s in (400, 422):
            print(f"F1: {s} clean rejection of the empty batch (defensible posture)")
        else:
            print(f"NOTE: F1 returned unexpected status {s}; recorded for the judge")

        # ---- F2: single upsert op -> exactly 1 result entry + durable point ----
        s, body, raw = batch_status_result(
            [{"upsert": {"points": [{"id": 1, "vector": V1, "payload": {"n": 1}}]}}])
        print(f"\nF2 single upsert op -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            transport_dead("F2 single-op batch")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F2: server "
                      f"error {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F2 5xx and healthz down")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F2: valid single-op "
                  f"batch rejected with {s}: {raw[:300]}")
            return
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, list) or len(result) != 1:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F2: 1 operation "
                  f"but result entries="
                  f"{len(result) if isinstance(result, list) else 'non-array'}: "
                  f"{raw[:300]}")
            return
        entry = result[0]
        if not isinstance(entry, dict) or not isinstance(entry.get("status"), str):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F2: result[0] "
                  f"missing string status (response_shape result[].status): "
                  f"{json.dumps(entry)[:200]}")
            return
        payload, rs, rraw = readback_payload(coll, 1)
        if rs == -1:
            if not transport_dead("F2 readback"):
                return
        elif payload is None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F2: 200 "
                  f"reported but point 1 absent on readback (status={rs}): "
                  f"{rraw[:300]}")
            return
        else:
            print(f"F2 readback payload={json.dumps(payload)} (durable)")

        # ---- F3: three IDENTICAL set_payload ops -> exactly 3 result entries ----
        dup_op = {"set_payload": {"payload": {"n": 7}, "points": [1]}}
        s, body, raw = batch_status_result([dup_op, dup_op, dup_op])
        print(f"\nF3 three identical set_payload ops -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            transport_dead("F3 duplicate-op batch")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F3: server "
                      f"error {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F3 5xx and healthz down")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F3: valid "
                  f"duplicate-op batch rejected with {s}: {raw[:300]}")
            return
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, list) or len(result) != 3:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F3: 3 operations "
                  f"but result entries="
                  f"{len(result) if isinstance(result, list) else 'non-array'} "
                  f"(duplicates must each report their own result): {raw[:300]}")
            return
        for i, entry in enumerate(result):
            if not isinstance(entry, dict) or not isinstance(entry.get("status"), str):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F3: "
                      f"result[{i}] missing string status: "
                      f"{json.dumps(entry)[:200]}")
                return
        payload, rs, rraw = readback_payload(coll, 1)
        if rs == -1:
            if not transport_dead("F3 readback"):
                return
        elif payload != {"n": 7}:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F3: "
                  f"identical ops are idempotent; payload must be "
                  f"{{\"n\": 7}}, got {json.dumps(payload)}: {rraw[:200]}")
            return
        else:
            print(f"F3 readback payload={json.dumps(payload)} (idempotent closure OK)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
