#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_overwrite_003
# strategy: strategy1 boundary-value (empty-payload replace-to-nothing closure + selector-less body)
# endpoint: payload+overwrite
# constraint_ids: qdrant_state_payload_overwrite_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/overwrite-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the degenerate corners of the
#            replacement promise: an EMPTY replacement payload and a request
#            with NO selector at all)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value x qdrant_state_payload_overwrite_001 — the
  two degenerate corners of the ENTIRE-replacement promise. Corner A
  (replace-to-nothing closure, G4 boundary closure of "replaces the ENTIRE
  payload"): overwrite point 1's 2-key payload with payload={} — the empty
  object is schema-legal (Payload is a plain object, no minProperties, per
  the published OpenAPI v1.18.0 SetPayload schema), so the promise's extreme
  reading is payload becomes EXACTLY empty ({} or absent — every old key
  GONE, nothing new); point 2 must stay deep-equal baseline. Corner B
  (selector-less body): {"payload":{...}} with NO points and NO filter — both
  optional in the SetPayload schema, so the body is schema-valid but licenses
  no documented selector; trichotomy sub-judgment per the R28 family-posture
  lesson (vacuous-op acceptance is family posture; the defect signal is a
  200-ack that CHANGES state — a selector-less mass broadcast).
  [chunk_payload+overwrite coverage: strategy1 boundary-value x
  qdrant_state_payload_overwrite_001, empty-payload + selector-presence faces
  (this script; points-selector face in _001, filter-selector face in _002,
  content-persistence faces in _004, key-scope face in _008)]
Oracle: corner A — overwrite points=[1] payload={} (wait=true query) on a
  2-key payload point: 200 with scroll readback showing point 1 payload EMPTY
  ({} or absent; ANY old-key residue = Type4 merge-not-replace) and point 2
  deep-equal baseline; a 4xx on the schema-legal empty payload is recorded as
  a NOTE divergence (vacuous-op family posture, R28) and the case continues;
  5xx = Type3 with /healthz re-check. Corner B — {"payload":{"ghost":1}} with
  no selector: 4xx naming points/filter = clean rejection (OK); 200 with
  readback unchanged vs the post-A state = vacuous no-op ack (OK, family
  posture NOTE); 200 with readback changed on ANY point = Type4 (selector-less
  mass broadcast licensed by no documented selector semantics); 5xx = Type3.
  (constraint qdrant_state_payload_overwrite_001)
Constraint: qdrant_state_payload_overwrite_001 (bare id) — "overwrite replaces
  the ENTIRE payload of the targeted points (set semantics: keys missing from
  the new payload are removed)" (evidence_tier: explicit; level: system)

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


def wait_payloads(coll, want, tries=6, delay=0.5):
    """Poll scroll readback until every id's payload deep-equals want[id]."""
    pls, cerr = scroll_payloads(coll)
    for _ in range(tries):
        if pls is None:
            break
        if all(pls.get(i) == want[i] for i in want):
            break
        time.sleep(delay)
        pls, cerr = scroll_payloads(coll)
    return pls, cerr


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpow3" + tag
    base_payloads = {
        1: {"city": "ams", "n": 1},
        2: {"city": "par", "n": 2},
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
        pls, cerr = wait_payloads(coll, dict(base_payloads))
        if pls is None or pls.get(1) != base_payloads[1] or pls.get(2) != base_payloads[2]:
            print(f"baseline readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        print("baseline: both payloads visible via scroll")

        # ---- Corner A: replace-to-nothing (payload={}, schema-legal) ----
        s, _, raw = safe_request(
            "PUT", f"/collections/{coll}/points/payload",
            json={"points": [1], "payload": {}},
            params={"wait": "true"}, timeout=60)
        print(f"\ncorner A payload={{}} points=[1] -> status={s}")
        print(f"raw: {raw[:500]}")

        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on empty-payload overwrite (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — corner A "
                  f"triggered server error {s}")
            return
        after_a = None
        if 200 <= s <= 299:
            # readback: point 1 must be EXACTLY empty ({} or absent)
            want_a = {1: {}, 2: dict(base_payloads[2])}
            pls_a, cerr_a = wait_payloads(coll, want_a)
            # {} vs absent: poll matched on {} only; also accept absent(None)
            if pls_a is None:
                print(f"VERDICT: SCRIPT_ERROR — readback channel failure: "
                      f"{str(cerr_a)[:300]}")
                return
            got1 = pls_a.get(1)
            if got1 not in ({}, None):
                residue = [k for k in base_payloads[1] if isinstance(got1, dict) and k in got1]
                if residue:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — corner A: "
                          f"old keys {residue} SURVIVED an overwrite with the empty "
                          f"payload: {got1} (promise: ENTIRE payload replaced — "
                          f"replace-to-nothing closure)")
                else:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — corner A: "
                          f"point 1 payload after empty overwrite is {got1}, want empty")
                return
            if pls_a.get(2) != base_payloads[2]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — corner A: "
                      f"empty overwrite on point 1 collateral-damaged point 2: "
                      f"{pls_a.get(2)} != {base_payloads[2]}")
                return
            after_a = dict(pls_a)
            print("corner A OK: point 1 payload empty, point 2 deep-equal baseline")
        else:
            low = raw.lower()
            if "payload" not in low:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — corner A "
                      f"rejected with {s} but names no payload parameter: {raw[:300]}")
                return
            print(f"NOTE: corner A empty payload rejected with {s} — schema-legal "
                  f"degenerate (R28 vacuous-op family posture divergence); recorded "
                  f"for the judge")
            after_a = dict(base_payloads)  # nothing changed

        # ---- Corner B: selector-less body (no points, no filter) ----
        s, _, raw = safe_request(
            "PUT", f"/collections/{coll}/points/payload",
            json={"payload": {"ghost": 1}},
            params={"wait": "true"}, timeout=60)
        print(f"\ncorner B selector-less payload={{ghost:1}} -> status={s}")
        print(f"raw: {raw[:500]}")

        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on selector-less body (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — corner B "
                  f"triggered server error {s}")
            return
        if s in (400, 422):
            low = raw.lower()
            if "point" not in low and "filter" not in low:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — corner B "
                      f"rejected with {s} but names no points/filter parameter: "
                      f"{raw[:300]}")
                return
            print("corner B OK: selector-less body cleanly rejected naming the selector")
            print("VERDICT: NO_DEFECT")
            return
        if 200 <= s <= 299:
            # sub-judge: state change = selector-less mass broadcast
            pls_b, cerr_b = scroll_payloads(coll)
            changed_ids = []
            for _ in range(4):  # async grace
                if pls_b is None:
                    break
                changed_ids = [i for i in (1, 2)
                               if pls_b.get(i) != after_a.get(i)]
                if changed_ids:
                    break
                time.sleep(0.5)
                pls_b, _ = scroll_payloads(coll)
            if pls_b is None:
                print(f"VERDICT: SCRIPT_ERROR — readback channel failure: "
                      f"{str(cerr_b)[:300]}")
                return
            if changed_ids:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — corner B: "
                      f"selector-less overwrite was 200-accepted AND changed payload "
                      f"state of points {changed_ids}: {pls_b} (baseline {after_a}) — "
                      f"a selector-less request licenses no documented targeting; a "
                      f"mass broadcast is a destructive undocumented default")
                return
            print("corner B OK: 200 no-op ack, state unchanged (vacuous-op family "
                  "posture, R28)")
            print("VERDICT: NO_DEFECT")
            return
        print(f"NOTE: corner B returned {s} (unexpected status family); recorded "
              f"for the judge")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
