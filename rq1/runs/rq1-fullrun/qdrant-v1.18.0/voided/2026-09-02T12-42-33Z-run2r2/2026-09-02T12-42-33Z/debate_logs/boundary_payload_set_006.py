#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_set_006
# strategy: state data-preservation readback (points-selector face, merge semantics)
# endpoint: payload+set
# constraint_ids: qdrant_state_payload_set_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/set-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — assuming the 200 ack on a
#            points-targeted set-payload means exactly the targeted point got
#            exactly the merge documented; judged via payload readback, not
#            the ack alone)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state data-preservation readback x qdrant_state_payload_set_001 —
  the G4 POSITIVE face on the points-selector parameter: "points OR filter
  must identify the targets". Three points carry distinct 3-key payloads;
  set-payload points=[2] with a 2-key payload that BOTH adds a new key and
  UPDATES an existing key's value (wait=true query) — the documented merge
  semantics (R29 reflection: set "updates specific fields while keeping
  others unchanged", contrasted with PUT overwrite = replace). The promise
  is judged through four independent readback channels (R5/R21: judge the
  state, not the ack): (1) scroll with_payload — point 2 payload must be
  the deep-merged dict (new key present, updated key replaced, EVERY other
  old key unchanged); merge-to-replace (old untouched keys dropped) =
  Type4, any value distortion = Type4; (2) untargeted points 1/3 payloads
  deep-equal baseline (selector over-reach = Type4); (3) scroll with_vector
  — all 3 vectors deep-equal the BASELINE READBACK vectors (R27 lesson:
  Cosine collections normalize at upsert — compare readback-vs-baseline-
  readback only); (4) exact count via points+count stays exactly 3.
  [chunk_payload+set coverage: state data-preservation readback x
  qdrant_state_payload_set_001, points-selector face (this script;
  filter-selector face in boundary_payload_set_007, selector-degenerate faces
  in boundary_payload_set_008)]
Oracle: with 3 points carrying {"city","n","tag"} each, set-payload
  points=[2] payload={"city":"gif","lang":"nl"} (wait=true query) returns
  200; afterwards scroll shows point 2 payload EXACTLY {"city":"gif",
  "lang":"nl","n":2,"tag":"beta"} (merge: new key added, city updated, n+tag
  kept byte-equal), points 1/3 payloads deep-equal baseline, all 3 vectors
  deep-equal the baseline readback vectors, exact count stays 3 —
  dropped-old-key (merge-as-replace), value distortion, collateral change
  on points 1/3, vector change, or count drift each =
  Type4_StateLogicViolation; non-200 on the legal points-targeted set =
  Type1_IllegalSuccess (promise: points list identifies targets and the set
  succeeds); 5xx/transport = Type3_RuntimeFailure with /healthz re-check
  (constraint qdrant_state_payload_set_001).
Constraint: qdrant_state_payload_set_001 (bare id) — "payload targets:
  exactly one of points-list or filter must identify targets; both null is
  rejected" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  payload+set           -> POST /collections/{collection_name}/points/payload
  points+upsert         -> PUT  /collections/{collection_name}/points
  points+scroll         -> POST /collections/{collection_name}/points/scroll
  points+count          -> POST /collections/{collection_name}/points/count
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


def scroll_snapshot(coll):
    """id -> point dict from points+scroll (with_payload + with_vector).
    Returns (snapshot, chan_err); None snapshot means the channel is unusable."""
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
    (async grace). Returns the final (snapshot, chan_err)."""
    snap, cerr = scroll_snapshot(coll)
    for _ in range(tries):
        if snap is None:
            break
        if all(snap[i].get("payload") == want[i] for i in want if i in snap):
            break
        time.sleep(delay)
        snap, cerr = scroll_snapshot(coll)
    return snap, cerr


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpset4" + tag
    base_payloads = {
        1: {"city": "ams", "n": 1, "tag": "alpha"},
        2: {"city": "par", "n": 2, "tag": "beta"},
        3: {"city": "tok", "n": 3, "tag": "gamma"},
    }
    vecs = {1: [0.1, 0.2, 0.3, 0.4], 2: [0.2, 0.3, 0.4, 0.5], 3: [0.3, 0.4, 0.5, 0.6]}
    # merge payload: adds "lang" AND updates "city"; "n"/"tag" must survive
    merge_payload = {"city": "gif", "lang": "nl"}

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

        # Act: MERGE payload onto point 2 via the points-selector
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload",
            json={"points": [2], "payload": dict(merge_payload)},
            params={"wait": "true"}, timeout=60)
        print(f"set-payload points=[2] payload={merge_payload} -> status={s}")
        print(f"raw: {raw[:600]}")

        # Assert
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on legal points-targeted set (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — set-payload "
                  f"on a valid point returned {s}")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal "
                  f"points-targeted set-payload on an existing point rejected "
                  f"with {s} (promise: points list identifies targets, set succeeds)")
            return

        want = {
            1: dict(base_payloads[1]),             # untargeted: deep-equal baseline
            2: {"city": "gif", "lang": "nl", "n": 2, "tag": "beta"},  # deep-merged
            3: dict(base_payloads[3]),
        }
        snap, cerr = wait_state(coll, want)
        if snap is None or any(i not in snap for i in (1, 2, 3)):
            print(f"post-set readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — readback channel failure, no defect conclusion")
            return
        print(f"post-set scroll: p1={snap[1].get('payload')} "
              f"p2={snap[2].get('payload')} p3={snap[3].get('payload')}")

        got2 = snap[2].get("payload")
        if got2 != want[2]:
            if isinstance(got2, dict):
                dropped = [k for k in ("n", "tag") if k not in got2]
                if dropped:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"untouched keys {dropped} DROPPED by set-payload on "
                          f"point 2: {got2} (documented set semantics: updates "
                          f"specific fields while keeping others unchanged — "
                          f"merge, not replace)")
                else:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"point 2 payload after set is {got2}, want exactly "
                          f"{want[2]} (merge promise violated)")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"point 2 payload after set is {got2!r}, want exactly "
                      f"{want[2]}")
            return
        for i in (1, 3):
            if snap[i].get("payload") != base_payloads[i]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"set-payload targeted at point 2 collateral-damaged "
                      f"untargeted point {i}: {snap[i].get('payload')} != "
                      f"{base_payloads[i]} (points selector over-reach)")
                return
        for i in (1, 2, 3):
            if snap[i].get("vector") != vec_baseline[i]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — vector "
                      f"of point {i} changed after a payload-only set (readback-"
                      f"vs-baseline-readback compare; set must not touch vectors)")
                return
        cnt1, _ = count_exact(coll)
        if cnt0 is not None and cnt1 is not None and cnt1 != cnt0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — exact "
                  f"count drifted {cnt0} -> {cnt1} after a payload set (set "
                  f"must not delete points)")
            return
        print(f"OK: point 2 payload deep-merged to {want[2]}; points 1/3 "
              f"deep-equal baseline; vectors deep-equal baseline readback; "
              f"exact count stable ({cnt0} -> {cnt1})")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
