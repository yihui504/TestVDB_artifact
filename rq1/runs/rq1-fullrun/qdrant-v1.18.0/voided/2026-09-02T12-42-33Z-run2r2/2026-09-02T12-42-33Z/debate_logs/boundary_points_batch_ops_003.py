#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_batch_ops_003
# strategy: strategy2 type-boundary attack on the operations field (the
#           UpdateOperation domain: array of exactly-one-key op objects
#           from the 8 batchable variants)
# endpoint: points+batch
# constraint_ids: qdrant_behavioral_points_batch_001, qdrant_state_points_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/batch-update
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde enum decoding of
#            UpdateOperation is trusted; null/unknown/multi-key variant
#            forms must be rejected, not coerced)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x points+batch operations field — the
  contract types operations as array[UpdateOperation] with the 8
  batchable variants (upsert/update_vectors/delete_vectors/set_payload/
  overwrite_payload/delete_payload/clear_payload/delete_points) and the
  published OpenAPI declares operations required. Faces (all against a
  LIVE collection holding point 1):
    F1 operations missing (body {})
    F2 operations: null
    F3 operations: {} (object, not array)
    F4 operations: "upsert" (string)
    F5 operations: [{}] (op object with no variant key)
    F6 operations: [{"frobnicate": {...}}] (unknown variant key)
    F7 operations: [{"upsert": {...}, "delete": {...}}] (two variant keys
       in one op — a oneOf/externally-tagged enum must reject ambiguity)
    F8 operations: [{"upsert": null}] (null variant value)
    F9 operations: [{"upsert": {"points": "not-an-array"}}] (nested
       field type confusion inside a known variant)
    Control C: [{"clear_payload": {"points": [1]}}] -> must be 200 with
       exactly 1 result entry (pins the promise so the 4xx faces above
       are domain rejections, not wholesale laziness)
  [chunk_points+batch coverage: strategy2 type-boundary x
  qdrant_behavioral_points_batch_001 + qdrant_state_points_batch_001
  operations-field faces (this script; order faces in
  boundary_points_batch_order_001/002, count faces in
  boundary_points_batch_count_004, 404 leg in
  boundary_points_batch_missing_005, nested-domain faces in
  boundary_points_batch_domain_006)]
Oracle: F1-F9 -> 400/422 clean domain rejection (error-naming quality is
  NOTE only per R29); 2xx on any F1-F9 = Type1_IllegalSuccess
  (out-of-domain operations accepted — for F7 additionally ambiguous:
  which variant was applied; for F2/F3/F4 the per-op result promise
  cannot hold); 5xx with /healthz alive = Type3_RuntimeFailure; Control
  C -> 200 with result length == 1 and point 1 payload cleared (anything
  else = Type1_IllegalSuccess promise face); transport failure ->
  /healthz liveness re-check then SCRIPT_ERROR (constraints
  qdrant_behavioral_points_batch_001 / qdrant_state_points_batch_001).
Constraint: qdrant_behavioral_points_batch_001 (bare id) — "batch update
  returns HTTP 200 with one result entry per operation; 404 when the
  collection is missing" (evidence_tier: explicit; level: endpoint);
  qdrant_state_points_batch_001 (bare id) — batchable ops are the 8
  enumerated variants, applied sequentially, each reporting its own
  result (evidence_tier: explicit)

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


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpbT3" + tag

    # Arrange: own collection with point 1 present (targets for the faces)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": [{"id": 1, "vector": V1,
                                                   "payload": {"seed": 1}}]},
                                 params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        upsert_body = {"points": [{"id": 2, "vector": V1, "payload": {"k": 1}}]}
        faces = [
            ("F1 operations missing", {}),
            ("F2 operations null", {"operations": None}),
            ("F3 operations object", {"operations": {}}),
            ("F4 operations string", {"operations": "upsert"}),
            ("F5 op object empty", {"operations": [{}]}),
            ("F6 unknown variant key", {"operations": [
                {"frobnicate": {"points": [1]}}]}),
            ("F7 two variant keys in one op", {"operations": [
                {"upsert": upsert_body, "delete": {"points": [1]}}]}),
            ("F8 null variant value", {"operations": [{"upsert": None}]}),
            ("F9 nested field type confusion", {"operations": [
                {"upsert": {"points": "not-an-array"}}]}),
        ]
        for label, payload in faces:
            s, body, raw = safe_request("POST", f"/collections/{coll}/points/batch",
                                        json=payload, params={"wait": "true"},
                                        timeout=60)
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
                extra = ""
                if "F7" in label:
                    # ambiguity observation: which variant won?
                    gs, _, graw = safe_request(
                        "GET", f"/collections/{coll}/points/1", timeout=60)
                    extra = (f"; point+get p1 -> {gs} "
                             f"({'upsert-face intact' if gs == 200 else 'delete-face won'})")
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"out-of-domain operations accepted with {s} (result="
                      f"{json.dumps(result)[:150] if result is not None else 'absent'}"
                      f"){extra}")
                return
            if s in (400, 422):
                names_op = "operations" in raw.lower() or "operation" in raw.lower()
                print(f"{label}: {s} clean domain rejection "
                      f"(error names the op field: {names_op} — NOTE only, R29)")
                continue
            print(f"NOTE: {label} returned unexpected status {s}; recorded for the judge")

        # ---- Control C: single valid clear_payload op -> 200 with 1 entry ----
        s, body, raw = safe_request("POST", f"/collections/{coll}/points/batch",
                                    json={"operations": [{"clear_payload": {"points": [1]}}]},
                                    params={"wait": "true"}, timeout=60)
        print(f"\nControl C clear_payload -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            if not transport_dead("control C"):
                return
        elif 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — control C: "
                      f"server error {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — control C 5xx and healthz down")
            return
        elif not (200 <= s <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — control C: valid "
                  f"single-op batch rejected with {s}: {raw[:300]}")
            return
        else:
            result = body.get("result") if isinstance(body, dict) else None
            if not isinstance(result, list) or len(result) != 1:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — control C: 1 "
                      f"operation but result entries="
                      f"{len(result) if isinstance(result, list) else 'non-array'}: "
                      f"{raw[:300]}")
                return
            gs, gbody, graw = safe_request(
                "POST", f"/collections/{coll}/points",
                json={"ids": [1], "with_payload": True, "with_vector": False},
                timeout=60)
            payload_now = None
            if gs == 200 and isinstance(gbody, dict) \
                    and isinstance(gbody.get("result"), list) and gbody["result"]:
                payload_now = gbody["result"][0].get("payload")
            print(f"control C readback p1 payload={json.dumps(payload_now)} "
                  f"(expected {{}})")
            if payload_now != {}:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — control C: "
                      f"clear_payload reported 200 but payload is "
                      f"{json.dumps(payload_now)}: {graw[:200]}")
                return
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
