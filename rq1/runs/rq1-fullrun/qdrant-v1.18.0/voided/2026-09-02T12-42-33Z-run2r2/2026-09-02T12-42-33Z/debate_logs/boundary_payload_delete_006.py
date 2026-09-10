#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_delete_006
# strategy: strategy2 type-boundary attack (keys type confusion — the 400 invalid-input face)
# endpoint: payload+delete
# constraint_ids: qdrant_behavioral_payload_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the endpoint spec types keys
#            as array[string] required=true; the probes test whether the serde
#            layer coerces or silently accepts a mistyped keys value on a
#            DESTRUCTIVE endpoint)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary (type confusion) x qdrant_behavioral_payload_delete_001
  — the assertion's declared "400 on invalid input" face, applied to the one
  parameter that defines this endpoint: `keys` (spec: array[string],
  required=true). Five type-confused bodies on one live bpdel6_* collection with
  2 payload-bearing points; each carries a VALID points selector [1] so ONLY the
  keys typing is violated:
    keys="city"          (string where the spec types array[string])
    keys=[123,456]       (array[int] elements where the spec types strings)
    keys=[null]          (null element where the spec types strings)
    keys={"city":1}      (object where the spec types array[string])
    keys=null            (explicit null on a required field)
  Adjudication: 4xx naming `keys` = clean reject (silent/unnamed 4xx =
  Type2_PoorDiagnostics); any 2xx is a defect sub-judged by readback — payload
  state changed = Type4 (type-confused keys EXECUTED a destructive delete),
  payloads intact = Type1_IllegalSuccess (invalid keys value accepted, no-op
  ack); 5xx = Type3 with /healthz re-check. Final readback: rejected bodies
  must have left state untouched.
  [chunk_payload+delete coverage: behavioral 400 invalid-input face x
  qdrant_behavioral_payload_delete_001, keys type-confusion (this script;
  200-envelope/404 pairing in _005)]
Oracle: each of the five type-confused bodies (keys="city" / keys=[123,456] /
  keys=[null] / keys={"city":1} / keys=null, all with a valid points=[1]
  selector) returns 4xx with the keys parameter named in the error (silent or
  unnamed 4xx = Type2_PoorDiagnostics); any 200 is a defect — readback shows
  payload state changed = Type4_StateLogicViolation (type-confused keys
  executed a destructive delete), payloads deep-equal baseline = Type1
  _IllegalSuccess (invalid keys value accepted); 5xx = Type3_RuntimeFailure
  with /healthz re-check; all five rejected leaves payloads deep-equal baseline
  at the final readback (constraint qdrant_behavioral_payload_delete_001:
  "400 on invalid input").
Constraint: qdrant_behavioral_payload_delete_001 (bare id) — "delete_payload
  with a keys list returns HTTP 200 on valid targets; missing collection
  returns 404" with declared "400 on invalid input" (evidence_tier: explicit;
  level: endpoint; this script attacks exactly the 400-on-invalid-input face
  through the endpoint's defining parameter)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  payload+delete      -> POST /collections/{collection_name}/points/payload/delete
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
    coll = "bpdel6" + tag
    base_payloads = {
        1: {"city": "ams", "n": 1, "tag": "alpha"},
        2: {"city": "par", "n": 2, "tag": "beta"},
    }
    vecs = {1: [0.1, 0.2, 0.3, 0.4], 2: [0.2, 0.3, 0.4, 0.5]}

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

        # (label, body) — each violates ONLY the keys typing (selector is valid)
        cases = [
            ("keys='city' (string, spec types array[string])",
             {"points": [1], "keys": "city"}),
            ("keys=[123,456] (array[int] elements, spec types array[string])",
             {"points": [1], "keys": [123, 456]}),
            ("keys=[null] (null element, spec types array[string])",
             {"points": [1], "keys": [None]}),
            ("keys={'city':1} (object, spec types array[string])",
             {"points": [1], "keys": {"city": 1}}),
            ("keys=null (explicit null on required field)",
             {"points": [1], "keys": None}),
        ]
        for label, body in cases:
            s, _, raw = safe_request(
                "POST", f"/collections/{coll}/points/payload/delete",
                json=body, params={"wait": "true"}, timeout=60)
            print(f"\ncase {label} -> status={s}")
            print(f"raw: {raw[:500]}")

            if s <= 0:
                transport_dead()
                return
            if 500 <= s <= 599:
                hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
                print(f"5xx on type-confused keys (healthz status={hs}: "
                      f"{hraw[:200]})")
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — "
                      f"type-confused keys {label} triggered server error {s}")
                return
            if 200 <= s <= 299:
                # accepted an invalid keys value on a destructive endpoint —
                # sub-judge by readback
                pls2, cerr2 = scroll_payloads(coll)
                changed = pls2 is not None and any(
                    pls2.get(i) != base_payloads[i] for i in (1, 2))
                for _ in range(4):  # async grace
                    if changed:
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
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"type-confused keys {label} was 200-accepted AND "
                          f"executed a destructive delete: {pls2} "
                          f"(baseline {base_payloads})")
                else:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — "
                          f"type-confused keys {label} 200-accepted although the "
                          f"spec types keys=array[string] required=true; payloads "
                          f"intact (no-op ack)")
                return
            if s in (400, 404, 422):
                low = raw.lower()
                if "key" not in low:
                    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — case "
                          f"{label} rejected with {s} but the error does not name "
                          f"the keys parameter: {raw[:300]}")
                    return
                print(f"OK: case {label} cleanly rejected with {s} naming keys")
                continue
            print(f"NOTE: case {label} returned {s} (unexpected status family; raw "
                  f"above for judge)")
            print("VERDICT: NO_DEFECT")
            return

        # final readback: rejected bodies must have left state untouched
        pls3, cerr3 = scroll_payloads(coll)
        if pls3 is None:
            print(f"VERDICT: SCRIPT_ERROR — final readback failure: {str(cerr3)[:300]}")
            return
        for i in (1, 2):
            if pls3.get(i) != base_payloads[i]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — payload of "
                      f"point {i} damaged although every keys-confused body was "
                      f"rejected: {pls3.get(i)} != {base_payloads[i]}")
                return
        print("all five type-confused keys bodies rejected; payloads deep-equal baseline")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
