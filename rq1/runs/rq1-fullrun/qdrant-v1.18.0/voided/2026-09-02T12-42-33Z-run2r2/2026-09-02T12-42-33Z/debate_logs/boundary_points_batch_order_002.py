#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_batch_order_002
# strategy: strategy1 boundary-value attack (mirrored order-mutation on
#           existence and vector state — G6: delete-vs-upsert is the sharpest
#           mutation point because any global reordering (deletes-first or
#           upserts-first coalescing) flips exactly one of the two mirrored
#           batches; update_vectors/delete_vectors close the remaining
#           batchable-op kinds)
# endpoint: points+batch
# constraint_ids: qdrant_state_points_batch_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-04 (Boundary Default Optimism — sequential application is a
#            doc promise; bulk-apply implementations that group deletes and
#            upserts violate it silently)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 order-mutation x qdrant_state_points_batch_001 — mirrored
  existence chains plus the two vector-family op kinds, all inside
  points+batch (ops: delete_points, upsert, update_vectors, delete_vectors
  — together with boundary_points_batch_order_001 this closes all 8
  doc-enumerated batchable op kinds):
    S (3 ops): upsert p8/p9 payload {"stage":"first"}, upsert p10 {}
    X (2 ops): [delete p8, upsert p8 {"stage":"reborn"}]
               -> sequential final: p8 EXISTS with {"stage":"reborn"}
    Y (2 ops): [upsert p9 {"stage":"second"}, delete p9]
               -> sequential final: p9 GONE (point+get 404)
    Z (1 op) : [update_vectors p10 -> v2]
               -> p10 vector direction == normalize(v2)
    W (2 ops): [upsert p11 {"stage":"w"} v1, delete_vectors p11 vector=[]]
               -> p11 EXISTS with payload {"stage":"w"} and vector removed
  X and Y are exact mirrors: same op kinds, opposite order, opposite
  outcome. A server that globally reorders (applies all deletes first, or
  all upserts first) must get exactly one of them wrong — the readback
  discriminates any non-sequential application.
  [chunk_points+batch coverage: strategy1 order-mutation x
  qdrant_state_points_batch_001 existence+vector faces (this script;
  payload chain in boundary_points_batch_order_001, type faces in
  boundary_points_batch_ops_003, count faces in
  boundary_points_batch_count_004, 404 leg in
  boundary_points_batch_missing_005, nested-domain faces in
  boundary_points_batch_domain_006)]
Oracle: batches S/X/Y/Z -> 200 with result length == op count; X -> p8
  exists with payload exactly {"stage":"reborn"}; Y -> point+get p9
  returns 404; Z -> readback p10 vector ~ normalize(v2) (cosine-safe
  compare, R27 readback-vs-baseline discipline); W -> 200 with p11
  present, payload {"stage":"w"}, vector null/absent (422 on W = NOTE
  clean — delete_vectors semantics for the unnamed vector are not pinned
  by this chunk's assertions). Any flipped final state =
  Type4_StateLogicViolation; 200 with wrong result count =
  Type1_IllegalSuccess; 5xx with /healthz alive = Type3_RuntimeFailure;
  4xx on all-valid batches = Type1_IllegalSuccess; transport failure ->
  /healthz liveness re-check then SCRIPT_ERROR (constraint
  qdrant_state_points_batch_001).
Constraint: qdrant_state_points_batch_001 (bare id) — "batch operations
  are applied sequentially in the order given; each operation reports
  its own result" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+batch        -> POST /collections/{collection_name}/points/batch
  points+get          -> POST /collections/{collection_name}/points
  point+get           -> GET  /collections/{collection_name}/points/{id}
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
  (wait is a query parameter on the batch face — passed via params=)
"""

import json
import math
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
V2 = [0.9, 0.1, 0.1, 0.1]


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


def normalize(v):
    """Cosine-safe direction (R27: compare readback against baseline direction)."""
    m = math.sqrt(sum(float(x) * float(x) for x in v)) or 1.0
    return [round(float(x) / m, 4) for x in v]


def batch_call(coll, operations, label):
    """POST one batch; shared adjudication of transport/5xx/count legs.
    Returns (ok, result_list_or_None)."""
    s, body, raw = safe_request("POST", f"/collections/{coll}/points/batch",
                                json={"operations": operations},
                                params={"wait": "true"}, timeout=120)
    print(f"\n{label} ({len(operations)} ops) -> status={s}")
    print(f"raw: {raw[:500]}")
    if s == -1:
        transport_dead(label)
        return False, None
    if 500 <= s <= 599:
        alive, _, _ = healthz_alive()
        if alive:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: server "
                  f"error {s} with service alive: {raw[:300]}")
        else:
            print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
        return False, None
    if not (200 <= s <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: all-valid "
              f"batchable ops rejected with {s}: {raw[:300]}")
        return False, None
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, list) or len(result) != len(operations):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: {len(operations)} "
              f"operations but result entries={len(result) if isinstance(result, list) else 'non-array'} "
              f"('each operation reports its own result' broken): {raw[:300]}")
        return False, None
    print(f"{label}: envelope OK ({len(result)} entries, statuses "
          f"{[e.get('status') for e in result if isinstance(e, dict)]})")
    return True, result


def readback_points(coll, ids):
    """Readback instrument: POST points+get with payload+vector."""
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points",
        json={"ids": ids, "with_payload": True, "with_vector": True}, timeout=60)
    if s == -1 or s != 200 or not isinstance(body, dict) \
            or not isinstance(body.get("result"), list):
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
    coll = "bpbO2" + tag

    # Arrange: own collection
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # ---- Batch S: seed three points (3 ops -> 3 entries) ----
        ops_s = [
            {"upsert": {"points": [{"id": 8, "vector": V1, "payload": {"stage": "first"}}]}},
            {"upsert": {"points": [{"id": 9, "vector": V1, "payload": {"stage": "first"}}]}},
            {"upsert": {"points": [{"id": 10, "vector": V1, "payload": {}}]}},
        ]
        ok, _ = batch_call(coll, ops_s, "batch S seed")
        if not ok:
            return

        # ---- Batch X: [delete p8, upsert p8 reborn] -> p8 must EXIST reborn ----
        ops_x = [
            {"delete": {"points": [8]}},
            {"upsert": {"points": [{"id": 8, "vector": V1, "payload": {"stage": "reborn"}}]}},
        ]
        ok, _ = batch_call(coll, ops_x, "batch X delete-then-upsert")
        if not ok:
            return
        got, rs, rraw = readback_points(coll, [8])
        if got is None:
            if rs == -1 and not transport_dead("readback after X"):
                return
            print(f"VERDICT: SCRIPT_ERROR — readback failed status={rs}: {rraw[:300]}")
            return
        p8 = got.get(8)
        print(f"X readback: p8 present={'yes' if p8 else 'NO'}, "
              f"payload={json.dumps(p8.get('payload')) if p8 else None}")
        if p8 is None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — X "
                  f"[delete,upsert] applied sequentially must end with p8 PRESENT "
                  f"(upsert is last); p8 missing = deletes reordered after upserts")
            return
        if p8.get("payload") != {"stage": "reborn"}:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — X final "
                  f"payload must be {{\"stage\": \"reborn\"}}, got "
                  f"{json.dumps(p8.get('payload'))}: {rraw[:200]}")
            return

        # ---- Batch Y: [upsert p9 second, delete p9] -> p9 must be GONE ----
        ops_y = [
            {"upsert": {"points": [{"id": 9, "vector": V1, "payload": {"stage": "second"}}]}},
            {"delete": {"points": [9]}},
        ]
        ok, _ = batch_call(coll, ops_y, "batch Y upsert-then-delete")
        if not ok:
            return
        gs, _, graw = safe_request("GET", f"/collections/{coll}/points/9", timeout=60)
        print(f"Y readback: point+get p9 -> status={gs} (raw: {graw[:200]})")
        if gs == -1:
            if not transport_dead("point+get p9 after Y"):
                return
        elif gs == 200:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Y "
                  f"[upsert,delete] applied sequentially must end with p9 ABSENT "
                  f"(delete is last); point+get 200 = upserts reordered after deletes")
            return
        elif gs != 404:
            print(f"NOTE: point+get p9 after Y returned {gs}; recorded for the judge")

        # ---- Batch Z: [update_vectors p10 -> v2] -> direction == normalize(v2) ----
        ops_z = [{"update_vectors": {"points": [{"id": 10, "vector": V2}]}}]
        ok, _ = batch_call(coll, ops_z, "batch Z update_vectors")
        if not ok:
            return
        got, rs, rraw = readback_points(coll, [10])
        if got is None:
            if rs == -1 and not transport_dead("readback after Z"):
                return
            print(f"VERDICT: SCRIPT_ERROR — readback failed status={rs}: {rraw[:300]}")
            return
        p10 = got.get(10)
        vec = p10.get("vector") if isinstance(p10, dict) else None
        print(f"Z readback: p10 vector={json.dumps(vec) if vec is not None else None} "
              f"(expected direction {normalize(V2)})")
        if not isinstance(vec, list) or len(vec) != DIM:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — update_vectors "
                  f"left p10 without a {DIM}-dim vector: {json.dumps(vec)[:200]}")
            return
        if normalize(vec) != normalize(V2):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — p10 vector "
                  f"direction {normalize(vec)} != normalize(v2) {normalize(V2)} "
                  f"(update_vectors not applied or wrong vector stored)")
            return

        # ---- Batch W: [upsert p11, delete_vectors p11] -> present, vector removed ----
        ops_w = [
            {"upsert": {"points": [{"id": 11, "vector": V1, "payload": {"stage": "w"}}]}},
            {"delete_vectors": {"points": [11], "vector": []}},
        ]
        s, body, raw = safe_request("POST", f"/collections/{coll}/points/batch",
                                    json={"operations": ops_w},
                                    params={"wait": "true"}, timeout=120)
        print(f"\nbatch W upsert-then-delete_vectors (2 ops) -> status={s}")
        print(f"raw: {raw[:500]}")
        if s == -1:
            if not transport_dead("batch W"):
                return
        elif 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — batch W: "
                      f"server error {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — batch W 5xx and healthz down")
            return
        elif s in (400, 422):
            print("NOTE: batch W rejected with 4xx — delete_vectors with vector=[] "
                  "on the unnamed default vector is not pinned by this chunk's "
                  "assertions; recorded for the judge (clean rejection)")
        elif 200 <= s <= 299:
            result = body.get("result") if isinstance(body, dict) else None
            if not isinstance(result, list) or len(result) != 2:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — batch W: 2 "
                      f"operations but result entries="
                      f"{len(result) if isinstance(result, list) else 'non-array'}: "
                      f"{raw[:300]}")
                return
            got, rs, rraw = readback_points(coll, [11])
            if got is None:
                if rs == -1 and not transport_dead("readback after W"):
                    return
                print(f"VERDICT: SCRIPT_ERROR — readback failed status={rs}: {rraw[:300]}")
                return
            p11 = got.get(11)
            if p11 is None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — W: "
                      f"delete_vectors must remove the vector, not the point; "
                      f"p11 missing: {rraw[:200]}")
                return
            vec = p11.get("vector")
            print(f"W readback: p11 payload={json.dumps(p11.get('payload'))}, "
                  f"vector={json.dumps(vec) if vec is not None else None}")
            if p11.get("payload") != {"stage": "w"}:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — W: p11 "
                      f"payload must stay {{\"stage\": \"w\"}}, got "
                      f"{json.dumps(p11.get('payload'))}")
                return
            if vec not in (None, [], {}):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — W: "
                      f"delete_vectors (last op) must leave p11.vector empty, got "
                      f"{json.dumps(vec)[:200]}")
                return
        else:
            print(f"NOTE: batch W returned unexpected status {s}; recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
