#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_batch_domain_006
# strategy: strategy2 type-boundary + strategy3 dimension-mismatch attack on
#           NESTED fields inside batch operations (PointId domain, required
#           selector/payload branches, vector dimension vs collection schema)
# endpoint: points+batch
# constraint_ids: qdrant_behavioral_points_batch_001, qdrant_state_points_batch_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-01 (Parameter Type Coercion Trust — nested PointId and
#            selector fields inside UpdateOperation variants are trusted to
#            be validated; the PointId domain is uint64 | UUID string only)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2/3 nested-domain x points+batch — PointId (oneOf 64-bit
  unsigned integer | UUID string, per contract data_types) and the nested
  required branches of UpdateOperation variants (request_required_paths:
  set_payload.payload, selector points|filter), plus the dimension face
  (vector length vs the collection's declared size). Faces on a LIVE
  dim-4 collection (points 1 and 30 are the only ids ever created):
    N1 upsert op with id -1        (negative int — not uint64, not UUID)
    N2 upsert op with id "1"       (numeric string — string branch is
        UUID-only; a 200 that lands it as numeric id 1 is out-of-domain
        coercion with stored evidence)
    N3 upsert op with id true      (boolean PointId)
    N4 set_payload with payload null (required branch missing)
    N5 set_payload with points null and no filter (selector absent)
    N6 upsert op with a 2-dim vector into the dim-4 collection
        (dimension-mismatch inside a batch op)
    Control C: valid upsert op id 30 dim-4 -> 200 with 1 result entry and
        point 30 durable on readback (pins the promise).
  [chunk_points+batch coverage: strategy2 nested-domain + strategy3
  dimension x qdrant_behavioral_points_batch_001 +
  qdrant_state_points_batch_001 (this script; order faces in
  boundary_points_batch_order_001/002, operations-field type faces in
  boundary_points_batch_ops_003, count faces in
  boundary_points_batch_count_004, 404 leg in
  boundary_points_batch_missing_005)]
Oracle: N1/N3/N4/N5 -> 400/422 clean (2xx = Type1_IllegalSuccess:
  out-of-domain nested value accepted; 5xx with /healthz alive =
  Type3_RuntimeFailure). N2 -> 4xx clean; 200 = readback-verified:
  numeric point 1 created by the string id = Type1_IllegalSuccess,
  nothing stored = leniency NOTE for the judge (mirrors the R32
  point+get string-branch posture). N6 -> 4xx clean OR 200 with a
  non-success per-op result entry; 200 claiming success
  (result[0].status completed/acknowledged) with point 20 absent =
  Type4_StateLogicViolation (report/effect mismatch); point 20 stored
  with a 2-dim vector = Type1_IllegalSuccess (collection schema
  violated); 5xx = Type3. Control C -> 200, 1 entry, point 30 durable;
  transport failure -> /healthz liveness re-check then SCRIPT_ERROR
  (constraints qdrant_behavioral_points_batch_001 /
  qdrant_state_points_batch_001).
Constraint: qdrant_behavioral_points_batch_001 (bare id) — "batch update
  returns HTTP 200 with one result entry per operation; 404 when the
  collection is missing" (evidence_tier: explicit; level: endpoint);
  qdrant_state_points_batch_001 (bare id) — the 8 batchable op variants,
  applied sequentially, each reporting its own result (evidence_tier:
  explicit); PointId (ExtendedPointId) — oneOf uint64 | UUID string

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+batch        -> POST /collections/{collection_name}/points/batch
  points+get          -> POST /collections/{collection_name}/points
  points+upsert       -> PUT  /collections/{collection_name}/points
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


def readback(coll, pid):
    """Readback instrument: POST points+get; returns (record_or_None, status, raw)."""
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points",
        json={"ids": [pid], "with_payload": True, "with_vector": True}, timeout=60)
    if s == 200 and isinstance(body, dict) and isinstance(body.get("result"), list) \
            and body["result"]:
        return body["result"][0], s, raw
    return None, s, raw


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpbD6" + tag

    # Arrange: own dim-4 collection; point 1 pre-exists (N2 coercion target)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # negative-domain faces: clean = 4xx
        faces = [
            ("N1 id -1 (negative int)", [{"upsert": {"points": [
                {"id": -1, "vector": V1, "payload": {"n": 1}}]}}]),
            ("N3 id true (boolean)", [{"upsert": {"points": [
                {"id": True, "vector": V1, "payload": {"n": 1}}]}}]),
            ("N4 set_payload payload null", [{"set_payload": {
                "payload": None, "points": [1]}}]),
            ("N5 set_payload selector absent (points null, no filter)",
             [{"set_payload": {"payload": {"n": 2}, "points": None}}]),
        ]
        for label, ops in faces:
            s, body, raw = safe_request("POST", f"/collections/{coll}/points/batch",
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
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"out-of-domain nested value accepted with {s} (result="
                      f"{json.dumps(result)[:150] if result is not None else 'absent'}): "
                      f"{raw[:300]}")
                return
            if s in (400, 422):
                print(f"{label}: {s} clean domain rejection (error-naming NOTE only, R29)")
                continue
            print(f"NOTE: {label} returned unexpected status {s}; recorded for the judge")

        # ---- N2: numeric-string id (string branch is UUID-only) ----
        s, body, raw = safe_request("POST", f"/collections/{coll}/points/batch",
                                    json={"operations": [{"upsert": {"points": [
                                        {"id": "1", "vector": V1,
                                         "payload": {"via": "string-id"}}]}}]},
                                    params={"wait": "true"}, timeout=60)
        print(f"\nN2 id \"1\" (numeric string) -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            if not transport_dead("N2 numeric-string id"):
                return
        elif 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — N2: server "
                      f"error {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — N2 5xx and healthz down")
            return
        elif 200 <= s <= 299:
            rec, rs, rraw = readback(coll, 1)
            if rs == -1:
                if not transport_dead("N2 readback"):
                    return
            elif rec is not None and rec.get("payload", {}).get("via") == "string-id":
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — N2: numeric "
                      f"string id coerced to numeric point 1 and STORED "
                      f"(PointId string branch is UUID-only): {rraw[:200]}")
                return
            else:
                print("NOTE: N2 accepted with 2xx but the string id did not land as "
                      "numeric point 1 — leniency recorded for the judge (R32 "
                      "string-branch posture)")
        elif s in (400, 422):
            print("N2: 4xx clean domain rejection (string branch is UUID-only)")
        else:
            print(f"NOTE: N2 returned unexpected status {s}; recorded for the judge")

        # ---- N6: dimension mismatch inside a batch op (2-dim into dim-4) ----
        s, body, raw = safe_request("POST", f"/collections/{coll}/points/batch",
                                    json={"operations": [{"upsert": {"points": [
                                        {"id": 20, "vector": [0.1, 0.2],
                                         "payload": {"dim": 2}}]}}]},
                                    params={"wait": "true"}, timeout=60)
        print(f"\nN6 2-dim vector into dim-4 collection -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            if not transport_dead("N6 dimension mismatch"):
                return
        elif 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — N6: server "
                      f"error {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — N6 5xx and healthz down")
            return
        elif 200 <= s <= 299:
            result = body.get("result") if isinstance(body, dict) else None
            op_status = None
            if isinstance(result, list) and result and isinstance(result[0], dict):
                op_status = result[0].get("status")
            print(f"N6: 200 with per-op status={op_status!r}")
            rec, rs, rraw = readback(coll, 20)
            if rs == -1:
                if not transport_dead("N6 readback"):
                    return
            vec = rec.get("vector") if isinstance(rec, dict) else None
            if rec is not None and isinstance(vec, list) and len(vec) == 2:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — N6: 2-dim "
                      f"vector STORED in the dim-4 collection (schema violated): "
                      f"{rraw[:200]}")
                return
            if op_status in ("completed", "acknowledged") and rec is None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — N6: "
                      f"batch 200 with per-op status {op_status!r} but point 20 "
                      f"absent on readback (report/effect mismatch): {rraw[:200]}")
                return
            if rec is None:
                print("N6: 2-dim vector not stored (per-op failure reported or "
                      "silently dropped) — recorded for the judge")
            else:
                print(f"NOTE: N6 point 20 present with vector "
                      f"{json.dumps(vec)[:120]}; recorded for the judge")
        elif s in (400, 422):
            print("N6: 4xx clean dimension rejection")
        else:
            print(f"NOTE: N6 returned unexpected status {s}; recorded for the judge")

        # ---- Control C: valid upsert -> 200, 1 entry, durable ----
        s, body, raw = safe_request("POST", f"/collections/{coll}/points/batch",
                                    json={"operations": [{"upsert": {"points": [
                                        {"id": 30, "vector": V1,
                                         "payload": {"ok": 1}}]}}]},
                                    params={"wait": "true"}, timeout=60)
        print(f"\nControl C valid upsert op -> status={s}")
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
                  f"batch rejected with {s}: {raw[:300]}")
            return
        else:
            result = body.get("result") if isinstance(body, dict) else None
            if not isinstance(result, list) or len(result) != 1:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — control C: 1 "
                      f"operation but result entries="
                      f"{len(result) if isinstance(result, list) else 'non-array'}: "
                      f"{raw[:300]}")
                return
            rec, rs, rraw = readback(coll, 30)
            if rs == -1:
                if not transport_dead("control C readback"):
                    return
            if rec is None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — control "
                      f"C: 200 reported but point 30 absent on readback: "
                      f"{rraw[:200]}")
                return
            print("control C: 200, 1 result entry, point 30 durable")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
