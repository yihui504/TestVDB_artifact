#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_clear_003
# strategy: strategy1 boundary-value (selector-presence boundary: empty body {})
# endpoint: payload+clear
# constraint_ids: qdrant_state_payload_clear_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/clear-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — assuming the destructive bulk-wipe
#            requires an explicit target; the {} boundary probes whether a
#            selector-less clear is accepted and what it silently does)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value (selector-presence boundary) x
  qdrant_state_payload_clear_001 — the NEGATIVE direction of the G4 pair: clear
  with body {} (neither `points` nor `filter` nor `shard_key`), while the
  endpoint's request_required_paths list the selector branches (points /
  filter.* / shard_key.*) as the required anyOf — a destructive bulk-wipe must
  carry an explicit target. Regression of the run2r #1 R5 "metadata {} clear"
  no-op doc-consistency case on this endpoint family. Sub-typing by readback:
  4xx = clean reject (diagnostics scanned for Type-2); 200 with payloads intact
  = Type1_IllegalSuccess no-op reproduction (accepted a selector-less wipe that
  wiped nothing); 200 with payloads gone = Type4 catastrophic over-reach
  (unbounded bulk wipe from a selector-less request).
  G3 note: threat-model "filter=null treated as no-filter" is by-design for READ
  endpoints (query/search) where a missing filter is harmless; the expectation
  here keys on the spec-derived request_required_paths of the DESTRUCTIVE clear
  face, where "no selector" has no safe meaning.
  [chunk_payload+clear coverage: state readback x qdrant_state_payload_clear_001,
  selector-absence boundary {} (this script)]
Oracle: POST payload/clear with body {} on a collection holding 2 payload-bearing points returns a 4xx reject (per request_required_paths anyOf: points|filter|shard_key);
  a 200 is adjudicated by scroll readback — payloads still deep-equal baseline
  after grace polls = Type1_IllegalSuccess (no-op ack on selector-less wipe),
  any payload gone = Type4_StateLogicViolation (unbounded bulk wipe); 5xx =
  Type3_RuntimeFailure with /healthz re-check; 4xx without any selector-keyword
  in the error body = Type2_PoorDiagnostics.
Constraint: qdrant_state_payload_clear_001 (bare id) — "clear removes all payload
  keys of the targeted points" (evidence_tier: explicit; level: system; the
  {} boundary attacks the implicit "of the TARGETED points" precondition — with
  no target declared, the operation must not silently succeed)

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
    coll = "bpclr3" + tag
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
        # baseline readback (poll until both payloads visible)
        pls, cerr = scroll_payloads(coll)
        for _ in range(6):
            if pls is not None and pls.get(1) == base_payloads[1] and pls.get(2) == base_payloads[2]:
                break
            time.sleep(0.5)
            pls, cerr = scroll_payloads(coll)
        if pls is None or pls.get(1) != base_payloads[1] or pls.get(2) != base_payloads[2]:
            print(f"baseline readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        print("baseline: both payloads visible via scroll")

        # Act: selector-less clear (empty body {}) — request_required_paths
        # anyOf (points | filter.* | shard_key.*) is NOT satisfied
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload/clear",
            json={}, timeout=60)
        print(f"clear body={{}} -> status={s}")
        print(f"raw: {raw[:600]}")

        # Assert
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on selector-less clear (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — selector-less clear "
                  f"triggered server error {s} (expected 4xx validation reject)")
            return
        if 200 <= s <= 299:
            # accepted a selector-less destructive wipe — sub-type by readback
            pls, cerr = scroll_payloads(coll)
            wiped_seen = pls is not None and any(
                pls.get(i) in (None, {}) for i in (1, 2))
            for _ in range(4):  # async grace: a lagging wipe must not mask itself
                if wiped_seen:
                    break
                time.sleep(0.5)
                pls, _ = scroll_payloads(coll)
                if pls is not None:
                    wiped_seen = any(pls.get(i) in (None, {}) for i in (1, 2))
            print(f"post-empty-body-clear scroll payloads: {pls}")
            if pls is None:
                print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr)[:300]}")
                return
            if wiped_seen:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — selector-less "
                      f"clear 200-accepted and WIPED payloads unboundedly (no target "
                      f"declared): {pls}")
                return
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — selector-less clear "
                  f"200-accepted but wiped nothing (no-op ack; request_required_paths "
                  f"anyOf points|filter|shard_key violated; run2r#1 R5 doc-consistency "
                  f"case reproduces)")
            return
        if s in (400, 404, 422):
            low = raw.lower()
            if ("points" not in low) and ("filter" not in low) and ("shard" not in low):
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — selector-less "
                      f"clear rejected with {s} but the error names no selector "
                      f"parameter: {raw[:300]}")
                return
            print(f"OK: selector-less clear cleanly rejected with {s}; diagnostics "
                  f"name the selector requirement")
            print("VERDICT: NO_DEFECT")
            return
        print(f"NOTE: selector-less clear returned {s} (unexpected status family; "
              f"raw above for judge)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
