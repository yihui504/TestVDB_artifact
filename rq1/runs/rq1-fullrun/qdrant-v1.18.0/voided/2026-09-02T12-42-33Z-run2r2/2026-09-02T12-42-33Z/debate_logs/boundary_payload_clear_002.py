#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_clear_002
# strategy: state_data_preservation_readback (filter-selector face)
# endpoint: payload+clear
# constraint_ids: qdrant_state_payload_clear_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/clear-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the filter selector branch of
#            clear; scope precision judged via readback, not the ack)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state data-preservation readback x qdrant_state_payload_clear_001 (promise:
  "clear removes all payload keys of the targeted points") — the FILTER-selector
  face (parameter `filter`, typed Filter|null per the endpoint spec; structure
  filter.must[].key + match per request_required_paths filter.must.key). One live
  bpclr2_* collection with 3 points (city=ams/par/tok); clear targets ONLY the
  filter-matching point (city=par, wait=true). Judged via readback channels: (1)
  scroll with_payload — par point payload-empty, ams/tok deep-equal baseline
  (filter over-reach = Type4); (2) with_vector — vectors intact; (3) exact count
  stays 3. Complements _001 (points-selector face): both documented selector
  branches of the same promise must behave identically (G9).
  [chunk_payload+clear coverage: state readback x qdrant_state_payload_clear_001,
  filter-selector face (this script; points-selector face in _001)]
Oracle: with 3 payload-bearing points (city ams/par/tok), clear {"filter":{"must":[{"key":"city","match":{"value":"par"}}]},"wait":true}
  returns 200; scroll afterwards shows the par point payload empty (null/{}), ams/tok
  payloads deep-equal to baseline, all vectors intact, exact count stays 3 —
  residue on the matched point, collateral wipe on unmatched points, vector loss
  or count drift each = Type4_StateLogicViolation; 5xx = Type3_RuntimeFailure with
  /healthz re-check (constraint qdrant_state_payload_clear_001).
Constraint: qdrant_state_payload_clear_001 (bare id) — "clear removes all payload
  keys of the targeted points; after clear, targeted points carry no payload keys"
  (evidence_tier: explicit; level: system)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  payload+clear       -> POST /collections/{collection_name}/points/payload/clear
  points+upsert       -> PUT  /collections/{collection_name}/points
  points+scroll       -> POST /collections/{collection_name}/points/scroll
  points+count        -> POST /collections/{collection_name}/points/count
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


def payload_empty(p):
    pl = p.get("payload")
    return pl is None or pl == {}


def vector_intact(p):
    v = p.get("vector")
    return bool(v) and (isinstance(v, (list, dict)) and len(v) > 0)


def scroll_snapshot(coll):
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points/scroll",
        json={"limit": 100, "with_payload": True, "with_vector": True}, timeout=30)
    if s != 200 or not isinstance(body, dict):
        return None, (s, raw)
    res = body.get("result")
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        return None, (s, raw)
    return {p.get("id"): p for p in pts if isinstance(p, dict)}, (s, raw)


def count_exact(coll):
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points/count",
        json={"exact": True}, timeout=30)
    if s != 200 or not isinstance(body, dict):
        return None, (s, raw)
    res = body.get("result")
    if isinstance(res, dict) and isinstance(res.get("count"), int):
        return res["count"], (s, raw)
    return None, (s, raw)


def wait_state(coll, want_cleared, want_intact, tries=6, delay=0.5):
    snap, cerr = scroll_snapshot(coll)
    for _ in range(tries):
        if snap is None:
            break
        ok = all(payload_empty(snap[i]) for i in want_cleared if i in snap) and \
             all(snap[i].get("payload") == want_intact[i] for i in want_intact if i in snap)
        if ok:
            break
        time.sleep(delay)
        snap, cerr = scroll_snapshot(coll)
    return snap, cerr


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpclr2" + tag
    base_payloads = {
        1: {"city": "ams", "n": 1},
        2: {"city": "par", "n": 2},
        3: {"city": "tok", "n": 3},
    }
    vecs = {1: [0.1, 0.2, 0.3, 0.4], 2: [0.2, 0.3, 0.4, 0.5], 3: [0.3, 0.4, 0.5, 0.6]}

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
                         for i in (1, 2, 3)]},
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
        snap, cerr = wait_state(coll, [], dict(base_payloads))
        if snap is None or any(i not in snap for i in (1, 2, 3)):
            print(f"baseline readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        cnt0, _ = count_exact(coll)
        print(f"baseline: 3 payloads visible, exact count={cnt0}")

        # Act: clear ONLY the filter-matching point (city=par), wait=true
        clear_body = {"filter": {"must": [
            {"key": "city", "match": {"value": "par"}}]}}
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload/clear",
            json=clear_body, params={"wait": "true"}, timeout=60)
        print(f"clear filter city=par -> status={s}")
        print(f"raw: {raw[:600]}")

        # Assert
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on legal filtered clear (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — filtered clear on "
                  f"existing collection returned {s}")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal filtered "
                  f"clear rejected with {s} (promise: targeted clear succeeds)")
            return

        snap, cerr = wait_state(coll, [2], {1: base_payloads[1], 3: base_payloads[3]})
        if snap is None or any(i not in snap for i in (1, 2, 3)):
            print(f"post-clear readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — readback channel failure, no defect conclusion")
            return
        print(f"post-clear scroll: p1.payload={snap[1].get('payload')} "
              f"p2.payload={snap[2].get('payload')} p3.payload={snap[3].get('payload')}")

        if not payload_empty(snap[2]):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — filter-matched "
                  f"point 2 (city=par) still carries payload keys after clear: "
                  f"{snap[2].get('payload')}")
            return
        for i in (1, 3):
            if snap[i].get("payload") != base_payloads[i]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — filtered "
                      f"clear collateral-damaged non-matching point {i}: "
                      f"{snap[i].get('payload')} != {base_payloads[i]}")
                return
        for i in (1, 2, 3):
            if not vector_intact(snap[i]):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — vector of "
                      f"point {i} lost after payload clear (clear must not touch vectors)")
                return
        cnt1, _ = count_exact(coll)
        if cnt0 is not None and cnt1 is not None and cnt1 != cnt0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — exact count "
                  f"drifted {cnt0} -> {cnt1} after filtered clear")
            return
        print(f"OK: par point payload cleared; ams/tok payloads deep-equal baseline; "
              f"vectors intact; exact count stable ({cnt0} -> {cnt1})")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
