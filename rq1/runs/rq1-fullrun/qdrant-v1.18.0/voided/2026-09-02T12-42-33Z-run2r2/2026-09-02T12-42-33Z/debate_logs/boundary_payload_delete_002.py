#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_delete_002
# strategy: state_data_preservation_readback (filter-selector face)
# endpoint: payload+delete
# constraint_ids: qdrant_state_payload_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the filter selector branch of
#            delete; scope precision of the listed-key removal judged via readback,
#            not the ack)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state data-preservation readback x qdrant_state_payload_delete_001 (promise:
  "delete removes only the listed keys; all other payload keys stay untouched") —
  the FILTER-selector face (parameter `filter`, typed Filter|null per the endpoint
  spec; structure filter.must[].key + match per request_required_paths
  filter.must.key). One live bpdel2_* collection with 3 points (city=ams/par/tok,
  each also carrying n); delete targets ONLY the filter-matching point
  (city=par) and ONLY key "n" (wait=true). Judged via readback channels:
  (1) scroll with_payload — par point payload exactly {"city":"par"} (n removed,
  city untouched); ams/tok payloads deep-equal baseline (filter over-reach =
  Type4); (2) with_vector — all 3 vectors deep-equal the BASELINE READBACK
  vectors (R27 CRITICAL lesson: Cosine readback is L2-normalized; compare
  readback-vs-baseline-readback only); (3) exact count stays 3. Complements _001
  (points-selector face): both documented selector branches of the same promise
  must behave identically (G9 — inconsistent disposition across selector faces
  is itself a defect signal).
  [chunk_payload+delete coverage: state readback x qdrant_state_payload_delete_001,
  filter-selector face (this script; points-selector face in _001)]
Oracle: with 3 points carrying {"city":..,"n":..}, delete
  {"filter":{"must":[{"key":"city","match":{"value":"par"}}]},"keys":["n"],"wait":true}
  returns 200; scroll afterwards shows the par point payload exactly
  {"city":"par"} ("n" gone, "city" untouched), ams/tok payloads deep-equal
  baseline, all 3 vectors deep-equal the baseline readback vectors, exact count
  stays 3 — "n" residue on the matched point, "city" loss on the matched point,
  collateral change on unmatched points, vector change or count drift each =
  Type4_StateLogicViolation; non-200 on the legal filtered delete =
  Type1_IllegalSuccess; 5xx/transport = Type3_RuntimeFailure with /healthz
  re-check (constraint qdrant_state_payload_delete_001).
Constraint: qdrant_state_payload_delete_001 (bare id) — "delete removes only the
  listed keys; all other payload keys stay untouched" (evidence_tier: explicit;
  level: system)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  payload+delete      -> POST /collections/{collection_name}/points/payload/delete
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


def scroll_snapshot(coll):
    """id -> point dict from points+scroll (with_payload + with_vector).
    Returns (snapshot, ok); ok=False means the readback channel is unusable."""
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


def wait_state(coll, want, tries=6, delay=0.5):
    """Poll scroll readback until every id's payload deep-equals want[id]
    (async grace), or tries run out. Returns the final (snapshot, chan_err)."""
    snap, cerr = scroll_snapshot(coll)
    for _ in range(tries):
        if snap is None:
            break
        ok = all(snap[i].get("payload") == want[i] for i in want if i in snap)
        if ok:
            break
        time.sleep(delay)
        snap, cerr = scroll_snapshot(coll)
    return snap, cerr


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdel2" + tag
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
        # baseline readback (poll until all 3 payloads visible)
        snap0, cerr = wait_state(coll, dict(base_payloads))
        if snap0 is None or any(i not in snap0 for i in (1, 2, 3)):
            print(f"baseline readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        # R27 lesson: compare readback vectors to the BASELINE READBACK vectors
        vec_baseline = {i: snap0[i].get("vector") for i in (1, 2, 3)}
        cnt0, cerr0 = count_exact(coll)
        print(f"baseline: 3 payloads visible, exact count={cnt0}")

        # Act: delete ONLY key "n" from ONLY the filter-matched point (city=par)
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload/delete",
            json={"filter": {"must": [{"key": "city", "match": {"value": "par"}}]},
                  "keys": ["n"]},
            params={"wait": "true"}, timeout=60)
        print(f"delete filter(city=par) keys=[n] -> status={s}")
        print(f"raw: {raw[:600]}")

        # Assert
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on legal filtered delete (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — listed-key delete "
                  f"via a valid filter returned {s}")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal listed-key "
                  f"delete via a valid filter rejected with {s} (promise: the "
                  f"listed-key delete succeeds on valid targets)")
            return

        want = {
            1: dict(base_payloads[1]),             # unmatched: deep-equal baseline
            2: {"city": "par"},                    # matched: n gone, city untouched
            3: dict(base_payloads[3]),
        }
        snap, cerr = wait_state(coll, want)
        if snap is None or any(i not in snap for i in (1, 2, 3)):
            print(f"post-delete readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — readback channel failure, no defect conclusion")
            return
        print(f"post-delete scroll: p1.payload={snap[1].get('payload')} "
              f"p2.payload={snap[2].get('payload')} p3.payload={snap[3].get('payload')}")

        got2 = snap[2].get("payload")
        if got2 != want[2]:
            if isinstance(got2, dict) and "n" in got2:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — listed "
                      f"key 'n' NOT removed from filter-matched point 2: {got2} "
                      f"(promise: the listed key is removed)")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — unlisted "
                      f"key 'city' lost from filter-matched point 2: got {got2}, "
                      f"want {want[2]} (promise: all other payload keys stay "
                      f"untouched)")
            return
        for i in (1, 3):
            if snap[i].get("payload") != base_payloads[i]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — filtered "
                      f"delete (city=par) collateral-damaged unmatched point {i}: "
                      f"{snap[i].get('payload')} != {base_payloads[i]}")
                return
        for i in (1, 2, 3):
            if snap[i].get("vector") != vec_baseline[i]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — vector of "
                      f"point {i} changed after payload-key delete (readback-vs-"
                      f"baseline-readback compare; delete must not touch vectors)")
                return
        cnt1, _ = count_exact(coll)
        if cnt0 is not None and cnt1 is not None and cnt1 != cnt0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — exact count "
                  f"drifted {cnt0} -> {cnt1} after payload-key delete (delete must "
                  f"not delete points)")
            return
        print(f"OK: par point lost exactly 'n' and kept 'city'; ams/tok deep-equal "
              f"baseline; vectors deep-equal baseline readback; exact count stable "
              f"({cnt0} -> {cnt1})")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
