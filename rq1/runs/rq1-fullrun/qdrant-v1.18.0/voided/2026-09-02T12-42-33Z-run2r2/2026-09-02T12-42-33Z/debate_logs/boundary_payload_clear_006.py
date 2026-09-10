#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_clear_006
# strategy: strategy2 type-boundary (selector type-confusion: points / filter)
# endpoint: payload+clear
# constraint_ids: qdrant_behavioral_payload_clear_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/clear-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde is assumed to reject a
#            type-confused selector; if coercion lets it through on a DESTRUCTIVE
#            endpoint the blast radius is a payload wipe, so every 200 is
#            sub-judged by readback)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_behavioral_payload_clear_001 — type
  confusion on the two selector parameters whose types the endpoint spec
  declares (points: array[PointId]|null; filter: Filter|null). Five sub-cases on
  one live bpclr6_* collection with 2 payload-bearing points: (a) points="all"
  (string where the spec types an array); (b) points=123 (integer); (c)
  points=[null] (null element where PointId = integer|string); (d)
  filter="city=par" (string where the spec types an object); (e) filter=[]
  (array where the spec types an object). The contract typing says none of these
  is a valid target, so the 200-face promise ("200 on VALID targets") must not
  fire: expected 4xx. Because the endpoint is destructive, every 200 acceptance
  is sub-judged by scroll readback: accepted AND wiped = Type4 over-reach on top
  of the Type1 illegal acceptance; accepted and no-op = Type1_IllegalSuccess
  (invalid target 200-acked).
  [chunk_payload+clear coverage: behavioral x qdrant_behavioral_payload_clear_001,
  selector type-confusion face (this script; 200/404 status pairing in _005)]
Oracle: each of the five type-confused clear bodies (points="all" / points=123 /
  points=[null] / filter="city=par" / filter=[]) returns 4xx with the points or
  filter parameter named in the error (silent/unnamed 4xx = Type2_PoorDiagnostics);
  any 200 is a defect — readback shows payloads wiped = Type4_StateLogicViolation
  (type-confused selector executed a destructive wipe), payloads intact =
  Type1_IllegalSuccess (invalid target accepted); 5xx = Type3_RuntimeFailure with
  /healthz re-check.
Constraint: qdrant_behavioral_payload_clear_001 (bare id) — "clear_payload returns
  HTTP 200 on valid targets; missing collection returns 404" (evidence_tier:
  explicit; level: endpoint; the type-confused selectors are invalid targets per
  the endpoint parameter typings, so they must not resolve to the 200 face)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  payload+clear       -> POST /collections/{collection_name}/points/payload/clear
  points+upsert       -> PUT  /collections/{collection_name}/points
  points+scroll       -> POST /collections/{collection_name}/points/scroll
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
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
    coll = "bpclr6" + tag
    base_payloads = {
        1: {"city": "ams", "n": 1},
        2: {"city": "par", "n": 2},
    }

    # Arrange: data-bearing collection with 2 payload points (own data, own cleanup)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request(
        "PUT", f"/collections/{coll}/points",
        json={"points": [{"id": i, "vector": [0.1 * i, 0.2 * i, 0.3 * i, 0.4 * i],
                          "payload": base_payloads[i]} for i in (1, 2)]},
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

        # (label, body) — each violates the endpoint parameter typing
        cases = [
            ("points='all' (string, spec types array[PointId])", {"points": "all"}),
            ("points=123 (integer, spec types array[PointId])", {"points": 123}),
            ("points=[null] (null element, PointId=integer|string)", {"points": [None]}),
            ("filter='city=par' (string, spec types Filter object)",
             {"filter": "city=par"}),
            ("filter=[] (array, spec types Filter object)", {"filter": []}),
        ]
        for label, body in cases:
            s, _, raw = safe_request(
                "POST", f"/collections/{coll}/points/payload/clear",
                json=body, timeout=60)
            print(f"\ncase {label} -> status={s}")
            print(f"raw: {raw[:500]}")

            if s <= 0:
                transport_dead()
                return
            if 500 <= s <= 599:
                hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
                print(f"5xx on type-confused selector (healthz status={hs}: "
                      f"{hraw[:200]})")
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — type-confused "
                      f"selector {label} triggered server error {s}")
                return
            if 200 <= s <= 299:
                # accepted an invalid target on a destructive endpoint — sub-judge
                pls2, cerr2 = scroll_payloads(coll)
                wiped = pls2 is not None and any(
                    pls2.get(i) in (None, {}) for i in (1, 2))
                for _ in range(4):  # async grace
                    if wiped:
                        break
                    time.sleep(0.5)
                    pls2, _ = scroll_payloads(coll)
                    if pls2 is not None:
                        wiped = any(pls2.get(i) in (None, {}) for i in (1, 2))
                if pls2 is None:
                    print(f"VERDICT: SCRIPT_ERROR — readback channel failure: "
                          f"{str(cerr2)[:300]}")
                    return
                if wiped:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"type-confused selector {label} was 200-accepted AND "
                          f"executed a destructive wipe: {pls2}")
                else:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — "
                          f"type-confused selector {label} 200-accepted on an "
                          f"invalid target (spec typing: points=array[PointId]|null, "
                          f"filter=Filter|null); payloads intact (no-op ack)")
                return
            if s in (400, 404, 422):
                low = raw.lower()
                if "points" not in low and "filter" not in low:
                    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — case "
                          f"{label} rejected with {s} but the error names no selector "
                          f"parameter: {raw[:300]}")
                    return
                print(f"OK: case {label} cleanly rejected with {s} naming the selector")
                continue
            print(f"NOTE: case {label} returned {s} (unexpected status family; raw "
                  f"above for judge)")
            print("VERDICT: NO_DEFECT")
            return

        # final readback: five rejected selectors must have left state untouched
        pls3, cerr3 = scroll_payloads(coll)
        if pls3 is None:
            print(f"VERDICT: SCRIPT_ERROR — final readback failure: {str(cerr3)[:300]}")
            return
        for i in (1, 2):
            if pls3.get(i) != base_payloads[i]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — payload of "
                      f"point {i} damaged although every selector was rejected: "
                      f"{pls3.get(i)} != {base_payloads[i]}")
                return
        print("all five type-confused selectors rejected; payloads deep-equal baseline")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
