#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_overwrite_005
# strategy: behavioral status-face pairing (200-face envelope shape + 404-face)
# endpoint: payload+overwrite
# constraint_ids: qdrant_behavioral_payload_overwrite_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/overwrite-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence — the 404 face's diagnostics are
#            assessed for whether it names the missing collection)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral status-face pairing x qdrant_behavioral_payload_overwrite_001
  — the G4 positive/negative pair on the assertion's two declared status faces
  ("overwrite_payload with valid targets returns HTTP 200 ... missing
  collection returns 404"). Face 1 (positive): a points-selector overwrite on
  an existing collection with a 2-key payload point must return EXACTLY 200;
  the 200 envelope must match the published OpenAPI v1.18.0
  Points_overwrite_payload_Response_200 grid — the contract materialized no
  response_shape for THIS endpoint, so the shape oracle is cross-checked
  against the published OpenAPI UpdateResult (R28 lesson; D3b §2 spec-derived
  wins): result is an object, result.status is a string (required by
  UpdateResult), result.operation_id is integer|null — and the 200 must
  couple to actual state (R21 lesson: judge the state, not the echo): scroll
  readback shows the old payload fully replaced. Face 2 (negative): the
  IDENTICAL body against a well-formed but nonexistent collection must
  return EXACTLY 404 (2xx = Type1 acting on a phantom collection; 5xx =
  Type3; other 4xx = clean rejection recorded as NOTE, R25 disposition
  ladder), with the error body naming the missing collection
  (Type-2 diagnostics assessment).
  [chunk_payload+overwrite coverage: behavioral status-face x
  qdrant_behavioral_payload_overwrite_001, 200-envelope/404 pairing (this
  script; 400 invalid-input type-confusion face in _006)]
Oracle: face 1 — overwrite points=[1] payload={"lang":"nl"} (wait=true query)
  on an existing collection returns exactly 200 with result an object whose
  status field is a string (operation_id integer|null when present), and
  scroll readback afterwards shows the point payload EXACTLY {"lang":"nl"}
  (old 2 keys gone) — a 200-ack with the old payload surviving = Type4, an
  envelope violating the UpdateResult grid = Type4, non-200 =
  Type1_IllegalSuccess (promise: 200 on valid targets); face 2 — the same body
  against a nonexistent collection returns exactly 404 (200-299 =
  Type1_IllegalSuccess, 5xx = Type3_RuntimeFailure with /healthz re-check,
  other 4xx = clean-reject NOTE); a 404 body naming neither the collection
  name nor the resource word "collection" = Type2_PoorDiagnostics.
Constraint: qdrant_behavioral_payload_overwrite_001 (bare id) —
  "overwrite_payload with valid targets returns HTTP 200; invalid input
  returns 400; missing collection returns 404" (evidence_tier: explicit;
  level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  payload+overwrite     -> PUT  /collections/{collection_name}/points/payload
  points+upsert         -> PUT  /collections/{collection_name}/points
  points+scroll         -> POST /collections/{collection_name}/points/scroll
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
  healthz               -> GET  /healthz
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
    params= forwards query parameters exactly (wait/timeout live in the query
    string on qdrant point-mutation faces).
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
    """Liveness re-check on the lightweight healthz face (transport branch)."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    print(f"transport failure (healthz status={hs}: {str(hraw)[:200]})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return


def scroll_payloads(coll):
    """id -> payload dict from points+scroll (with_payload).
    Returns (payloads, chan_err); None payloads means channel unusable."""
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points/scroll",
        json={"limit": 100, "with_payload": True}, timeout=30)
    if s != 200 or not isinstance(body, dict):
        return None, (s, raw)
    res = body.get("result")
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        return None, (s, raw)
    return {p.get("id"): p.get("payload") for p in pts if isinstance(p, dict)}, (s, raw)


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpow5" + tag
    ghost = "bpow5no" + tag     # well-formed but never created
    base_payload = {"city": "ams", "n": 1}
    new_payload = {"lang": "nl"}
    vec = [0.1, 0.2, 0.3, 0.4]

    # Arrange: data-bearing collection (own data, own cleanup)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request(
        "PUT", f"/collections/{coll}/points",
        json={"points": [{"id": 1, "vector": vec, "payload": dict(base_payload)}]},
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
        # baseline readback (poll until the payload is visible)
        pls, cerr = scroll_payloads(coll)
        for _ in range(6):
            if pls is not None and pls.get(1) == base_payload:
                break
            time.sleep(0.5)
            pls, cerr = scroll_payloads(coll)
        if pls is None or pls.get(1) != base_payload:
            print(f"baseline readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        print("baseline: payload visible via scroll")

        # ---- Face 1 (positive): valid target -> exactly 200 + envelope + state
        body_req = {"points": [1], "payload": dict(new_payload)}
        s, body, raw = safe_request(
            "PUT", f"/collections/{coll}/points/payload",
            json=body_req, params={"wait": "true"}, timeout=60)
        print(f"\nface1 valid target -> status={s}")
        print(f"raw: {raw[:600]}")

        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on valid target (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — face1 returned {s}")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — face1 valid target "
                  f"returned {s}, promise: 200 on valid targets")
            return

        # envelope vs published OpenAPI v1.18.0 UpdateResult grid (this
        # endpoint's response_shape is NOT materialized in the contract —
        # cross-checked against the published spec per the R28 lesson):
        # result object; result.status string (required); result.operation_id
        # integer|null (D3b §2: spec-derived field wins)
        if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — face1 200 "
                  f"envelope violates the UpdateResult grid: result is not an "
                  f"object ({raw[:300]})")
            return
        res = body["result"]
        if not isinstance(res.get("status"), str):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — face1 200 "
                  f"envelope violates the UpdateResult grid: result.status is not "
                  f"a string ({raw[:300]})")
            return
        opid = res.get("operation_id", None)
        if opid is not None and not isinstance(opid, int):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — face1 200 "
                  f"envelope violates the UpdateResult grid: result.operation_id "
                  f"is neither integer nor null ({raw[:300]})")
            return
        print(f"face1 envelope OK: result.status={res.get('status')!r} "
              f"operation_id={opid!r}")

        # ack-vs-state coupling (async grace)
        pls2, cerr2 = scroll_payloads(coll)
        for _ in range(6):
            if pls2 is not None and pls2.get(1) == new_payload:
                break
            time.sleep(0.5)
            pls2, _ = scroll_payloads(coll)
        if pls2 is None or 1 not in pls2:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr2)[:300]}")
            return
        got = pls2.get(1)
        if got != new_payload:
            if isinstance(got, dict) and ("city" in got or "n" in got):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — face1 "
                      f"200-ack but old payload keys survive readback: {got} "
                      f"(promise face: the overwrite replaces the payload)")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — face1 "
                      f"200-ack but readback payload is {got}, want exactly "
                      f"{new_payload}")
            return
        print("face1 state OK: payload exactly {'lang': 'nl'}")

        # ---- Face 2 (negative): nonexistent collection -> exactly 404
        s2, _, raw2 = safe_request(
            "PUT", f"/collections/{ghost}/points/payload",
            json=body_req, params={"wait": "true"}, timeout=60)
        print(f"\nface2 nonexistent collection -> status={s2}")
        print(f"raw: {raw2[:600]}")

        if s2 <= 0:
            transport_dead()
            return
        if 500 <= s2 <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on missing collection (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — face2 returned {s2}")
            return
        if 200 <= s2 <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — face2 overwrite "
                  f"on a nonexistent collection returned {s2} (promise: 404; a 2xx "
                  f"acks acting on a phantom collection)")
            return
        if s2 != 404:
            print(f"NOTE: face2 returned {s2}, not the promised 404 — clean "
                  f"rejection ladder (R25); recorded for the judge")
        else:
            # Type-2 diagnostics: 404 should name the collection / the resource
            low = raw2.lower()
            if ghost not in low and "collection" not in low:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — face2 404 "
                      f"names neither the collection ({ghost}) nor the resource "
                      f"word 'collection': {raw2[:300]}")
                return
            print("face2 OK: 404 naming the missing collection")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
