#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_delete_004
# strategy: state keys-content idempotency/persistence readback (mixed keys + repetition + never-had-key closure)
# endpoint: payload+delete
# constraint_ids: qdrant_state_payload_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — assuming a keys list mixing
#            existing and nonexistent keys, a repeated delete, and a delete of a
#            key a point never had are all harmless; each is probed for
#            resurrection, collateral loss and point loss)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state keys-content idempotency/persistence readback x
  qdrant_state_payload_delete_001 — the keys-list CONTENT faces of the same
  promise. One live bpdel4_* collection with 3 points; p1/p2 carry
  {"city","n","tag"}, p3 carries {"n","tag"} (NEVER had "city" — the boundary
  closure of "the listed keys"). Sequence, each step wait=true and judged by
  scroll readback + exact count + vector readback:
  (a) delete keys=["city","ghost_key"] points=[1,2] — a MIXED list (one existing
      key, one nonexistent key) across two points: "city" must vanish from BOTH,
      n/tag must stay byte-equal, the ghost key must be harmless (no 4xx, no
      side effects), p3 untouched;
  (b) REPEAT the identical delete — the emptied state must be a fixed point:
      still 200, no payload resurrection, no point loss, no vector damage;
  (c) delete keys=["city"] points=[3] — the never-had-key closure: still 200
      (removing a key a point never had removes nothing), state unchanged.
  Mutation-point argument (G6): repetition-on-already-deleted and
  delete-of-never-had-key are the two operations whose pre-state and post-state
  coincide for a correct implementation — any drift (resurrected city, lost
  n/tag, count drift 3->2, vector change) is unambiguously attributable to the
  delete; and the ghost key in the mixed list is the classic silent-failure
  trap: an implementation that errors the WHOLE batch on the missing key, or
  silently wipes the other keys, both violate "removes only the listed keys;
  all others stay untouched".
  [chunk_payload+delete coverage: state readback x qdrant_state_payload_delete_001,
  keys-content idempotency/closure face (this script)]
Oracle: (a) delete {"points":[1,2],"keys":["city","ghost_key"],"wait":true}
  returns 200 with p1/p2 payload exactly {"n":..,"tag":..} (city gone, n/tag
  byte-equal baseline values) and p3 deep-equal baseline; (b) the IDENTICAL
  repeat also returns 200 leaving the same state (resurrected city or lost
  n/tag = Type4); (c) delete {"points":[3],"keys":["city"],"wait":true} returns
  200 with p3 still exactly {"n":3,"tag":..}; exact count stays exactly 3 after
  every step (drift = Type4_StateLogicViolation); all vectors deep-equal the
  baseline readback vectors at the end (R27 lesson: readback-vs-baseline-readback
  on Cosine); a 4xx on any of the three legal deletes = Type1_IllegalSuccess;
  5xx = Type3_RuntimeFailure with /healthz re-check (constraint
  qdrant_state_payload_delete_001).
Constraint: qdrant_state_payload_delete_001 (bare id) — "delete removes only the
  listed keys; all other payload keys stay untouched" (evidence_tier: explicit;
  level: system; this script attacks the promise under mixed listed keys,
  repetition and the zero-prevalence closure of a listed key)

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


def check_step(step, s, raw, coll, want, vec_baseline, cnt0):
    """Shared per-step adjudication: legal delete -> 200 + state == want.
    Returns True to continue, False after printing a verdict."""
    if s <= 0:
        transport_dead()
        return False
    if 500 <= s <= 599:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"5xx on legal delete (healthz status={hs}: {hraw[:200]})")
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {step} returned {s}")
        return False
    if s != 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {step} rejected with "
              f"{s} (promise: the listed-key delete succeeds on valid targets; "
              f"ghost keys and never-had keys must be harmless)")
        return False
    snap, cerr = wait_state(coll, want)
    if snap is None:
        print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr)[:300]}")
        return False
    for i in want:
        got = snap[i].get("payload")
        if got != want[i]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {step}: "
                  f"point {i} payload {got} != expected {want[i]} (promise: only "
                  f"the listed keys are removed, all others stay untouched)")
            return False
    for i in vec_baseline:
        if snap[i].get("vector") != vec_baseline[i]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {step}: "
                  f"vector of point {i} changed (readback-vs-baseline-readback "
                  f"compare; delete must not touch vectors)")
            return False
    cnt, _ = count_exact(coll)
    if cnt0 is not None and cnt is not None and cnt != cnt0:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {step}: exact "
              f"count drifted {cnt0} -> {cnt} (delete must not delete points)")
        return False
    print(f"OK: {step} — payloads exactly as expected, count stable ({cnt})")
    return True


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdel4" + tag
    base_payloads = {
        1: {"city": "ams", "n": 1, "tag": "alpha"},
        2: {"city": "par", "n": 2, "tag": "beta"},
        3: {"n": 3, "tag": "gamma"},   # NEVER had "city" (closure face)
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
        cnt0, _ = count_exact(coll)
        print(f"baseline: 3 payloads visible, exact count={cnt0}")

        after_a = {
            1: {"n": 1, "tag": "alpha"},            # city gone via mixed list
            2: {"n": 2, "tag": "beta"},
            3: dict(base_payloads[3]),              # untouched control
        }

        # (a) MIXED keys list: one existing key + one ghost key, two points
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload/delete",
            json={"points": [1, 2], "keys": ["city", "ghost_key"]},
            params={"wait": "true"}, timeout=60)
        print(f"\n(a) mixed keys [city,ghost_key] points=[1,2] -> status={s}")
        print(f"raw: {raw[:500]}")
        if not check_step("step (a) mixed-keys delete", s, raw, coll,
                          after_a, vec_baseline, cnt0):
            return

        # (b) REPEAT the identical delete — fixed point, no resurrection
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload/delete",
            json={"points": [1, 2], "keys": ["city", "ghost_key"]},
            params={"wait": "true"}, timeout=60)
        print(f"\n(b) IDENTICAL repeat -> status={s}")
        print(f"raw: {raw[:500]}")
        if not check_step("step (b) identical repeat", s, raw, coll,
                          after_a, vec_baseline, cnt0):
            return

        # (c) never-had-key closure: delete "city" from point 3 (never had it)
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload/delete",
            json={"points": [3], "keys": ["city"]},
            params={"wait": "true"}, timeout=60)
        print(f"\n(c) delete city from never-had-key point 3 -> status={s}")
        print(f"raw: {raw[:500]}")
        if not check_step("step (c) never-had-key closure", s, raw, coll,
                          after_a, vec_baseline, cnt0):
            return

        print("OK: mixed keys removed exactly the existing key; ghost key and "
              "repeat harmless; never-had-key closure a no-op; count stable")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
