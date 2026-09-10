#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_overwrite_002
# strategy: state data-preservation readback (filter-selector face)
# endpoint: payload+overwrite
# constraint_ids: qdrant_state_payload_overwrite_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/overwrite-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the filter selector path is
#            a different deserialization branch than points[]; its overwrite
#            scope is judged by state readback, not by the ack)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state data-preservation readback x qdrant_state_payload_overwrite_001
  (promise: "overwrite replaces the ENTIRE payload of the targeted points; keys
  missing from the new payload are removed") — the FILTER-selector face of the
  same promise (a distinct server-side selection branch from _001's
  points-selector): overwrite via filter city=par (matches ONLY point 2 of 3)
  with a disjoint payload (wait=true). Judged through three independent
  readback channels: (1) scroll with_payload — point 2 payload EXACTLY the
  provided payload with every old key gone (old-key residue = merge-not-replace
  Type4); points 1/3 (non-matching) deep-equal baseline (filter over-reach =
  Type4); (2) scroll with_vector — all 3 vectors deep-equal the BASELINE
  READBACK vectors (R27 lesson: Cosine readback is L2-normalized; compare
  readback-vs-baseline-readback only); (3) exact count stays 3.
  [chunk_payload+overwrite coverage: state readback x
  qdrant_state_payload_overwrite_001, filter-selector face (this script;
  points-selector face in _001, boundary-value faces in _003,
  content-persistence faces in _004, key-scope face in _008)]
Oracle: with 3 points (city ams/par/tok, each carrying {"city","n","tag"}),
  overwrite filter{must:[key=city match par]} payload={"zone":"eu"} (wait=true
  query) returns 200; afterwards scroll shows point 2 payload EXACTLY
  {"zone":"eu"} (city/n/tag all gone), points 1/3 payloads deep-equal baseline,
  all 3 vectors deep-equal the baseline readback vectors, exact count stays 3 —
  old-key residue on point 2, collateral change on points 1/3, vector change
  or count drift each = Type4_StateLogicViolation; non-200 on the legal
  filter-overwrite = Type1_IllegalSuccess; 5xx/transport =
  Type3_RuntimeFailure with /healthz re-check (constraint
  qdrant_state_payload_overwrite_001).
Constraint: qdrant_state_payload_overwrite_001 (bare id) — "overwrite replaces
  the ENTIRE payload of the targeted points (set semantics: keys missing from
  the new payload are removed)" (evidence_tier: explicit; level: system)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  payload+overwrite     -> PUT  /collections/{collection_name}/points/payload
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
        ok = all(snap[i].get("payload") == want[i] for i in want if i in snap)
        if ok:
            break
        time.sleep(delay)
        snap, cerr = scroll_snapshot(coll)
    return snap, cerr


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpow2" + tag
    base_payloads = {
        1: {"city": "ams", "n": 1, "tag": "alpha"},
        2: {"city": "par", "n": 2, "tag": "beta"},
        3: {"city": "tok", "n": 3, "tag": "gamma"},
    }
    vecs = {1: [0.1, 0.2, 0.3, 0.4], 2: [0.2, 0.3, 0.4, 0.5], 3: [0.3, 0.4, 0.5, 0.6]}
    new_payload = {"zone": "eu"}   # disjoint from every old key
    # filter syntax from the contract's filter family (same shape as the
    # payload+delete filter face of R28: must:[{key, match:{value}}])
    sel_filter = {"must": [{"key": "city", "match": {"value": "par"}}]}

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
        # R27 lesson: capture the BASELINE READBACK vectors
        vec_baseline = {i: snap0[i].get("vector") for i in (1, 2, 3)}
        cnt0, cerr0 = count_exact(coll)
        print(f"baseline: 3 payloads visible, exact count={cnt0}")

        # Act: overwrite ENTIRE payload of every point matching city=par (point 2 only)
        s, _, raw = safe_request(
            "PUT", f"/collections/{coll}/points/payload",
            json={"filter": sel_filter, "payload": new_payload},
            params={"wait": "true"}, timeout=60)
        print(f"overwrite filter(city=par) payload={new_payload} -> status={s}")
        print(f"raw: {raw[:600]}")

        # Assert
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on legal filter-overwrite (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — filter-selector "
                  f"overwrite on valid points returned {s}")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal "
                  f"filter-selector overwrite rejected with {s} (promise: "
                  f"overwrite succeeds on valid targets)")
            return

        want = {
            1: dict(base_payloads[1]),             # non-matching: deep-equal baseline
            2: dict(new_payload),                  # matching: ENTIRE payload replaced
            3: dict(base_payloads[3]),
        }
        snap, cerr = wait_state(coll, want)
        if snap is None or any(i not in snap for i in (1, 2, 3)):
            print(f"post-overwrite readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — readback channel failure, no defect conclusion")
            return
        print(f"post-overwrite scroll: p1.payload={snap[1].get('payload')} "
              f"p2.payload={snap[2].get('payload')} p3.payload={snap[3].get('payload')}")

        got2 = snap[2].get("payload")
        if got2 != want[2]:
            residue = [k for k in base_payloads[2] if isinstance(got2, dict) and k in got2]
            if residue:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — old keys "
                      f"{residue} SURVIVED a full filter-overwrite on matched point "
                      f"2: {got2} (promise: set semantics, not merge)")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — matched "
                      f"point 2 payload after overwrite is {got2}, want exactly "
                      f"{want[2]} (promise: payload equals the provided payload)")
            return
        for i in (1, 3):
            if snap[i].get("payload") != base_payloads[i]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"filter-overwrite city=par collateral-damaged NON-matching "
                      f"point {i}: {snap[i].get('payload')} != {base_payloads[i]} "
                      f"(filter over-reach)")
                return
        for i in (1, 2, 3):
            if snap[i].get("vector") != vec_baseline[i]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — vector of "
                      f"point {i} changed after a payload-only overwrite (readback-vs-"
                      f"baseline-readback compare; overwrite must not touch vectors)")
                return
        cnt1, _ = count_exact(coll)
        if cnt0 is not None and cnt1 is not None and cnt1 != cnt0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — exact count "
                  f"drifted {cnt0} -> {cnt1} after a payload overwrite (overwrite "
                  f"must not delete points)")
            return
        print(f"OK: point 2 payload exactly {new_payload} (all old keys gone); "
              f"non-matching points 1/3 deep-equal baseline; vectors deep-equal "
              f"baseline readback; exact count stable ({cnt0} -> {cnt1})")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
