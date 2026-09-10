#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_overwrite_006
# strategy: strategy2 type-boundary attack (payload/points type confusion — the 400 invalid-input face)
# endpoint: payload+overwrite
# constraint_ids: qdrant_behavioral_payload_overwrite_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/overwrite-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde assumed to reject
#            non-object payload values and non-array points; every accepted
#            type confusion is sub-judged by state readback)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary attack x qdrant_behavioral_payload_overwrite_001
  — the assertion's declared 400 face ("invalid input returns 400"): six
  type-confused bodies against the published OpenAPI v1.18.0 SetPayload
  schema (body requires payload:object; points:array[PointId]|null):
  (1) payload omitted (required=['payload']), (2) payload=[] (array),
  (3) payload="city" (string), (4) payload=42 (number), (5) payload=null,
  (6) points="1" (string instead of array, payload itself valid). Each must
  be rejected with a 4xx naming the confused parameter; any 200 is a defect
  and is sub-judged by scroll readback (state changed = Type4 destructive
  execution of a type-confused body; state unchanged = Type1 invalid value
  accepted). Final sweep: after all rejections the payloads must be
  deep-equal baseline.
  [chunk_payload+overwrite coverage: strategy2 type-boundary x
  qdrant_behavioral_payload_overwrite_001, payload/points type-confusion
  faces (this script; 200-envelope/404 status pairing in _005)]
Oracle: each of the six type-confused bodies (all on an existing collection,
  wait=true query) returns 4xx with the confused parameter named in the error
  (silent or unnamed 4xx = Type2_PoorDiagnostics); any 200 is a defect —
  readback shows payload state changed = Type4_StateLogicViolation
  (type-confused body executed a destructive overwrite), payloads deep-equal
  baseline = Type1_IllegalSuccess (invalid value accepted); 5xx/transport =
  Type3_RuntimeFailure with /healthz re-check; all six rejected leaves the
  payloads deep-equal baseline at the final readback (constraint
  qdrant_behavioral_payload_overwrite_001: "invalid input returns 400").
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
    coll = "bpow6" + tag
    base_payloads = {
        1: {"city": "ams", "n": 1},
        2: {"city": "par", "n": 2},
    }
    vecs = {1: [0.1, 0.2, 0.3, 0.4], 2: [0.2, 0.3, 0.4, 0.5]}

    # (label, body, expected-error-token) — the six type confusions
    cases = [
        ("payload omitted (spec: required=['payload'])",
         {"points": [1]}, "payload"),
        ("payload=[] (array, spec: object)",
         {"points": [1], "payload": []}, "payload"),
        ("payload=\"city\" (string, spec: object)",
         {"points": [1], "payload": "city"}, "payload"),
        ("payload=42 (number, spec: object)",
         {"points": [1], "payload": 42}, "payload"),
        ("payload=null (spec: object, required)",
         {"points": [1], "payload": None}, "payload"),
        ("points=\"1\" (string, spec: array[PointId])",
         {"points": "1", "payload": {"ghost": 1}}, "points"),
    ]

    # Arrange: data-bearing collection (own data, own cleanup)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request(
        "PUT", f"/collections/{coll}/points",
        json={"points": [{"id": i, "vector": vecs[i], "payload": base_payloads[i]}
                         for i in (1, 2)]},
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
        # baseline readback (poll until both payloads visible)
        pls, cerr = scroll_payloads(coll)
        for _ in range(6):
            if pls is not None and pls.get(1) == base_payloads[1] \
                    and pls.get(2) == base_payloads[2]:
                break
            time.sleep(0.5)
            pls, cerr = scroll_payloads(coll)
        if pls is None or pls.get(1) != base_payloads[1] or pls.get(2) != base_payloads[2]:
            print(f"baseline readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        print("baseline: both payloads visible via scroll")

        for label, body, token in cases:
            s, _, raw = safe_request(
                "PUT", f"/collections/{coll}/points/payload",
                json=body, params={"wait": "true"}, timeout=60)
            print(f"\ncase {label} -> status={s}")
            print(f"raw: {raw[:500]}")

            if s <= 0:
                transport_dead()
                return
            if 500 <= s <= 599:
                hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
                print(f"5xx on type-confused body (healthz status={hs}: {hraw[:200]})")
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — type confusion "
                      f"{label} triggered server error {s}")
                return
            if 200 <= s <= 299:
                # accepted a type-confused destructive request — sub-judge state
                pls2, cerr2 = scroll_payloads(coll)
                changed = pls2 is not None and any(
                    pls2.get(i) != base_payloads[i] for i in (1, 2))
                for _ in range(4):  # async grace
                    if changed or pls2 is None:
                        break
                    time.sleep(0.5)
                    pls2, _ = scroll_payloads(coll)
                    if pls2 is not None:
                        changed = any(pls2.get(i) != base_payloads[i] for i in (1, 2))
                if pls2 is None:
                    print(f"VERDICT: SCRIPT_ERROR — readback channel failure: "
                          f"{str(cerr2)[:300]}")
                    return
                if changed:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case "
                          f"{label} was 200-accepted AND executed a destructive "
                          f"payload change: {pls2} (baseline {base_payloads})")
                else:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — case "
                          f"{label} 200-accepted although the value violates the "
                          f"published SetPayload schema; payloads intact (no-op ack)")
                return
            if s in (400, 422):
                low = raw.lower()
                if token not in low:
                    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — case "
                          f"{label} rejected with {s} but the error does not name "
                          f"the confused parameter '{token}': {raw[:300]}")
                    return
                print(f"OK: case {label} cleanly rejected with {s} naming '{token}'")
                continue
            print(f"NOTE: case {label} returned {s} (unexpected status family; raw "
                  f"{raw[:200]}); recorded for the judge — continuing the sweep")
            continue

        # final sweep: all rejections must have left state untouched
        pls_f, cerr_f = scroll_payloads(coll)
        if pls_f is None:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr_f)[:300]}")
            return
        for i in (1, 2):
            if pls_f.get(i) != base_payloads[i]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — final "
                      f"sweep: point {i} payload drifted to {pls_f.get(i)}, want "
                      f"{base_payloads[i]} (a rejected body must not change state)")
                return
        print("final sweep OK: payloads deep-equal baseline after all rejections")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
