#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_set_005
# strategy: strategy2 type-boundary attack (payload/points/filter type confusion — the 400 invalid-input face)
# endpoint: payload+set
# constraint_ids: qdrant_behavioral_payload_set_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/set-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde assumed to reject
#            non-object payload values, non-array/PointId-violating points,
#            and string/shape-violating filters; every accepted type
#            confusion is sub-judged by state readback)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_behavioral_payload_set_001 — the
  assertion's declared 400 face ("invalid input returns 400"): ten
  type-confused bodies against the published OpenAPI v1.18.0 SetPayload
  schema (body: payload object REQUIRED; points array[PointId]|null with
  PointId oneOf uint64|UUID string; filter Filter|null with must/should/
  must_not arrays of conditions):
  (1) payload omitted (required field absent), (2) payload=[] (array),
  (3) payload="city" (string), (4) payload=42 (number), (5) payload=null,
  (6) points="1" (string instead of array; payload itself valid),
  (7) points=[-1] (negative — PointId is u64|UUID, -1 is neither),
  (8) points=[1.5] (float — neither u64 nor UUID string),
  (9) filter="city=ams" (string instead of Filter object), (10)
  filter={"must":"x"} (must is a string; the grid requires an array of
  conditions). Each must be rejected with a 4xx; any 200 is a defect and
  is sub-judged by scroll readback (state changed = Type4 destructive
  execution of a type-confused body; state unchanged = Type1 invalid value
  accepted). Final sweep: after all faces the payloads must be deep-equal
  baseline. Error-naming quality on 4xx faces is NOTE only (R29 lesson:
  Type2 error-naming has NO anchor — three NOT precedents).
  [chunk_payload+set coverage: strategy2 type-boundary x
  qdrant_behavioral_payload_set_001, payload/points/filter type-confusion
  faces (this script; 200-envelope/404 status pairing in
  boundary_payload_set_004)]
Oracle: each of the ten type-confused bodies (all on an existing
  collection, wait=true query) returns a 4xx (clean rejection; unnamed 4xx =
  NOTE only); any 200 is a defect — readback shows payload state changed =
  Type4_StateLogicViolation (type-confused body executed a destructive
  set), payloads deep-equal baseline = Type1_IllegalSuccess (invalid value
  accepted); 5xx/transport = Type3_RuntimeFailure with /healthz re-check;
  all ten rejected leaves the payloads deep-equal baseline at the final
  readback (constraint qdrant_behavioral_payload_set_001: "invalid input
  returns 400").
Constraint: qdrant_behavioral_payload_set_001 (bare id) — "set_payload with
  valid targets returns HTTP 200; both targets null or invalid input
  returns 400; missing collection returns 404" (evidence_tier: explicit;
  level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  payload+set           -> POST /collections/{collection_name}/points/payload
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


def readback_changed(coll, baseline, tries=4):
    """Return (changed_ids, pls) — ids whose payload differs from baseline
    (with async grace); (None, None) means the channel is unusable."""
    pls, _ = scroll_payloads(coll)
    for _ in range(tries):
        if pls is None:
            return None, None
        changed = [i for i in baseline if pls.get(i) != baseline[i]]
        if changed:
            return changed, pls
        time.sleep(0.5)
        pls, _ = scroll_payloads(coll)
    return [], pls


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpset8" + tag
    base_payloads = {
        1: {"city": "ams", "n": 1},
        2: {"city": "par", "n": 2},
    }
    vecs = {1: [0.1, 0.2, 0.3, 0.4], 2: [0.2, 0.3, 0.4, 0.5]}
    valid_payload = {"lang": "nl"}

    # Ten type-confused bodies (schema grid: payload object REQUIRED;
    # points array[PointId]|null, PointId oneOf uint64|UUID; filter
    # Filter|null with must/should/must_not arrays)
    faces = [
        ("payload omitted (required)", {"points": [1]}),
        ("payload=[] (array)", {"points": [1], "payload": []}),
        ("payload='city' (string)", {"points": [1], "payload": "city"}),
        ("payload=42 (number)", {"points": [1], "payload": 42}),
        ("payload=null", {"points": [1], "payload": None}),
        ("points='1' (string)", {"points": "1", "payload": dict(valid_payload)}),
        ("points=[-1] (negative PointId)", {"points": [-1], "payload": dict(valid_payload)}),
        ("points=[1.5] (float PointId)", {"points": [1.5], "payload": dict(valid_payload)}),
        ("filter='city=ams' (string)", {"filter": "city=ams", "payload": dict(valid_payload)}),
        ("filter={'must':'x'} (string condition)",
         {"filter": {"must": "x"}, "payload": dict(valid_payload)}),
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

        for label, body_json in faces:
            s, _, raw = safe_request(
                "POST", f"/collections/{coll}/points/payload",
                json=body_json, params={"wait": "true"}, timeout=60)
            print(f"\nface [{label}] -> status={s}")
            print(f"raw: {raw[:400]}")
            if s <= 0:
                transport_dead()
                return
            if 500 <= s <= 599:
                hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
                print(f"5xx on type-confused body (healthz status={hs}: {hraw[:200]})")
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — face "
                      f"[{label}] triggered server error {s}")
                return
            if 200 <= s <= 299:
                changed, pls_a = readback_changed(coll, base_payloads)
                if changed is None:
                    print(f"VERDICT: SCRIPT_ERROR — readback channel failure on face [{label}]")
                    return
                if changed:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"type-confused body [{label}] was 200-accepted AND "
                          f"changed payload state of points {changed}: {pls_a} "
                          f"(baseline {base_payloads}) — destructive execution "
                          f"of an invalid body")
                    return
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — invalid "
                      f"body [{label}] accepted with 200 (state unchanged; "
                      f"promise: invalid input returns 400)")
                return
            if s in (400, 422):
                low = raw.lower()
                names = [w for w in ("payload", "points", "filter", "point", "type", "id")
                         if w in low]
                print(f"face [{label}] cleanly rejected with {s} (mentions: "
                      f"{names or 'no parameter name'} — NOTE only, R29)")
            else:
                print(f"NOTE: face [{label}] returned unexpected status {s}; "
                      f"recorded for the judge")

        # final sweep: payloads deep-equal baseline after all rejections
        pls_f, cerr_f = scroll_payloads(coll)
        if pls_f is None:
            print(f"VERDICT: SCRIPT_ERROR — final readback failure: {str(cerr_f)[:300]}")
            return
        drift = [i for i in base_payloads if pls_f.get(i) != base_payloads[i]]
        if drift:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — after all "
                  f"rejections, payloads drifted from baseline on points {drift}")
            return
        print("final sweep: payloads deep-equal baseline (all 10 type-confused faces rejected)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
