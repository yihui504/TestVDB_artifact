#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_clear_004
# strategy: state idempotency/persistence readback (repetition + empty-state closure)
# endpoint: payload+clear
# constraint_ids: qdrant_state_payload_clear_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/clear-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — assuming once cleared, always
#            cleared; the repetition and never-had-payload closure cases probe
#            resurrection, point loss and vector damage on the empty state)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state idempotency/persistence readback x qdrant_state_payload_clear_001 —
  the repetition face plus the boundary closure of the same promise. One live
  bpclr4_* collection with 3 points: id 1 and 2 carry payloads, id 3 NEVER
  carried a payload (vector-only, the min-boundary of "payload keys to remove").
  Sequence: (a) clear [1] wait=true -> p1 emptied, p2/control intact; (b) REPEAT
  the identical clear [1] -> the emptied state must be a fixed point: no payload
  resurrection, no point loss, no vector damage; (c) clear [3] (the empty-state
  closure) -> still 200, state unchanged. Mutation-point argument (G6):
  repetition-on-empty-state and clear-of-never-populated are the two operations
  whose pre-state and post-state coincide for a correct implementation — any
  drift (resurrected payload, count drift 3->2, vector loss) is unambiguously
  attributable to the clear, and a 4xx on the legal repeat contradicts the
  idempotent face of the promise.
  [chunk_payload+clear coverage: state readback x qdrant_state_payload_clear_001,
  idempotency/persistence + empty-state closure face (this script)]
Oracle: clear {"points":[1],"wait":true} then the IDENTICAL clear again each return 200 (200 twice) with scroll readback showing p1 payload empty after BOTH (resurrected
  payload = Type4), p2 payload deep-equal baseline throughout, p3 (never had
  payload) still payload-free with vector intact, exact count stays exactly 3
  after every step (drift = Type4_StateLogicViolation); a 4xx on the legal
  repeat or on clear [3] = Type1_IllegalSuccess (legal targeted clear rejected);
  5xx = Type3_RuntimeFailure with /healthz re-check.
Constraint: qdrant_state_payload_clear_001 (bare id) — "after clear, targeted
  points carry no payload keys" (evidence_tier: explicit; level: system; this
  script attacks the persistence of that postcondition under repetition and its
  boundary closure at zero payload keys)

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


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpclr4" + tag
    p2_base = {"city": "par", "n": 2}

    # Arrange: id 1,2 carry payloads; id 3 is vector-only (never had payload)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    pts = [
        {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"city": "ams", "n": 1}},
        {"id": 2, "vector": [0.2, 0.3, 0.4, 0.5], "payload": p2_base},
        {"id": 3, "vector": [0.3, 0.4, 0.5, 0.6]},  # no payload key at all
    ]
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": pts}, params={"wait": "true"}, timeout=60)
    if s not in (200, 201):
        print(f"setup upsert failed status={s}: {raw[:300]}")
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # baseline
        snap, cerr = scroll_snapshot(coll)
        for _ in range(6):
            if snap is not None and all(i in snap for i in (1, 2, 3)):
                break
            time.sleep(0.5)
            snap, cerr = scroll_snapshot(coll)
        if snap is None or not all(i in snap for i in (1, 2, 3)):
            print(f"baseline readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        cnt0, _ = count_exact(coll)
        print(f"baseline: 3 points visible (2 with payload, 1 vector-only), exact count={cnt0}")

        def do_clear(step_label, ids):
            """One clear step: request + full readback adjudication."""
            st, _, rw = safe_request(
                "POST", f"/collections/{coll}/points/payload/clear",
                json={"points": ids}, params={"wait": "true"}, timeout=60)
            print(f"clear {step_label} -> status={st}")
            print(f"raw: {rw[:400]}")
            if st <= 0:
                transport_dead()
                return "script"
            if 500 <= st <= 599:
                hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
                print(f"5xx on legal clear (healthz status={hs}: {hraw[:200]})")
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — legal targeted "
                      f"clear {step_label} returned {st}")
                return "defect"
            if st != 200:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal targeted "
                      f"clear {step_label} rejected with {st} (valid targets -> 200)")
                return "defect"
            sn, ce = scroll_snapshot(coll)
            for _ in range(6):  # async grace
                if sn is None:
                    break
                ok = (payload_empty(sn[1]) and sn[2].get("payload") == p2_base
                      and payload_empty(sn[3]))
                if ok:
                    break
                time.sleep(0.5)
                sn, ce = scroll_snapshot(coll)
            if sn is None or not all(i in sn for i in (1, 2, 3)):
                print(f"readback unusable after {step_label}: {str(ce)[:300]}")
                print("VERDICT: SCRIPT_ERROR — readback channel failure, no defect conclusion")
                return "script"
            if not payload_empty(sn[1]):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — point 1 "
                      f"carries payload keys after {step_label}: {sn[1].get('payload')}")
                return "defect"
            if sn[2].get("payload") != p2_base:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — control "
                      f"point 2 payload damaged by {step_label}: {sn[2].get('payload')}")
                return "defect"
            if not payload_empty(sn[3]):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — vector-only "
                      f"point 3 gained payload after {step_label}: {sn[3].get('payload')}")
                return "defect"
            for i in (1, 2, 3):
                if not vector_intact(sn[i]):
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — vector "
                          f"of point {i} lost after {step_label}")
                    return "defect"
            cn, _ = count_exact(coll)
            if cnt0 is not None and cn is not None and cn != cnt0:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — exact "
                      f"count drifted {cnt0} -> {cn} after {step_label}")
                return "defect"
            print(f"OK: {step_label} — p1 empty, p2 control intact, p3 vector-only, "
                  f"vectors intact, count stable ({cn})")
            return "ok"

        # (a) first clear of point 1
        r = do_clear("first [1]", [1])
        if r != "ok":
            return
        # (b) identical repeat — the emptied state must be a fixed point
        r = do_clear("repeat [1]", [1])
        if r != "ok":
            return
        # (c) boundary closure: clear of a never-populated point
        r = do_clear("closure [3]", [3])
        if r != "ok":
            return
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
