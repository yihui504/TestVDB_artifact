#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_overwrite_004
# strategy: state replacement-content persistence (chained overwrite + from-nothing + nested deep-equal + null-valued key)
# endpoint: payload+overwrite
# constraint_ids: qdrant_state_payload_overwrite_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/overwrite-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — assuming the replacement
#            promise holds for chained replacements, payload-less points,
#            nested object payloads and null-valued keys, without readback)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state replacement-content persistence x
  qdrant_state_payload_overwrite_001 ("after overwrite the point payload
  equals the provided payload") — four content faces of the same promise on
  four dedicated points (each judged by scroll readback, collateral =
  untouched sibling points): (A) CHAINED overwrite — overwrite p1 with
  {"c":3} then again with {"d":4,"e":5}: the SECOND replacement must remove
  "c" exactly as the first removed {"a","b"} (replacement is not
  accumulate-and-merge); (B) FROM-NOTHING — p2 is upserted with NO payload;
  overwrite must still produce EXACTLY the provided payload (from-nothing is
  still exact-set, not error/no-op); (C) NESTED deep-equal — p3 gets a nested
  object payload; readback must deep-equal byte-exact (no flattening, no
  re-serialization distortion of nested subtrees); (D) NULL-VALUED key — p4
  overwritten with {"k":null}: readback must be exactly {"k":null}
  (present-with-null is distinct from absent — old key "x" gone, "k" kept);
  a 4xx on the null-valued payload is recorded as NOTE (null-value support is
  implementation-defined), a 200 that DROPS the null key (readback {}) is a
  Type4 distortion signal for the judge.
  [chunk_payload+overwrite coverage: state content-persistence x
  qdrant_state_payload_overwrite_001, chained/from-nothing/nested/null faces
  (this script; points-selector face in _001, filter-selector face in _002,
  boundary-value faces in _003, key-scope face in _008)]
Oracle: each overwrite (wait=true query) returns 200 and its point's scroll
  readback deep-equals the provided payload EXACTLY — case A: p1 == {"c":3}
  after the first and == {"d":4,"e":5} after the second ("c" gone = chained
  full replacement); case B: p2 == {"only":"key"}; case C: p3 ==
  {"nested":{"new":2},"top":5} deep-equal; case D: p4 == {"k":null} (4xx on
  null value = NOTE ladder, 200 with readback {} = Type4 null-key drop);
  any residue of a previous payload on ANY case, any distortion of the
  provided payload, or collateral change on a sibling point =
  Type4_StateLogicViolation; non-200 on a legal overwrite =
  Type1_IllegalSuccess; 5xx/transport = Type3_RuntimeFailure with /healthz
  re-check (constraint qdrant_state_payload_overwrite_001).
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
    Returns (found, payload, chan_err); found=False means the readback channel
    is unusable or the point is missing (payload itself may be None)."""
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


def overwrite(coll, pid, payload):
    """One overwrite act + shared status ladder. Returns True to continue."""
    s, _, raw = safe_request(
        "PUT", f"/collections/{coll}/points/payload",
        json={"points": [pid], "payload": payload},
        params={"wait": "true"}, timeout=60)
    print(f"\noverwrite points=[{pid}] payload={json.dumps(payload)} -> status={s}")
    print(f"raw: {raw[:500]}")
    if s <= 0:
        transport_dead()
        return False
    if 500 <= s <= 599:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"5xx on legal overwrite (healthz status={hs}: {hraw[:200]})")
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — overwrite on point "
              f"{pid} returned {s}")
        return False
    if s != 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal overwrite on "
              f"point {pid} rejected with {s} (promise: overwrite succeeds on "
              f"valid targets)")
        return False
    return True


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpow4" + tag
    base_payloads = {
        1: {"a": 1, "b": 2},                                   # A: chained
        # 2: NO payload (B: from-nothing)
        3: {"nested": {"old": 1, "sub": "x"}, "keep": "me"},   # C: nested
        4: {"x": 1, "k": "old"},                               # D: null-valued key
    }
    vecs = {1: [0.1, 0.2, 0.3, 0.4], 2: [0.2, 0.3, 0.4, 0.5],
            3: [0.3, 0.4, 0.5, 0.6], 4: [0.4, 0.5, 0.6, 0.7]}
    want_c = {"nested": {"new": 2}, "top": 5}

    # Arrange: data-bearing collection (own data, own cleanup)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    pts = [{"id": 1, "vector": vecs[1], "payload": base_payloads[1]},
           {"id": 2, "vector": vecs[2]},                       # payload-less
           {"id": 3, "vector": vecs[3], "payload": base_payloads[3]},
           {"id": 4, "vector": vecs[4], "payload": base_payloads[4]}]
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": pts},
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
        # baseline readback: all 4 visible, p2 payload-less
        pls, cerr = scroll_payloads(coll)
        for _ in range(6):
            if pls is not None and all(i in pls for i in (1, 2, 3, 4)):
                break
            time.sleep(0.5)
            pls, cerr = scroll_payloads(coll)
        if pls is None or any(i not in pls for i in (1, 2, 3, 4)):
            print(f"baseline readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        if pls.get(1) != base_payloads[1] or pls.get(3) != base_payloads[3] \
                or pls.get(4) != base_payloads[4] or pls.get(2) not in ({}, None):
            print(f"baseline mismatch: {pls}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        print("baseline: 4 points visible (p2 payload-less)")

        # ---- Case A: chained overwrite (second replacement removes the first) ----
        if not overwrite(coll, 1, {"c": 3}):
            return
        found, got, cerr = wait_payload(coll, 1, {"c": 3})
        if not found:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr)[:300]}")
            return
        if got != {"c": 3}:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case A step1: "
                  f"p1 payload is {got}, want exactly 'c'=3 (old a/b must be gone)")
            return
        if not overwrite(coll, 1, {"d": 4, "e": 5}):
            return
        found, got, cerr = wait_payload(coll, 1, {"d": 4, "e": 5})
        if not found:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr)[:300]}")
            return
        if got != {"d": 4, "e": 5}:
            residue = [k for k in ("a", "b", "c") if isinstance(got, dict) and k in got]
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case A step2 "
                  f"(chained): p1 payload is {got}, want exactly d=4,e=5; residue "
                  f"{residue} — the second overwrite did not replace the ENTIRE "
                  f"payload (accumulate/merge posture)")
            return
        print("case A OK: chained replacement exact at both steps")

        # ---- Case B: from-nothing (payload-less point) ----
        if not overwrite(coll, 2, {"only": "key"}):
            return
        found, got, cerr = wait_payload(coll, 2, {"only": "key"})
        if not found:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr)[:300]}")
            return
        if got != {"only": "key"}:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case B "
                  f"(from-nothing): p2 payload is {got}, want exactly only='key'")
            return
        print("case B OK: from-nothing overwrite exact")

        # ---- Case C: nested object deep-equal ----
        if not overwrite(coll, 3, want_c):
            return
        found, got, cerr = wait_payload(coll, 3, want_c)
        if not found:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr)[:300]}")
            return
        if got != want_c:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case C "
                  f"(nested): p3 payload is {got}, want deep-equal {want_c} "
                  f"(nested subtree distorted and/or old keys kept)")
            return
        print("case C OK: nested payload deep-equal after replacement")

        # ---- Case D: null-valued key ----
        s, _, raw = safe_request(
            "PUT", f"/collections/{coll}/points/payload",
            json={"points": [4], "payload": {"k": None}},
            params={"wait": "true"}, timeout=60)
        print("\noverwrite points=[4] payload={'k': None} -> status=%s" % s)
        print(f"raw: {raw[:500]}")
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on null-valued overwrite (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — case D "
                  f"triggered server error {s}")
            return
        if s in (400, 422):
            print(f"NOTE: case D null-valued payload rejected with {s} — null-value "
                  f"support is implementation-defined; recorded for the judge")
        elif s == 200:
            found, got, cerr = wait_payload(coll, 4, {"k": None})
            if not found:
                print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr)[:300]}")
                return
            if got != {"k": None}:
                if got in ({}, None):
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case D: "
                          f"200-accepted a null-valued payload but readback DROPPED "
                          f"the null key entirely (payload {got}) — the provided "
                          f"payload had k present-with-null; present-with-null is "
                          f"not absent")
                else:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case D: "
                          f"p4 payload is {got}, want exactly k=None ('x' must be "
                          f"gone, k kept with null)")
                return
            print("case D OK: null-valued key persisted exactly")
        else:
            print(f"NOTE: case D returned {s} (unexpected status family); recorded "
                  f"for the judge — continuing the sweep")

        # collateral sweep: every sibling keeps its case-final exact value
        pls_f, cerr_f = scroll_payloads(coll)
        if pls_f is None:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr_f)[:300]}")
            return
        finals = {1: {"d": 4, "e": 5}, 2: {"only": "key"}, 3: want_c}
        for pid, wantv in finals.items():
            if pls_f.get(pid) != wantv:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — collateral "
                      f"sweep: point {pid} payload drifted to {pls_f.get(pid)}, "
                      f"want {wantv}")
                return
        print("collateral sweep OK: all siblings hold their case-final exact payloads")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
