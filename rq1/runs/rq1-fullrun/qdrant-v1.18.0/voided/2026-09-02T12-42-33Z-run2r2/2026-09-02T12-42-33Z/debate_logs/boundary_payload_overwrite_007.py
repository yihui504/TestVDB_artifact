#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_overwrite_007
# strategy: bc replace-not-merge discriminator (documented scenario verbatim + set-vs-overwrite contrast face)
# endpoint: payload+overwrite
# constraint_ids: qdrant_bc_payload_overwrite_replace_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-04 (Boundary Default Optimism — overwrite and set share the
#            same SetPayload wire schema; only readback can prove the server
#            actually distinguishes replace from merge)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: bc replace-not-merge discriminator x
  qdrant_bc_payload_overwrite_replace_001 — the behavioral contract's
  documented scenario executed VERBATIM on its own related_endpoints chain
  (payload+set -> payload+overwrite -> points+get): upsert a point, set
  payload keys {a,b} via payload+set, then PUT payload+overwrite with {c}
  (wait=true), then read the point back via points+get (POST
  /collections/{name}/points ids=[..] with_payload=true — the documented
  "GET the points with payload" channel). The promised outcome: payload
  equals EXACTLY {c}; previously stored keys {a,b} are removed (set
  semantics, not merge). The contrast face (the discriminator that makes
  merge-vs-replace falsifiable rather than coincidental): on the SAME state,
  payload+set {d} afterwards must MERGE — readback exactly {c,d} — because
  set adds keys while overwrite replaces. If overwrite merged we would see
  {a,b,c}; if set replaced we would see {d} alone; either confusion =
  Type4. Collateral: the point's vector deep-equals the BASELINE READBACK
  vector (R27 lesson) and exact count stays 1.
  [chunk_payload+overwrite coverage: bc replace-not-merge x
  qdrant_bc_payload_overwrite_replace_001, documented-scenario + contrast
  faces (this script; key-scoped scope face in _008)]
Oracle: step 1 — payload+set {"a":1,"b":2} points=[1] (wait=true) returns
  200 and points+get shows exactly {"a":1,"b":2}; step 2 — payload+overwrite
  {"c":3} points=[1] (wait=true) returns 200 and points+get shows EXACTLY
  {"c":3} with BOTH {a,b} gone ({a,b,c} or any a/b residue =
  Type4_StateLogicViolation merge-not-replace; non-200 = Type1_IllegalSuccess
  promise: the documented scenario succeeds); step 3 (discriminator) —
  payload+set {"d":4} returns 200 and readback shows EXACTLY {"c":3,"d":4}
  ({d:4} alone = Type4 set/overwrite semantics swapped); vector deep-equals
  the baseline readback vector and exact count stays 1 throughout; 5xx at
  any step = Type3_RuntimeFailure with /healthz re-check (contract
  qdrant_bc_payload_overwrite_replace_001).
Constraint: qdrant_bc_payload_overwrite_replace_001 (bare id) — "after
  overwrite the record payload equals exactly {c}; the previously stored
  keys {a,b} are removed (set semantics, not merge)" (scenario:
  "set payload keys {a,b} -> PUT payload+overwrite with {c} (wait=true) ->
  GET the points with payload")
Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  payload+overwrite     -> PUT  /collections/{collection_name}/points/payload
  payload+set           -> POST /collections/{collection_name}/points/payload
  points+get            -> POST /collections/{collection_name}/points
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


def get_payloads(coll):
    """points+get readback (the bc contract's documented channel):
    POST /collections/{name}/points {"ids":[1],"with_payload":true}.
    Returns (payload_map, chan_err); None map means channel unusable."""
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points",
        json={"ids": [1], "with_payload": True}, timeout=30)
    if s != 200 or not isinstance(body, dict):
        return None, (s, raw)
    res = body.get("result")
    if not isinstance(res, list):
        return None, (s, raw)
    return {p.get("id"): p.get("payload") for p in res if isinstance(p, dict)}, (s, raw)


def scroll_point(coll):
    """points+scroll readback (cross-check channel): point 1 dict or None."""
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points/scroll",
        json={"limit": 100, "with_payload": True, "with_vector": True}, timeout=30)
    if s != 200 or not isinstance(body, dict):
        return None, (s, raw)
    res = body.get("result")
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        return None, (s, raw)
    for p in pts:
        if isinstance(p, dict) and p.get("id") == 1:
            return p, (s, raw)
    return None, (s, raw)


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


def wait_for(coll, want, tries=6, delay=0.5):
    """Poll the points+get channel until point 1's payload deep-equals want.
    Returns (found, payload, chan_err)."""
    pls, cerr = get_payloads(coll)
    for _ in range(tries):
        if pls is None or 1 not in pls:
            return False, None, cerr
        if pls.get(1) == want:
            return True, pls.get(1), cerr
        time.sleep(delay)
        pls, cerr = get_payloads(coll)
    if pls is None or 1 not in pls:
        return False, None, cerr
    return True, pls.get(1), cerr


def step_ladder(label, s, raw):
    """Shared status ladder for the three documented steps.
    Returns 'ok' to continue, anything else stops (verdict already printed)."""
    if s <= 0:
        transport_dead()
        return "stop"
    if 500 <= s <= 599:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"5xx on {label} (healthz status={hs}: {hraw[:200]})")
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label} returned {s}")
        return "stop"
    if s != 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label} rejected "
              f"with {s} (promise: the documented scenario step succeeds on "
              f"valid targets)")
        return "stop"
    return "ok"


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpow7" + tag
    vec = [0.1, 0.2, 0.3, 0.4]

    # Arrange: data-bearing collection (own data, own cleanup)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request(
        "PUT", f"/collections/{coll}/points",
        json={"points": [{"id": 1, "vector": vec}]},
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
        # baseline: point visible, payload-less; capture baseline readback vector
        p0, cerr0 = scroll_point(coll)
        for _ in range(6):
            if p0 is not None:
                break
            time.sleep(0.5)
            p0, cerr0 = scroll_point(coll)
        if p0 is None:
            print(f"baseline readback unusable: {str(cerr0)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        vec_baseline = p0.get("vector")
        cnt0, _ = count_exact(coll)
        print(f"baseline: point 1 visible (payload {p0.get('payload')}), exact count={cnt0}")

        # ---- Step 1 (bc scenario): payload+set {"a":1,"b":2} ----
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload",
            json={"points": [1], "payload": {"a": 1, "b": 2}},
            params={"wait": "true"}, timeout=60)
        print(f"\nstep1 payload+set a=1,b=2 -> status={s}")
        print(f"raw: {raw[:400]}")
        if step_ladder("step1 payload+set", s, raw) != "ok":
            return
        found, got, cerr = wait_for(coll, {"a": 1, "b": 2})
        if not found:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr)[:300]}")
            return
        if got != {"a": 1, "b": 2}:
            print(f"VERDICT: SCRIPT_ERROR — step1 baseline mismatch: got {got}, "
                  f"want a=1,b=2 (setup precondition of the documented scenario)")
            return
        print("step1 OK: payload exactly {'a': 1, 'b': 2} via points+get")

        # ---- Step 2 (bc scenario core): payload+overwrite {"c":3} ----
        s, _, raw = safe_request(
            "PUT", f"/collections/{coll}/points/payload",
            json={"points": [1], "payload": {"c": 3}},
            params={"wait": "true"}, timeout=60)
        print(f"\nstep2 payload+overwrite c=3 -> status={s}")
        print(f"raw: {raw[:400]}")
        if step_ladder("step2 payload+overwrite", s, raw) != "ok":
            return
        found, got, cerr = wait_for(coll, {"c": 3})
        if not found:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr)[:300]}")
            return
        if got != {"c": 3}:
            residue = [k for k in ("a", "b") if isinstance(got, dict) and k in got]
            if residue:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — bc core: "
                      f"after overwrite the payload is {got}, want EXACTLY "
                      f"{{'c': 3}}; keys {residue} survived — MERGE semantics, "
                      f"not the promised set/replace semantics")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — bc core: "
                      f"after overwrite the payload is {got}, want EXACTLY "
                      f"{{'c': 3}}")
            return
        print("step2 OK: payload exactly {'c': 3} — {a,b} removed (replace, not merge)")

        # ---- Step 3 (discriminator): payload+set {"d":4} must MERGE ----
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload",
            json={"points": [1], "payload": {"d": 4}},
            params={"wait": "true"}, timeout=60)
        print(f"\nstep3 discriminator payload+set d=4 -> status={s}")
        print(f"raw: {raw[:400]}")
        if step_ladder("step3 payload+set discriminator", s, raw) != "ok":
            return
        found, got, cerr = wait_for(coll, {"c": 3, "d": 4})
        if not found:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr)[:300]}")
            return
        if got != {"c": 3, "d": 4}:
            if got == {"d": 4}:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"discriminator: payload+set {{'d'}} REPLACED the payload "
                      f"(readback {got}, want merge c=3,d=4) — set/overwrite "
                      f"semantics swapped on the shared SetPayload schema")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"discriminator: after payload+set d=4 readback is {got}, "
                      f"want exactly merge c=3,d=4")
            return
        print("step3 OK: set merged (c kept, d added) — set vs overwrite are "
              "genuinely distinct semantics")

        # collateral: vector stable vs baseline readback; count stays 1
        p1, cerr1 = scroll_point(coll)
        if p1 is None:
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr1)[:300]}")
            return
        if p1.get("vector") != vec_baseline:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — vector of "
                  f"point 1 changed across the set/overwrite steps (readback-vs-"
                  f"baseline-readback compare; payload ops must not touch vectors)")
            return
        if p1.get("payload") != {"c": 3, "d": 4}:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — scroll "
                  f"cross-check readback {p1.get('payload')} != points+get "
                  f"readback c=3,d=4 (channel disagreement)")
            return
        cnt1, _ = count_exact(coll)
        if cnt0 is not None and cnt1 is not None and cnt1 != cnt0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — exact count "
                  f"drifted {cnt0} -> {cnt1} across the payload steps")
            return
        print(f"collateral OK: vector deep-equal baseline readback; exact count "
              f"stable ({cnt0} -> {cnt1})")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
