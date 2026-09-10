#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_set_008
# strategy: strategy1 boundary-value attack (selector degenerates: both-absent, both-null, empty-points) + OR-control
# endpoint: payload+set
# constraint_ids: qdrant_state_payload_set_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/set-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the degenerate corners of
#            the selector promise: a body with NO selector at all, a body
#            with BOTH selectors explicitly null, and an empty points list;
#            plus the one-sided control that pins the promise to BOTH-null)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value x qdrant_state_payload_set_001 — the
  degenerate corners of "points OR filter must identify the targets; both
  absent (null) is an error". Face A (both selectors ABSENT): body
  {"payload":{"ghost":1}} with no points and no filter — both optional in
  the published OpenAPI v1.18.0 SetPayload schema, so the body is
  schema-valid but licenses no selector; the constraint explicitly declares
  both-null an ERROR -> expect 4xx. Face B (both selectors EXPLICIT NULL):
  {"points":null,"filter":null,"payload":{...}} — the constraint's verbatim
  "both null" case -> expect 4xx. A 200 on A or B is sub-judged by scroll
  readback: state CHANGED on any point = Type4 (a selector-less mass
  broadcast licensed by no documented selector semantics); state unchanged
  = Type1_IllegalSuccess (a body the spec explicitly calls an error was
  200-accepted). Face C (empty points list, posture per R28 — no
  empty-array rejection norm): {"points":[],"payload":{...}} — trichotomy:
  4xx = clean rejection (OK); 200 no-op = vacuous-op family posture
  (NOTE); 200 with state change = Type4 (an empty selector licenses no
  targeting). Face D (one-sided OR control): {"points":[1],"filter":null,
  "payload":{...}} -> expect 200 with the merge on point 1 ONLY — this pins
  the error condition to BOTH-null rather than any-null (a 4xx here would
  mean the documented OR disjunction is not honored; typed as the promise's
  inverse = Type1_IllegalSuccess face). Final sweep: payloads deep-equal
  the post-D expected state. Error-naming quality on 4xx faces is NOTE
  only (R29 lesson: Type2 error-naming has NO anchor).
  [chunk_payload+set coverage: strategy1 boundary-value x
  qdrant_state_payload_set_001, selector-degenerate + OR-control faces
  (this script; points-selector face in boundary_payload_set_006,
  filter-selector face in boundary_payload_set_007)]
Oracle: face A (payload only, no selector) returns 4xx; face B
  (points=null, filter=null) returns 4xx — on either, a 200 with readback
  state changed on ANY point = Type4_StateLogicViolation (selector-less
  mass broadcast) and a 200 with state unchanged = Type1_IllegalSuccess
  (explicitly-errored body accepted); face C (points=[]) returns 4xx or a
  200 no-op (both acceptable; 200 no-op = NOTE, R28 posture) — 200 with
  state change = Type4; face D (points=[1], filter=null) returns 200 with
  the merge landing on point 1 only (points 2/3 deep-equal baseline) —
  non-200 = Type1_IllegalSuccess (documented OR disjunction rejected);
  5xx/transport = Type3_RuntimeFailure with /healthz re-check (constraint
  qdrant_state_payload_set_001).
Constraint: qdrant_state_payload_set_001 (bare id) — "payload targets:
  exactly one of points-list or filter must identify targets; both null is
  rejected" (evidence_tier: explicit; level: endpoint)

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
    coll = "bpset6" + tag
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
        pls, cerr = wait_payloads(coll, dict(base_payloads))
        if pls is None or any(pls.get(i) != base_payloads[i] for i in (1, 2, 3)):
            print(f"baseline readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        print("baseline: 3 payloads visible via scroll")

        # ---- Face A: both selectors ABSENT ----
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload",
            json={"payload": {"ghost": 1}},
            params={"wait": "true"}, timeout=60)
        print(f"\nface A selector-less (payload only) -> status={s}")
        print(f"raw: {raw[:500]}")
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on selector-less body (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — face A triggered server error {s}")
            return
        if s in (400, 422):
            low = raw.lower()
            names = [w for w in ("point", "filter", "selector") if w in low]
            print(f"face A cleanly rejected with {s} (mentions: {names or 'no selector word'} — NOTE only, R29)")
        elif 200 <= s <= 299:
            changed, pls_a = readback_changed(coll, base_payloads)
            if changed is None:
                print("VERDICT: SCRIPT_ERROR — readback channel failure on face A")
                return
            if changed:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — face A: "
                      f"selector-less set-payload was 200-accepted AND changed "
                      f"payload state of points {changed}: {pls_a} (baseline "
                      f"{base_payloads}) — a selector-less request licenses no "
                      f"documented targeting; a mass broadcast is a destructive "
                      f"undocumented default (constraint: both absent is an error)")
                return
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — face A: "
                  f"selector-less body 200-accepted (state unchanged) although the "
                  f"constraint explicitly declares both-absent an error")
            return
        else:
            print(f"NOTE: face A returned unexpected status {s}; recorded for the judge")

        # ---- Face B: both selectors EXPLICIT NULL ----
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload",
            json={"points": None, "filter": None, "payload": {"ghost": 2}},
            params={"wait": "true"}, timeout=60)
        print(f"\nface B points=null filter=null -> status={s}")
        print(f"raw: {raw[:500]}")
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on both-null body (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — face B triggered server error {s}")
            return
        if s in (400, 422):
            low = raw.lower()
            names = [w for w in ("point", "filter", "selector") if w in low]
            print(f"face B cleanly rejected with {s} (mentions: {names or 'no selector word'} — NOTE only, R29)")
        elif 200 <= s <= 299:
            changed, pls_b = readback_changed(coll, base_payloads)
            if changed is None:
                print("VERDICT: SCRIPT_ERROR — readback channel failure on face B")
                return
            if changed:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — face B: "
                      f"points=null+filter=null set-payload was 200-accepted AND "
                      f"changed payload state of points {changed}: {pls_b} "
                      f"(constraint verbatim: both null is rejected — a null-null "
                      f"selector broadcast is undocumented destructive behavior)")
                return
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — face B: "
                  f"points=null+filter=null body 200-accepted (state unchanged) "
                  f"although the constraint explicitly declares both-null an error")
            return
        else:
            print(f"NOTE: face B returned unexpected status {s}; recorded for the judge")

        # ---- Face C: empty points list (R28 posture) ----
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload",
            json={"points": [], "payload": {"ghost": 3}},
            params={"wait": "true"}, timeout=60)
        print(f"\nface C points=[] -> status={s}")
        print(f"raw: {raw[:500]}")
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on empty-points body (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — face C triggered server error {s}")
            return
        if s in (400, 422):
            print(f"face C cleanly rejected with {s} (acceptable posture)")
        elif 200 <= s <= 299:
            changed, pls_c = readback_changed(coll, base_payloads)
            if changed is None:
                print("VERDICT: SCRIPT_ERROR — readback channel failure on face C")
                return
            if changed:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — face C: "
                      f"points=[] set-payload was 200-accepted AND changed payload "
                      f"state of points {changed}: {pls_c} (an empty selector "
                      f"licenses no documented targeting)")
                return
            print("face C OK: 200 no-op ack, state unchanged (vacuous-op family posture, R28)")
        else:
            print(f"NOTE: face C returned unexpected status {s}; recorded for the judge")

        # ---- Face D: one-sided OR control (points identifies, filter null) ----
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload",
            json={"points": [1], "filter": None, "payload": {"lang": "nl"}},
            params={"wait": "true"}, timeout=60)
        print(f"\nface D points=[1] filter=null -> status={s}")
        print(f"raw: {raw[:500]}")
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on one-sided OR body (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — face D triggered server error {s}")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — face D: "
                  f"points=[1] with filter=null rejected with {s} (promise: points "
                  f"OR filter — ONE identifying selector suffices; the error "
                  f"condition is BOTH-null, not any-null)")
            return
        want_d = {
            1: {"city": "ams", "n": 1, "lang": "nl"},  # merged
            2: dict(base_payloads[2]),
            3: dict(base_payloads[3]),
        }
        pls_d, cerr_d = wait_payloads(coll, want_d)
        if pls_d is None:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr_d)[:300]}")
            return
        if pls_d.get(1) != want_d[1]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — face D: "
                  f"point 1 payload is {pls_d.get(1)}, want exactly {want_d[1]} "
                  f"(one-sided OR merge promise violated)")
            return
        if pls_d.get(2) != base_payloads[2] or pls_d.get(3) != base_payloads[3]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — face D: "
                  f"points=[1] targeted set collateral-damaged untargeted points: "
                  f"{pls_d}")
            return
        print("face D OK: merge landed on point 1 only; points 2/3 deep-equal baseline")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
