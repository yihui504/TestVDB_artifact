#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_set_007
# strategy: state data-preservation readback (filter-selector face, broadcast-to-matched-set)
# endpoint: payload+set
# constraint_ids: qdrant_state_payload_set_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/set-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — assuming the 200 ack on a
#            filter-targeted set-payload means exactly the MATCHED points got
#            the merge; a filter selector is a broadcast, so over-reach and
#            under-reach are both state defects, judged via readback)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state data-preservation readback x qdrant_state_payload_set_001 —
  the G4 POSITIVE face on the filter-selector parameter: "points OR filter
  must identify the targets". Three points carry distinct payloads; a
  filter (must: match city in {ams, tok}) identifies TWO of them;
  set-payload with that filter merges a new key onto the targets (wait=true
  query). The promise is judged through readback channels (R5/R21: judge
  the state, not the ack): (1) both MATCHED points get the deep-merged
  payload (new key added, every old key kept byte-equal — the documented
  merge semantics, R29: set "updates specific fields while keeping others
  unchanged"); (2) the UNMATCHED point stays deep-equal baseline — a
  filter-selector broadcast touching the unmatched point = selector
  over-reach (Type4); either matched point missing the merge = selector
  under-reach (Type4); (3) exact count via points+count stays exactly 3.
  The filter itself is pre-validated through scroll-with-filter (channel
  attributability: the filter matches exactly {1,3} before the mutation,
  so any post-mutation discrepancy is the selector's doing, not the
  filter's).
  [chunk_payload+set coverage: state data-preservation readback x
  qdrant_state_payload_set_001, filter-selector face (this script;
  points-selector face in boundary_payload_set_006, selector-degenerate faces
  in boundary_payload_set_008)]
Oracle: with 3 points carrying {"city","n"} each and the filter
  must:[match city in {ams,tok}] matching exactly points 1 and 3
  (pre-validated via scroll), set-payload filter=<that filter>
  payload={"lang":"nl"} (wait=true query) returns 200; afterwards scroll
  shows points 1/3 payloads deep-merged to {...baseline, "lang":"nl"} and
  point 2 payload deep-equal baseline; exact count stays 3 — a matched
  point left unmerged (under-reach), the unmatched point touched
  (over-reach), an old key dropped on a matched point (merge-as-replace),
  or count drift each = Type4_StateLogicViolation; non-200 on the legal
  filter-targeted set = Type1_IllegalSuccess (promise: filter identifies
  targets, set succeeds); 5xx/transport = Type3_RuntimeFailure with
  /healthz re-check (constraint qdrant_state_payload_set_001).
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


def scroll_ids_by_filter(coll, flt):
    """Sorted id list of points matching flt via scroll (filtering channel).
    Returns (ids, chan_err); None ids means channel unusable."""
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points/scroll",
        json={"limit": 100, "with_payload": False, "filter": flt}, timeout=30)
    if s != 200 or not isinstance(body, dict):
        return None, (s, raw)
    res = body.get("result")
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        return None, (s, raw)
    return sorted(p.get("id") for p in pts if isinstance(p, dict)), (s, raw)


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
    coll = "bpset5" + tag
    base_payloads = {
        1: {"city": "ams", "n": 1},
        2: {"city": "par", "n": 2},
        3: {"city": "tok", "n": 3},
    }
    vecs = {1: [0.1, 0.2, 0.3, 0.4], 2: [0.2, 0.3, 0.4, 0.5], 3: [0.3, 0.4, 0.5, 0.6]}
    selector_flt = {"must": [{"key": "city", "match": {"any": ["ams", "tok"]}}]}
    merge_payload = {"lang": "nl"}

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
        pls, cerr = wait_payloads(coll, dict(base_payloads))
        if pls is None or any(pls.get(i) != base_payloads[i] for i in (1, 2, 3)):
            print(f"baseline readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        # channel attributability: the selector filter must match exactly {1,3}
        ids, ferr = scroll_ids_by_filter(coll, selector_flt)
        if ids is None:
            fs, fraw = ferr
            print(f"selector pre-validation unusable: status={fs} {str(fraw)[:300]}")
            print("VERDICT: SCRIPT_ERROR — filter channel failure, no defect conclusion")
            return
        print(f"selector pre-validation: filter matches ids={ids}")
        if ids != [1, 3]:
            print(f"VERDICT: SCRIPT_ERROR — selector filter matched {ids}, want "
                  f"[1, 3]; test vector does not isolate the selector")
            return
        cnt0, _ = count_exact(coll)
        print(f"baseline: 3 payloads visible, exact count={cnt0}")

        # Act: MERGE payload onto the filter-matched targets (points 1 and 3)
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload",
            json={"filter": selector_flt, "payload": dict(merge_payload)},
            params={"wait": "true"}, timeout=60)
        print(f"set-payload filter(city in [ams,tok]) payload={merge_payload} -> status={s}")
        print(f"raw: {raw[:600]}")

        # Assert
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on legal filter-targeted set (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — filter-targeted "
                  f"set-payload returned {s}")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal "
                  f"filter-targeted set-payload on matched points rejected with "
                  f"{s} (promise: filter identifies targets, set succeeds)")
            return

        want = {
            1: {"city": "ams", "n": 1, "lang": "nl"},   # matched: deep-merged
            2: {"city": "par", "n": 2},                 # unmatched: baseline
            3: {"city": "tok", "n": 3, "lang": "nl"},   # matched: deep-merged
        }
        pls, cerr = wait_payloads(coll, want)
        if pls is None or any(i not in pls for i in (1, 2, 3)):
            print(f"post-set readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — readback channel failure, no defect conclusion")
            return
        print(f"post-set scroll: p1={pls.get(1)} p2={pls.get(2)} p3={pls.get(3)}")

        for i in (1, 3):
            got = pls.get(i)
            if got != want[i]:
                if isinstance(got, dict) and "lang" not in got:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"filter-IDENTIFIED point {i} left unmerged (selector "
                          f"under-reach): {got}, want {want[i]}")
                elif isinstance(got, dict) and "lang" in got and "city" not in got:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"matched point {i} payload replaced instead of merged "
                          f"(merge-as-replace): {got}, want {want[i]}")
                else:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"matched point {i} payload is {got}, want exactly "
                          f"{want[i]}")
                return
        if pls.get(2) != base_payloads[2]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                  f"set-payload filter (city in [ams,tok]) collateral-damaged "
                  f"UNMATCHED point 2: {pls.get(2)} != {base_payloads[2]} "
                  f"(filter selector over-reach)")
            return
        cnt1, _ = count_exact(coll)
        if cnt0 is not None and cnt1 is not None and cnt1 != cnt0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — exact "
                  f"count drifted {cnt0} -> {cnt1} after a filter-targeted "
                  f"payload set (set must not delete points)")
            return
        print(f"OK: matched points 1/3 deep-merged; unmatched point 2 deep-equal "
              f"baseline; exact count stable ({cnt0} -> {cnt1})")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
