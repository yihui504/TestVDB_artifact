#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_delete_001
# strategy: state_data_preservation_readback (points-selector face)
# endpoint: payload+delete
# constraint_ids: qdrant_state_payload_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — assuming the 200 ack on a
#            selective keys delete means exactly the listed key was removed and
#            nothing else moved; judged via payload readback, not status alone)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state data-preservation readback x qdrant_state_payload_delete_001 (promise:
  "delete removes only the listed keys; all other payload keys stay untouched") —
  the G4 POSITIVE face on the points-selector parameter, with the keys parameter
  exercising the promise's selective core: ONE key of THREE must vanish. One live
  bpdel1_* collection with 3 points each carrying a 3-key payload; delete targets
  ONLY point 1 and ONLY key "city" (wait=true). The promise is judged through
  three independent readback channels (R5/R21 lesson: state, not the ack): (1)
  scroll with_payload readback — point 1 payload must be EXACTLY its two unlisted
  keys (n, tag) deep-equal; residue of "city" OR loss of n/tag on point 1 =
  Type4; points 2/3 payloads deep-equal baseline (selector over-reach = Type4);
  (2) scroll with_vector readback — all 3 vectors deep-equal the BASELINE READBACK
  vectors (R27 CRITICAL lesson: on Cosine collections readback is L2-normalized,
  so compare readback-vs-baseline-readback, never readback-vs-uploaded-raw);
  (3) exact count via points+count — stays exactly 3 (delete must not delete
  points).
  [chunk_payload+delete coverage: state readback x qdrant_state_payload_delete_001,
  points-selector face (this script; filter-selector face in _002, keys/selector
  presence boundary in _003, keys-content idempotency face in _004)]
Oracle: with 3 points carrying {"city","n","tag"} each, delete
  {"points":[1],"keys":["city"],"wait":true} returns 200; afterwards scroll shows
  point 1 payload exactly {"n":..,"tag":..} (both unlisted keys byte-equal
  baseline values, "city" gone), points 2/3 payloads deep-equal baseline, all 3
  vectors deep-equal the baseline readback vectors, exact count stays 3 — "city"
  residue or unlisted-key loss on point 1, collateral change on points 2/3,
  vector change or count drift each = Type4_StateLogicViolation; non-200 on the
  legal delete = Type1_IllegalSuccess (promise: listed-key delete succeeds);
  5xx/transport = Type3_RuntimeFailure with /healthz re-check (constraint
  qdrant_state_payload_delete_001).
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
    coll = "bpdel1" + tag
    base_payloads = {
        1: {"city": "ams", "n": 1, "tag": "alpha"},
        2: {"city": "par", "n": 2, "tag": "beta"},
        3: {"city": "tok", "n": 3, "tag": "gamma"},
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
        # R27 lesson: capture the BASELINE READBACK vectors (Cosine upsert
        # L2-normalizes; never compare readback to the uploaded raw vectors)
        vec_baseline = {i: snap0[i].get("vector") for i in (1, 2, 3)}
        cnt0, cerr0 = count_exact(coll)
        print(f"baseline: 3 payloads visible, exact count={cnt0}")

        # Act: delete ONLY key "city" from ONLY point 1 (wait=true)
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload/delete",
            json={"points": [1], "keys": ["city"]},
            params={"wait": "true"}, timeout=60)
        print(f"delete points=[1] keys=[city] -> status={s}")
        print(f"raw: {raw[:600]}")

        # Assert
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on legal delete (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — listed-key delete "
                  f"on a valid point returned {s}")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal listed-key "
                  f"delete on an existing point rejected with {s} (promise: the "
                  f"listed-key delete succeeds on valid targets)")
            return

        want = {
            1: {"n": 1, "tag": "alpha"},           # city gone, n/tag untouched
            2: dict(base_payloads[2]),             # untargeted: deep-equal baseline
            3: dict(base_payloads[3]),
        }
        snap, cerr = wait_state(coll, want)
        if snap is None or any(i not in snap for i in (1, 2, 3)):
            print(f"post-delete readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — readback channel failure, no defect conclusion")
            return
        print(f"post-delete scroll: p1.payload={snap[1].get('payload')} "
              f"p2.payload={snap[2].get('payload')} p3.payload={snap[3].get('payload')}")

        got1 = snap[1].get("payload")
        if got1 != want[1]:
            if isinstance(got1, dict) and "city" in got1:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — listed "
                      f"key 'city' NOT removed from targeted point 1: {got1} "
                      f"(promise: the listed key is removed)")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — unlisted "
                      f"keys of targeted point 1 damaged: got {got1}, want {want[1]} "
                      f"(promise: all other payload keys stay untouched)")
            return
        for i in (2, 3):
            if snap[i].get("payload") != base_payloads[i]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — delete of "
                      f"point 1/key city collateral-damaged untargeted point {i}: "
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
        print(f"OK: point 1 lost exactly 'city'; n/tag byte-equal; points 2/3 "
              f"deep-equal baseline; vectors deep-equal baseline readback; exact "
              f"count stable ({cnt0} -> {cnt1})")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
