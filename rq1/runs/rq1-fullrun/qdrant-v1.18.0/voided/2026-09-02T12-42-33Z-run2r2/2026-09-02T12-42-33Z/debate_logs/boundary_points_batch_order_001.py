#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_batch_order_001
# strategy: strategy1 boundary-value attack (sequential-order mutation on a
#           same-point op chain — G6: the mutation point is maximal-order-
#           discriminative because every adjacent op pair in the chain
#           produces a DIFFERENT observable payload if swapped)
# endpoint: points+batch
# constraint_ids: qdrant_state_points_batch_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-04 (Boundary Default Optimism — the doc promises sequential
#            application; a server that coalesces or reorders same-point ops
#            inside one batch silently breaks the final state)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 order-mutation x qdrant_state_points_batch_001 — the
  contract promises "batch operations are applied sequentially in the
  order given; each operation reports its own result". One batch of 7
  operations on two fresh points (all payload-family op kinds: upsert,
  set_payload, overwrite_payload, delete_payload, clear_payload), in a
  chain engineered so that ANY reordering changes the observable final
  payload:
    op1 upsert      p1 payload {"a":1,"b":1}
    op2 upsert      p2 payload {"x":9}
    op3 set_payload {"a":2} on [1]        -> p1 {"a":2,"b":1}
    op4 overwrite_payload {"c":3} on [1]  -> p1 {"c":3}   (a,b wiped)
    op5 set_payload {"a":4} on [1]        -> p1 {"c":3,"a":4}
    op6 delete_payload keys=["c"] on [1]  -> p1 {"a":4}
    op7 clear_payload on [2]              -> p2 {}
  Sequential-application closure: p1 payload == exactly {"a":4} and
  p2 payload == exactly {}. Swapping op3/op4 leaves a==2; applying op5
  before op4 wipes a; applying op6 before op4 resurrects c; every
  permutation of the chain yields a payload != {"a":4} (checked by
  construction: only the given order deletes "c" after re-creating "a").
  Envelope leg: 200 must carry result array with exactly 7 entries
  ("each operation reports its own result" — result[]: object with
  status: string per the published OpenAPI response_shape).
  [chunk_points+batch coverage: strategy1 order-mutation x
  qdrant_state_points_batch_001 payload-chain face (this script; mirrored
  existence/vector chains in boundary_points_batch_order_002, type faces
  in boundary_points_batch_ops_003, count faces in
  boundary_points_batch_count_004, 404 leg in
  boundary_points_batch_missing_005, nested-domain faces in
  boundary_points_batch_domain_006)]
Oracle: batch -> HTTP 200 with result array length == 7 (each entry an
  object; a string status field per response_shape result[].status);
  readback p1 payload == {"a":4} exactly and p2 payload == {} exactly
  (persistence judged via point readback after batch, wait=true).
  200 with a different final payload = Type4_StateLogicViolation
  (sequential-order promise broken); 200 with len(result) != 7 =
  Type1_IllegalSuccess (per-op result promise broken); 4xx/5xx on this
  all-valid batch = promise face broken (5xx with /healthz alive =
  Type3_RuntimeFailure; 4xx = Type1_IllegalSuccess: valid batchable ops
  rejected); transport failure -> /healthz liveness re-check then
  SCRIPT_ERROR (constraint qdrant_state_points_batch_001).
Constraint: qdrant_state_points_batch_001 (bare id) — "batch operations
  are applied sequentially in the order given; each operation reports
  its own result" (evidence_tier: explicit; level: endpoint)

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


def readback_points(coll, ids):
    """Readback instrument: POST points+get with payload+vector, returns
    {id: record} for the ids actually present (envelope result.<field>)."""
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points",
        json={"ids": ids, "with_payload": True, "with_vector": True}, timeout=60)
    if s == -1:
        return None, s, raw
    if s != 200 or not isinstance(body, dict) or not isinstance(body.get("result"), list):
        return None, s, raw
    got = {}
    for rec in body["result"]:
        if isinstance(rec, dict) and "id" in rec:
            try:
                got[int(rec["id"])] = rec
            except (TypeError, ValueError):
                got[str(rec["id"])] = rec
    return got, s, raw


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpbO1" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        operations = [
            {"upsert": {"points": [{"id": 1, "vector": V1, "payload": {"a": 1, "b": 1}}]}},
            {"upsert": {"points": [{"id": 2, "vector": V1, "payload": {"x": 9}}]}},
            {"set_payload": {"payload": {"a": 2}, "points": [1]}},
            {"overwrite_payload": {"payload": {"c": 3}, "points": [1]}},
            {"set_payload": {"payload": {"a": 4}, "points": [1]}},
            {"delete_payload": {"keys": ["c"], "points": [1]}},
            {"clear_payload": {"points": [2]}},
        ]
        # Act: one batch, wait=true so readback is deterministic
        s, body, raw = safe_request("POST", f"/collections/{coll}/points/batch",
                                    json={"operations": operations},
                                    params={"wait": "true"}, timeout=120)
        print(f"7-op order chain -> status={s}")
        print(f"raw: {raw[:600]}")
        if s == -1:
            transport_dead("7-op order chain")
            return
        if 500 <= s <= 599:
            alive, hs, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — all-valid 7-op "
                      f"batch returned {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — batch 5xx and healthz down")
            return
        if s in (400, 404, 422):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — batch of 8 "
                  f"doc-enumerated batchable ops rejected with {s}: {raw[:300]}")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s}; no defect conclusion")
            return

        # Envelope leg: one result entry per operation
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, list):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — 200 but result is "
                  f"not an array (response_shape: result array): {raw[:300]}")
            return
        if len(result) != len(operations):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {len(operations)} "
                  f"operations but {len(result)} result entries ('each operation "
                  f"reports its own result' broken): {raw[:300]}")
            return
        for i, entry in enumerate(result):
            if not isinstance(entry, dict) or not isinstance(entry.get("status"), str):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — result[{i}] "
                      f"missing string status (response_shape result[].status): "
                      f"{json.dumps(entry)[:200]}")
                return
        print(f"envelope OK: {len(result)} result entries, each with string status "
              f"(statuses: {[e.get('status') for e in result]})")

        # Sequential-application leg: final state readback
        got, rs, rraw = readback_points(coll, [1, 2])
        if got is None:
            if rs == -1 and not transport_dead("readback points+get"):
                return
            print(f"VERDICT: SCRIPT_ERROR — readback failed status={rs}: {rraw[:300]}")
            return
        p1 = got.get(1)
        p2 = got.get(2)
        if p1 is None or p2 is None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — after 200 "
                  f"batch, readback missing points (p1={'yes' if p1 else 'NO'}, "
                  f"p2={'yes' if p2 else 'NO'}): {rraw[:300]}")
            return
        p1_payload = p1.get("payload")
        p2_payload = p2.get("payload")
        print(f"readback p1.payload={json.dumps(p1_payload)} (expected {{\"a\": 4}})")
        print(f"readback p2.payload={json.dumps(p2_payload)} (expected {{}})")
        if p1_payload != {"a": 4}:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — sequential-"
                  f"order promise broken: 7-op chain applied in the given order must "
                  f"end with p1.payload == {{\"a\": 4}}, got {json.dumps(p1_payload)} "
                  f"(op reordering/coalescing observable): {rraw[:200]}")
            return
        if p2_payload != {}:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — clear_payload "
                  f"op7 final effect wrong: p2.payload must be {{}}, got "
                  f"{json.dumps(p2_payload)}: {rraw[:200]}")
            return
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
