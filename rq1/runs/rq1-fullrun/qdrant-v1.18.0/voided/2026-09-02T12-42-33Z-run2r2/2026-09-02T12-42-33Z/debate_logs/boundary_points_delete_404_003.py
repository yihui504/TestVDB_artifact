#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_delete_404_003
# strategy: behavioral negative-face attack (missing-collection 404 leg of the
#           200/404/400 endpoint promise, sampled across BOTH selector
#           branches with a positive control isolating the cause)
# endpoint: points+delete
# constraint_ids: qdrant_behavioral_points_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the 404 leg is probed on
#            both selector branches to catch per-branch validation divergence)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral 404 leg x qdrant_behavioral_points_delete_001 — the
  assertion "returns 200 ok on success; 404 when the collection is missing;
  400 on an invalid filter" is attacked at its 404 leg with BOTH selector
  branches of the filter-or-ids grammar (R34 lesson), plus a positive control
  on an existing collection that pins the 404 to the missing-collection cause
  (G4 positive-negative pairing, shared setup):
    G0 ghost collection name: uuid-tagged, PROVEN unused via
       collections+exists (result.exists == false) before any probe — no
       name collision can fake a 200
    N1 delete {"points":[1,2]}    on the ghost -> exactly 404
    N2 delete {"filter": must[...]} on the ghost -> exactly 404
    C  identical bodies on an EXISTING collection (2 seeded points)
       -> 200 each, exact count 0 after (the same grammar that 404'd on the
       ghost must succeed on a live collection — isolates the 404 leg to
       collection existence, not body validity)
  A 2xx on the ghost = the delete was applied to a nonexistent collection
  (state-corruption signal); divergent statuses across N1/N2 are recorded as
  a G9 disposition-consistency signal (session convention for 404 legs).
  [chunk_points+delete coverage: behavioral 404 leg x
  qdrant_behavioral_points_delete_001 (this script; idempotence faces in
  boundary_points_delete_idempotent_001, filter-wipe faces in
  boundary_points_delete_filter_wipe_002, invalid-filter 400 leg in
  boundary_points_delete_invalid_filter_004, selector-boundary faces in
  boundary_points_delete_selector_005, cross-face invisibility in
  boundary_points_delete_invisibility_006)]
Oracle: N1/N2 -> HTTP 404 exactly (200/201 = Type1_IllegalSuccess: delete
  reported applied to a nonexistent collection; 5xx with /healthz alive =
  Type3_RuntimeFailure); a non-404 4xx = NOTE + G9 disposition-consistency
  check across the two selector faces; control C -> 200 on both bodies with
  exact count == 0 afterwards (other count = Type4; non-200 = Type1 valid
  delete rejected); transport failure -> /healthz liveness re-check then
  SCRIPT_ERROR (constraint qdrant_behavioral_points_delete_001).
Constraint: qdrant_behavioral_points_delete_001 (bare id) — "returns 200 ok
  (UpdateResult) on success; 404 when the collection is missing; 400 on an
  invalid filter" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+delete         -> POST /collections/{collection_name}/points/delete
  points+count          -> POST /collections/{collection_name}/points/count
  collections+exists    -> GET  /collections/{collection_name}/exists
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
  points+upsert         -> PUT  /collections/{collection_name}/points
  healthz               -> GET  /healthz
  (wait is a query parameter on the delete/upsert faces — passed via params=)
"""

import json
import os
import sys
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

DIM = 4
V = [0.1, 0.2, 0.3, 0.4]
CITY_COND = {"key": "city", "match": {"value": "berlin"}}
IDS_BODY = {"points": [1, 2]}
FILTER_BODY = {"filter": {"must": [CITY_COND]}}


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/ordering/timeout) via params= — never stuffed into the body.
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


def healthz_alive():
    """Inline liveness probe on the lightweight healthz face."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def transport_dead(where):
    """Transport-branch liveness re-check (lightweight healthz face only)."""
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return False


def collection_exists(name):
    """collections+exists face: result.exists boolean."""
    s, body, raw = safe_request("GET", f"/collections/{name}/exists", timeout=30)
    if s == -1 or not (200 <= s <= 299):
        return None, s, raw
    result = body.get("result") if isinstance(body, dict) else None
    got = result.get("exists") if isinstance(result, dict) else None
    return got, s, raw


def fresh_ghost_name():
    """uuid-tagged name PROVEN unused via collections+exists (no fake 200)."""
    for _ in range(4):
        name = "bpd3no" + uuid.uuid4().hex[:10]
        got, s, raw = collection_exists(name)
        if got is False:
            return name
    return None


def delete_on(name, body):
    """points+delete face, wait=true (query param)."""
    return safe_request("POST", f"/collections/{name}/points/delete",
                        json=body, timeout=60, params={"wait": "true"})


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpd3n" + tag
    ghost = fresh_ghost_name()
    if ghost is None:
        print("could not prove a ghost collection name unused (exists face)")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    # Arrange: existing collection with 2 points (positive-control substrate)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{"id": i, "vector": V, "payload": {"city": "berlin"}} for i in (1, 2)]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=120)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        print(f"control collection {coll} seeded (2 points); ghost {ghost} proven absent")

        # ---- N1/N2: both selector branches on the ghost collection ----
        seen = []
        for label, body in (("N1 ids-selector", IDS_BODY), ("N2 filter-selector", FILTER_BODY)):
            s, _, raw = delete_on(ghost, body)
            print(f"\n{label} on ghost collection -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                transport_dead(label)
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                          f"delete on missing collection returned {s}: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — {l} 5xx and healthz down".format(l=label))
                return
            if 200 <= s <= 299:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"delete reported APPLIED (status {s}) to the missing "
                      f"collection {ghost}; promise says 404: {raw[:300]}")
                return
            if s == 404:
                print(f"{label}: 404 exactly as promised")
                seen.append(404)
            else:
                print(f"NOTE: {label} returned {s} instead of 404 — non-404 4xx on a "
                      f"missing collection; recorded for the G9 disposition-"
                      f"consistency check across the two selector faces")
                seen.append(s)
        if len(set(seen)) > 1:
            print(f"NOTE (G9): divergent missing-collection dispositions across the "
                  f"two selector branches: {seen} — same-shape grammar, different "
                  f"rejection face; recorded for the judge")
        else:
            print(f"both selector faces agree on {seen[0]} (G9 consistent)")

        # ---- C: identical bodies on the EXISTING collection -> 200, count 0 ----
        for label, body in (("C1 ids-selector", IDS_BODY), ("C2 filter-selector", FILTER_BODY)):
            s, _, raw = delete_on(coll, body)
            print(f"\n{label} on existing collection -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                transport_dead(label)
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: valid delete returned {s}: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — {l} 5xx and healthz down".format(l=label))
                return
            if not (200 <= s <= 299):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: valid "
                      f"delete rejected with {s} on an existing collection (promise: "
                      f"HTTP 200); the 404 leg is thereby pinned to collection "
                      f"existence, not body validity: {raw[:300]}")
                return
            print(f"{label}: 200 as promised")

        s, body, raw = safe_request("POST", f"/collections/{coll}/points/count",
                                    json={"exact": True}, timeout=60)
        if s == -1:
            transport_dead("post-control count")
            return
        result = body.get("result") if isinstance(body, dict) else None
        cnt = result.get("count") if isinstance(result, dict) else None
        if cnt != 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — control "
                  f"deletes returned 200 but exact count == {cnt}, expected 0 "
                  f"(both control bodies jointly cover all 2 seeded points): {raw[:300]}")
            return
        print("control: both deletes 200 and exact count == 0 (cause isolated to collection existence)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal
        try:
            safe_request("DELETE", f"/collections/{ghost}", timeout=60)
        except Exception:
            pass  # ghost never existed; harmless if 404


if __name__ == "__main__":
    main()
