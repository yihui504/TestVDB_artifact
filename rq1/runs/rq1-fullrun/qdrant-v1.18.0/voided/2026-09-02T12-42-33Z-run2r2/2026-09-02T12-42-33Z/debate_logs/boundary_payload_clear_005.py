#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_clear_005
# strategy: behavioral status-face pairing (200-face envelope shape + 404-face)
# endpoint: payload+clear
# constraint_ids: qdrant_behavioral_payload_clear_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/clear-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence — the 404 face's diagnostics are
#            assessed for whether it names the missing collection)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral status-face pairing x qdrant_behavioral_payload_clear_001 —
  the G4 positive/negative pair on the assertion's two declared faces. Face 1
  (positive): clear with points=[1] wait=true on an existing collection with a
  payload-bearing point must return exactly 200, the 200 envelope must match the
  endpoint response_shape grid (result: object; result.status: string;
  result.operation_id: integer|null), and the 200 must couple to actual state —
  scroll readback shows the payload gone (ack-vs-state coupling, R21 lesson:
  judge the state, not the echo). Face 2 (negative): the identical request
  against a well-formed but nonexistent collection name must return exactly 404
  (200 = Type1 acting on a phantom collection; 5xx = Type3; other 4xx = clean
  rejection recorded as NOTE for the judge, R25 disposition ladder), with the
  error body naming the missing collection (Type-2 diagnostics assessment).
  [chunk_payload+clear coverage: behavioral status-face x
  qdrant_behavioral_payload_clear_001, 200-envelope/404 pairing (this script;
  selector type-confusion face in _006)]
Oracle: face 1 — clear {"points":[1],"wait":true} on an existing collection
  returns exactly 200 with a result object whose status field is a string
  (operation_id integer|null when present), and scroll readback afterwards shows
  the point payload empty (200-ack with payload surviving = Type4, envelope
  violating the response_shape grid = Type4); face 2 — the same body against a
  nonexistent collection returns exactly 404 (200-299 = Type1_IllegalSuccess,
  5xx = Type3_RuntimeFailure with /healthz re-check, other 4xx = clean-reject
  NOTE); a 404 body naming neither the collection nor the resource =
  Type2_PoorDiagnostics.
Constraint: qdrant_behavioral_payload_clear_001 (bare id) — "clear_payload
  returns HTTP 200 on valid targets; missing collection returns 404"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  payload+clear       -> POST /collections/{collection_name}/points/payload/clear
  points+upsert       -> PUT  /collections/{collection_name}/points
  points+scroll       -> POST /collections/{collection_name}/points/scroll
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
  (wait is a query parameter on the point-mutation faces — passed via params=)
"""

import json
import os
import sys
import time
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


def safe_request(method, endpoint, json=None, timeout=30, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
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


def transport_dead():
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    print(f"transport failure (healthz status={hs}: {str(hraw)[:200]})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return


def scroll_payloads(coll):
    """id -> payload from points+scroll readback. Returns (map, chan_err)."""
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points/scroll",
        json={"limit": 100, "with_payload": True, "with_vector": False}, timeout=30)
    if s != 200 or not isinstance(body, dict):
        return None, (s, raw)
    res = body.get("result")
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        return None, (s, raw)
    return {p.get("id"): p.get("payload") for p in pts if isinstance(p, dict)}, (s, raw)


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpclr5" + tag
    missing = "bpclr5missing" + tag  # well-formed, never created
    p1_base = {"city": "ams", "n": 1}

    # Arrange: one collection with one payload-bearing point (own data, own cleanup)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request(
        "PUT", f"/collections/{coll}/points",
        json={"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": p1_base}]},
        params={"wait": "true"}, timeout=60)
    if s not in (200, 201):
        print(f"setup upsert failed status={s}: {raw[:300]}")
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # baseline readback
        pls, cerr = scroll_payloads(coll)
        for _ in range(6):
            if pls is not None and pls.get(1) == p1_base:
                break
            time.sleep(0.5)
            pls, cerr = scroll_payloads(coll)
        if pls is None or pls.get(1) != p1_base:
            print(f"baseline readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        print("baseline: point 1 payload visible via scroll")

        # ---- Face 1 (positive): valid target -> exactly 200 + envelope + state ----
        s, body, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload/clear",
            json={"points": [1]}, params={"wait": "true"}, timeout=60)
        print(f"face1 clear on existing collection -> status={s}")
        print(f"raw: {raw[:600]}")

        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on valid-target clear (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — clear on valid "
                  f"target returned {s} (promise: 200)")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — clear on valid "
                  f"target returned {s} (promise: exactly 200)")
            return
        # envelope shape per response_shape grid: result object / result.status string
        # / result.operation_id integer|null
        res = body.get("result") if isinstance(body, dict) else None
        if not isinstance(res, dict):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 without "
                  f"the documented result object (response_shape: result=object): "
                  f"{raw[:300]}")
            return
        if not isinstance(res.get("status"), str):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — result.status "
                  f"is not a string (response_shape grid): {raw[:300]}")
            return
        oid = res.get("operation_id")
        if oid is not None and not isinstance(oid, int):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                  f"result.operation_id neither integer nor null: {raw[:300]}")
            return
        # ack-vs-state coupling: the 200 must correspond to actual cleared state
        pls, cerr = scroll_payloads(coll)
        for _ in range(6):
            if pls is not None and pls.get(1) in (None, {}):
                break
            time.sleep(0.5)
            pls, _ = scroll_payloads(coll)
        if pls is None:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr)[:300]}")
            return
        if pls.get(1) not in (None, {}):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 ack but "
                  f"payload survived the clear (ack decoupled from state): "
                  f"{pls.get(1)}")
            return
        print(f"OK: face1 200 with result.status={res.get('status')!r}, "
              f"operation_id={oid!r}, payload gone via readback")

        # ---- Face 2 (negative): missing collection -> exactly 404 ----
        s, _, raw = safe_request(
            "POST", f"/collections/{missing}/points/payload/clear",
            json={"points": [1]}, params={"wait": "true"}, timeout=60)
        print(f"face2 clear on nonexistent collection -> status={s}")
        print(f"raw: {raw[:600]}")

        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on missing-collection clear (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — clear on missing "
                  f"collection triggered server error {s} (promise: 404)")
            return
        if s == 404:
            low = raw.lower()
            if missing not in low and "collection" not in low:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — 404 as "
                      f"promised but the error names neither the missing collection "
                      f"nor the resource: {raw[:300]}")
                return
            print("OK: face2 missing collection rejected with 404 naming the resource")
            print("VERDICT: NO_DEFECT")
            return
        if 200 <= s <= 399:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — clear on missing "
                  f"collection returned {s} instead of the promised 404: {raw[:300]}")
            return
        print(f"NOTE: missing collection rejected with {s} (not the promised 404 but "
              f"a clean 4xx rejection; raw above for judge)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal
        try:
            safe_request("DELETE", f"/collections/{missing}", timeout=30)
        except Exception:
            pass  # never created; nothing to clean


if __name__ == "__main__":
    main()
