#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_batch_missing_005
# strategy: behavioral-boundary attack (the missing-collection leg of the
#           200/404 promise, sampled across three different op kinds —
#           G9: the disposition must be consistent across op faces)
# endpoint: points+batch
# constraint_ids: qdrant_behavioral_points_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/batch-update
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — a server that resolves
#            the op payload before resolving the collection may return an
#            op-shaped error, or worse 200-apply into a phantom collection)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral-boundary x qdrant_behavioral_points_batch_001 — the
  assertion pins BOTH legs of the points+batch face: "returns HTTP 200
  with one result entry per operation; 404 when the collection is
  missing". This script attacks the 404 leg with three different valid
  op kinds against a collection that does NOT exist (unique per run):
    M1 upsert-op batch        -> exactly 404
    M2 delete-op batch        -> exactly 404
    M3 set_payload-op batch   -> exactly 404
  and pins the promise with Control C: the IDENTICAL M1 upsert-op batch
  against an EXISTING collection -> 200 with 1 result entry. Any 2xx on
  M1-M3 is a phantom success (the server claims to have applied
  operations to a collection that does not exist); divergent dispositions
  across M1-M3 (e.g. 404 vs 400) are recorded as a G9 inconsistency
  signal for the judge (the leg is collection-existence-driven, not
  op-kind-driven).
  [chunk_points+batch coverage: behavioral missing-collection 404 leg x
  qdrant_behavioral_points_batch_001 (this script; order faces in
  boundary_points_batch_order_001/002, operations-type faces in
  boundary_points_batch_ops_003, count faces in
  boundary_points_batch_count_004, nested-domain faces in
  boundary_points_batch_domain_006)]
Oracle: M1/M2/M3 -> HTTP 404 exactly (200/201 = Type1_IllegalSuccess:
  operations reported applied to a nonexistent collection; 5xx with
  /healthz alive = Type3_RuntimeFailure; a non-404 4xx = NOTE + G9
  disposition-consistency check across the three op faces); Control C ->
  200 with result length == 1 (anything else = Type1_IllegalSuccess
  promise face); transport failure -> /healthz liveness re-check then
  SCRIPT_ERROR (constraint qdrant_behavioral_points_batch_001).
Constraint: qdrant_behavioral_points_batch_001 (bare id) — "batch update
  returns HTTP 200 with one result entry per operation; 404 when the
  collection is missing" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+batch        -> POST /collections/{collection_name}/points/batch
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


def main():
    tag = uuid.uuid4().hex[:8]
    ghost = "bpbM5ghost" + tag   # never created
    coll = "bpbM5live" + tag     # control face

    upsert_op = [{"upsert": {"points": [{"id": 1, "vector": V1, "payload": {"n": 1}}]}}]
    faces = [
        ("M1 upsert-op batch on missing collection", upsert_op),
        ("M2 delete-op batch on missing collection", [{"delete": {"points": [1]}}]),
        ("M3 set_payload-op batch on missing collection",
         [{"set_payload": {"payload": {"n": 2}, "points": [1]}}]),
    ]
    seen_statuses = []
    for label, ops in faces:
        s, body, raw = safe_request("POST", f"/collections/{ghost}/points/batch",
                                    json={"operations": ops},
                                    params={"wait": "true"}, timeout=60)
        print(f"\n{label} -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            if not transport_dead(label):
                return
            continue
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                      f"server error {s} with service alive: {raw[:300]}")
            else:
                print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
            return
        if 200 <= s <= 299:
            result = body.get("result") if isinstance(body, dict) else None
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: 2xx "
                  f"(operations reported applied to a NONEXISTENT collection; "
                  f"result={json.dumps(result)[:150] if result is not None else 'absent'}): "
                  f"{raw[:300]}")
            return
        if s == 404:
            print(f"{label}: 404 exactly as promised")
            seen_statuses.append(404)
            continue
        if s in (400, 422):
            print(f"NOTE: {label} returned {s} instead of 404 — non-404 4xx on a "
                  f"missing collection; recorded for the judge (G9 disposition "
                  f"consistency)")
            seen_statuses.append(s)
            continue
        print(f"NOTE: {label} returned unexpected status {s}; recorded for the judge")
        seen_statuses.append(s)

    if len(set(seen_statuses)) > 1:
        print(f"NOTE: G9 inconsistent disposition across op faces on the same "
              f"missing collection: {seen_statuses} (the 404 leg is collection-"
              f"existence-driven, not op-kind-driven)")

    # ---- Control C: identical upsert-op batch on an EXISTING collection ----
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"control setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        s, body, raw = safe_request("POST", f"/collections/{coll}/points/batch",
                                    json={"operations": upsert_op},
                                    params={"wait": "true"}, timeout=60)
        print(f"\nControl C upsert-op batch on EXISTING collection -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            transport_dead("control C")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — control C: "
                      f"server error {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — control C 5xx and healthz down")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — control C: the "
                  f"IDENTICAL batch that 404'd on the ghost collection returned "
                  f"{s} on a live one (promise face broken): {raw[:300]}")
            return
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, list) or len(result) != 1:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — control C: 1 "
                  f"operation but result entries="
                  f"{len(result) if isinstance(result, list) else 'non-array'}: "
                  f"{raw[:300]}")
            return
        print("control C: 200 with 1 result entry (404 leg pinned to collection "
              "existence)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
