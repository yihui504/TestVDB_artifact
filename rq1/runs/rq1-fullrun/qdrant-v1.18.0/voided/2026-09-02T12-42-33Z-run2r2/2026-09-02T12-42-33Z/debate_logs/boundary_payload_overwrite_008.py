#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_overwrite_008
# strategy: state replacement-scope boundary (key-scoped overwrite — the [SPEC] nested-path parameter)
# endpoint: payload+overwrite
# constraint_ids: qdrant_state_payload_overwrite_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/overwrite-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the key parameter rides
#            the same SetPayload wire schema; whether the server really
#            narrows the replacement scope to the path is only provable by
#            readback of the keys OUTSIDE the path)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state replacement-scope boundary x qdrant_state_payload_overwrite_001
  — the [SPEC] key parameter of payload+overwrite ("assign payload at this
  nested property path", published OpenAPI v1.18.0 SetPayload.key:
  string|null). The state constraint promises replacement of the ENTIRE
  payload of the targeted points; the key parameter's documented meaning
  NARROWS the assignment scope to the given property path — so the scope
  boundary of the promise is: keys OUTSIDE the path must SURVIVE a key-scoped
  overwrite, while the subtree AT the path is replaced (set semantics, the
  bc replace-not-merge contract at subtree granularity). Three faces:
  (A) key="nested" on an EXISTING subtree — p1 {"keep","nested":{old,sub}}
  overwritten at path with {"new":2} must become exactly
  {"keep":"me","nested":{"new":2}} — top-level "keep" lost = scope
  over-reach (Type4), nested old/sub surviving = merge-at-path (Type4);
  (B) key="brand.new.path" on a NONEXISTENT deep path — creation semantics
  (dotted-path nesting vs literal key) is recorded as observed, but
  preservation is strict: "keep" and the post-A "nested" subtree must be
  byte-equal and the provided payload must land somewhere reachable;
  (C) key="" (empty-string boundary) on p2 — either clean 4xx, or 200 with
  root-assignment (payload exactly the provided one) or no-op (baseline);
  anything else = Type4. Sentinel discipline: the non-targeted point is
  deep-equal-checked in every case.
  [chunk_payload+overwrite coverage: replacement-scope boundary x
  qdrant_state_payload_overwrite_001 + bc replace-not-merge at subtree
  granularity, key=[existing-path, nonexistent-deep-path, empty-string]
  faces (this script; whole-payload faces in _001-_004, _007)]
Oracle: case A — overwrite {"payload":{"new":2},"points":[1],"key":"nested"}
  (wait=true query) returns 200 and scroll shows p1 EXACTLY
  {"keep":"me","nested":{"new":2}} ("keep" gone = Type4 scope over-reach to
  the whole payload; nested old/sub surviving = Type4 merge-at-path); p2
  deep-equal baseline. case B — key="brand.new.path": 4xx = NOTE ladder
  (creation semantics implementation-defined); 200 requires "keep" and
  "nested"=={"new":2} byte-equal AND {"v":1} reachable at the dotted path or
  under the literal key — loss of any pre-existing top-level key = Type4.
  case C — key="": 4xx = clean reject OK; 200 requires p2 exactly
  {"fresh":1} (root assignment) or exactly baseline {"solo":"top"} (no-op),
  anything else = Type4; p1 byte-equal its post-B value. non-200 on A =
  Type1_IllegalSuccess (documented [SPEC] parameter rejected); 5xx/transport
  = Type3_RuntimeFailure with /healthz re-check (constraint
  qdrant_state_payload_overwrite_001).
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


def wait_payload(coll, pid, want, tries=6, delay=0.5):
    """Poll scroll readback until point pid's payload deep-equals want.
    Returns (found, payload, chan_err); found=False means channel unusable
    or point missing (payload itself may be None)."""
    pls, cerr = scroll_payloads(coll)
    for _ in range(tries):
        if pls is None or pid not in pls:
            return False, None, cerr
        if pls.get(pid) == want:
            return True, pls.get(pid), cerr
        time.sleep(delay)
        pls, cerr = scroll_payloads(coll)
    if pls is None or pid not in pls:
        return False, None, cerr
    return True, pls.get(pid), cerr


def walk_path(payload, dotted):
    """Walk a dotted property path. Returns (value, found)."""
    node = payload
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None, False
    return node, True


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpow8" + tag
    base_payloads = {
        1: {"keep": "me", "nested": {"old": 1, "sub": "x"}},
        2: {"solo": "top"},
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

        # ---- Case A: key-scoped overwrite on an EXISTING subtree ----
        want_a = {"keep": "me", "nested": {"new": 2}}
        s, _, raw = safe_request(
            "PUT", f"/collections/{coll}/points/payload",
            json={"points": [1], "payload": {"new": 2}, "key": "nested"},
            params={"wait": "true"}, timeout=60)
        print(f"\ncase A key=nested -> status={s}")
        print(f"raw: {raw[:500]}")
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on key-scoped overwrite (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — case A returned {s}")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — case A: the "
                  f"documented [SPEC] key parameter was rejected with {s} on an "
                  f"existing path (promise: overwrite succeeds on valid targets)")
            return
        found, got, cerr = wait_payload(coll, 1, want_a)
        if not found:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr)[:300]}")
            return
        if got != want_a:
            if got == {"new": 2}:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case A: "
                      f"key-scoped overwrite OVER-REACHED and replaced the WHOLE "
                      f"payload (readback {got}) — the sibling top-level key 'keep' "
                      f"was destroyed; the [SPEC] key parameter narrows the "
                      f"assignment scope to the path")
            elif isinstance(got, dict) and got.get("nested") == {"old": 1, "sub": "x", "new": 2}:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case A: "
                      f"key-scoped overwrite MERGED at the path (readback {got}) — "
                      f"old subtree keys survived; overwrite is set/replace "
                      f"semantics, not merge")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case A: "
                      f"p1 payload is {got}, want exactly {want_a}")
            return
        pls_s, cerr_s = scroll_payloads(coll)
        if pls_s is None:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr_s)[:300]}")
            return
        if pls_s.get(2) != base_payloads[2]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case A: "
                  f"key-scoped overwrite on p1 collateral-damaged p2: "
                  f"{pls_s.get(2)} != {base_payloads[2]}")
            return
        print("case A OK: subtree replaced at path; 'keep' survived; p2 sentinel intact")

        # ---- Case B: key on a NONEXISTENT deep path ----
        deep = "brand.new.path"
        s, _, raw = safe_request(
            "PUT", f"/collections/{coll}/points/payload",
            json={"points": [1], "payload": {"v": 1}, "key": deep},
            params={"wait": "true"}, timeout=60)
        print(f"\ncase B key={deep} (nonexistent) -> status={s}")
        print(f"raw: {raw[:500]}")
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on nonexistent-path key (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — case B returned {s}")
            return
        last_p1 = want_a  # post-A state; case B starts from here
        if s in (400, 422):
            print(f"NOTE: case B nonexistent-path key rejected with {s} — "
                  f"creation semantics implementation-defined; recorded for the "
                  f"judge; p1 assumed unchanged (verified below)")
        elif s == 200:
            time.sleep(0.5)  # async grace before single readback
            pls_b, cerr_b = scroll_payloads(coll)
            if pls_b is None or 1 not in pls_b:
                print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr_b)[:300]}")
                return
            got = pls_b.get(1)
            if not isinstance(got, dict) or got.get("keep") != "me" \
                    or got.get("nested") != {"new": 2}:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case B: "
                      f"key-scoped overwrite on a nonexistent path DAMAGED "
                      f"pre-existing state: {got} (want 'keep' and nested=new:2 "
                      f"byte-equal preserved)")
                return
            dotted_val, dotted_ok = walk_path(got, deep)
            literal_val = got.get(deep) if isinstance(got, dict) else None
            if not (dotted_ok and dotted_val == {"v": 1}) and literal_val != {"v": 1}:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case B: "
                      f"200-accepted but the provided payload is unreachable "
                      f"(dotted={dotted_val!r}, literal={literal_val!r}): {got}")
                return
            where = "dotted path" if (dotted_ok and dotted_val == {"v": 1}) else "literal key"
            last_p1 = got
            print(f"case B OK: pre-existing state preserved; payload landed at {where}")
            pls_s2, cerr_s2 = scroll_payloads(coll)
            if pls_s2 is None:
                print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr_s2)[:300]}")
                return
            if pls_s2.get(2) != base_payloads[2]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case B: "
                      f"p2 sentinel damaged: {pls_s2.get(2)} != {base_payloads[2]}")
                return
        else:
            print(f"NOTE: case B returned {s} (unexpected status family); recorded "
                  f"for the judge; p1 assumed unchanged (verified below)")

        # verify case B left p1 unchanged when rejected, or at its recorded value
        pls_v, cerr_v = scroll_payloads(coll)
        if pls_v is None or pls_v.get(1) != last_p1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case B: p1 "
                  f"post-state {pls_v.get(1) if pls_v else None} != expected "
                  f"{last_p1} (rejected/unplaced request must not alter state)")
            return

        # ---- Case C: key="" (empty-string boundary) on p2 ----
        s, _, raw = safe_request(
            "PUT", f"/collections/{coll}/points/payload",
            json={"points": [2], "payload": {"fresh": 1}, "key": ""},
            params={"wait": "true"}, timeout=60)
        print(f"\ncase C key=\"\" -> status={s}")
        print(f"raw: {raw[:500]}")
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on empty-key overwrite (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — case C returned {s}")
            return
        if s in (400, 422):
            print(f"case C OK: empty key cleanly rejected with {s}")
        elif s == 200:
            time.sleep(0.5)  # async grace before single readback
            pls_c, cerr_c = scroll_payloads(coll)
            if pls_c is None or 2 not in pls_c or 1 not in pls_c:
                print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr_c)[:300]}")
                return
            got2 = pls_c.get(2)
            if got2 == {"fresh": 1}:
                print("case C OK: empty key treated as root assignment — p2 exactly "
                      "the provided payload (recorded posture)")
            elif got2 == base_payloads[2]:
                print("case C OK: empty key was a no-op — p2 deep-equal baseline "
                      "(recorded posture)")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case C: "
                      f"empty-key 200-ack left p2 in an unexplained state {got2} "
                      f"(neither root assignment {{'fresh': 1}} nor baseline "
                      f"{base_payloads[2]})")
                return
            if pls_c.get(1) != last_p1:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case C: "
                      f"empty-key overwrite on p2 changed p1: {pls_c.get(1)} != "
                      f"{last_p1}")
                return
        else:
            print(f"NOTE: case C returned {s} (unexpected status family); recorded "
                  f"for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
