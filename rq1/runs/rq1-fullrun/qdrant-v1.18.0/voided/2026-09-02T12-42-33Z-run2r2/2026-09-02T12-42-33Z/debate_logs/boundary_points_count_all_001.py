#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_count_all_001
# strategy: strategy1 boundary-value attack (positive/baseline faces of the
#           count promise: omitted filter = all points; exact default = exact)
# endpoint: points+count
# constraint_ids: qdrant_behavioral_points_count_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/count-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the DEFAULT exact=true face is
#            the one developers never re-verify; if the default silently
#            degraded to approximate, nobody would notice)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 positive-baseline x qdrant_behavioral_points_count_001 —
  the promise "HTTP 200 with {count}; exact=true returns the exact number of
  points (all points when the filter is omitted)" verified on a LIVE
  data-bearing collection seeded with N=12 uniquely-identified points
  (fresh uuid-tagged collection => zero pre-existing ids, satisfying the R33
  id-collision analysis: every count expectation is arithmetic-derived from
  this seed set alone). Faces:
    F1 omitted filter (body {}) — exact default in force: 200 with
       result.count == 12; result.count must be a true integer per
       published response_shape result.count:integer.
    F2 explicit {"exact": true} — must agree with F1: result.count == 12
       (explicit true and the default are the same face).
    F3 cross-face agreement (R31/R33 instrument): POST points+scroll with no
       filter must return EXACTLY the 12 seeded ids (set equality, paginated
       to exhaustion) — the count face and the scroll face must agree on N.
  [chunk_points+count coverage: strategy1 positive-baseline x
  qdrant_behavioral_points_count_001 (this script; filter arithmetic faces in
  boundary_points_count_filter_arith_002, filter type-confusion faces in
  boundary_points_count_filter_type_003, min_should branch faces in
  boundary_points_count_min_should_004, exact type-confusion faces in
  boundary_points_count_exact_type_005, malformed-body faces in
  boundary_points_count_malformed_006)]
Oracle: F1 -> 200 with result.count == 12 (integer); F2 -> 200 with
  result.count == 12 and equal to F1; count != 12 = Type4_StateLogicViolation;
  result.count non-integer = Type1_IllegalSuccess (response_shape violation);
  4xx on F1/F2 (valid requests) = Type1_IllegalSuccess (promise: HTTP 200
  with {count}); 5xx with /healthz alive = Type3_RuntimeFailure; F3 ->
  scroll id set == seeded 12-id set, else Type4 cross-face disagreement;
  transport failure -> /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_count_001).
Constraint: qdrant_behavioral_points_count_001 (bare id) — "exact=true
  (default) performs an exact count (slower); an omitted filter counts all
  points" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+count         -> POST /collections/{collection_name}/points/count
  points+scroll        -> POST /collections/{collection_name}/points/scroll
  collections+create   -> PUT  /collections/{collection_name}
  collections+delete   -> DELETE /collections/{collection_name}
  points+upsert        -> PUT  /collections/{collection_name}/points
  healthz              -> GET  /healthz
  (wait is a query parameter on the upsert face — passed via params=)
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
N_SEED = 12
BERLIN_N = 8
PARIS_N = 4  # BERLIN_N + PARIS_N == N_SEED (arithmetic-derived expectations)
V = [0.1, 0.2, 0.3, 0.4]
SEEDED_IDS = list(range(1, N_SEED + 1))


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


def count_face(coll, count_body):
    """POST one count request; returns (status, count_or_None, body, raw)."""
    s, body, raw = safe_request("POST", f"/collections/{coll}/points/count",
                                json=count_body, timeout=60)
    count = None
    if s == 200 and isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, dict):
            count = r.get("count")
    return s, count, body, raw


def extract_count_typed(body, raw):
    """Extract result.count with response_shape typing (true integer, not bool/str)."""
    if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
        return None, False
    c = body["result"].get("count")
    is_int = isinstance(c, int) and not isinstance(c, bool)
    return c, is_int


coll = ""


def main():
    global coll
    tag = uuid.uuid4().hex[:8]
    coll = "bpcA1" + tag

    # Arrange: own collection + N_SEED uniquely-tagged points (wait=true => durable
    # before any count face runs, so exact-count expectations are deterministic)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    points = []
    for i in SEEDED_IDS:
        city = "berlin" if i <= BERLIN_N else "paris"
        points.append({"id": i, "vector": V, "payload": {"city": city}})
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": points}, params={"wait": "true"}, timeout=120)
    if s not in (200, 201):
        print(f"setup upsert failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # ---- F1: omitted filter (body {}), exact default in force ----
        s1, c1, body1, raw1 = count_face(coll, {})
        print(f"F1 count {{}} (omitted filter, exact default) -> status={s1}")
        print(f"raw: {raw1[:400]}")
        if s1 == -1:
            transport_dead("F1 count omitted-filter")
            return
        if 500 <= s1 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F1: count on a "
                      f"valid live collection returned {s1}: {raw1[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F1 5xx and healthz down")
            return
        if not (200 <= s1 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F1: valid count "
                  f"request rejected with {s1} (promise: HTTP 200 with count): "
                  f"{raw1[:300]}")
            return
        c1, int1 = extract_count_typed(body1, raw1)
        if not int1:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F1: result.count "
                  f"is not an integer (response_shape result.count:integer): "
                  f"{raw1[:300]}")
            return
        if c1 != N_SEED:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F1: omitted "
                  f"filter must count ALL points: expected exactly {N_SEED} "
                  f"(arithmetic-derived from the seed set), got {c1}: {raw1[:300]}")
            return
        print(f"F1: result.count == {c1} == N_SEED (omitted filter counts all)")

        # ---- F2: explicit exact=true must agree with the default face ----
        s2, c2, body2, raw2 = count_face(coll, {"exact": True})
        print(f"\nF2 count {{\"exact\": true}} -> status={s2}")
        print(f"raw: {raw2[:400]}")
        if s2 == -1:
            transport_dead("F2 count explicit-exact")
            return
        if 500 <= s2 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F2: explicit "
                      f"exact=true count returned {s2}: {raw2[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F2 5xx and healthz down")
            return
        if not (200 <= s2 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F2: valid "
                  f"exact=true count rejected with {s2}: {raw2[:300]}")
            return
        c2, int2 = extract_count_typed(body2, raw2)
        if not int2:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F2: result.count "
                  f"not an integer: {raw2[:300]}")
            return
        if c2 != N_SEED or c2 != c1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F2: "
                  f"exact=true must return the exact total ({N_SEED}) and agree "
                  f"with the default face ({c1}), got {c2}: {raw2[:300]}")
            return
        print(f"F2: result.count == {c2} == {N_SEED}, agrees with F1 default face")

        # ---- F3: cross-face agreement (scroll face must see the same N points) ----
        got_ids = set()
        offset = None
        pages = 0
        f3_status = None
        f3_raw = ""
        while pages < 5:
            body = {"limit": 100, "with_payload": False, "with_vector": False}
            if offset is not None:
                body["offset"] = offset
            s3, b3, raw3 = safe_request("POST", f"/collections/{coll}/points/scroll",
                                        json=body, timeout=60)
            f3_status, f3_raw = s3, raw3
            pages += 1
            if s3 == -1:
                if not transport_dead("F3 scroll cross-face"):
                    return
            if 500 <= s3 <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F3: scroll "
                          f"cross-face returned {s3}: {raw3[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — F3 5xx and healthz down")
                return
            if not (200 <= s3 <= 299):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F3: valid "
                      f"scroll rejected with {s3}: {raw3[:300]}")
                return
            result = b3.get("result") if isinstance(b3, dict) else None
            pts = result.get("points") if isinstance(result, dict) else None
            if not isinstance(pts, list):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F3: scroll "
                      f"result.points not an array: {raw3[:300]}")
                return
            for p in pts:
                if isinstance(p, dict):
                    got_ids.add(p.get("id"))
            next_page = result.get("next_page") if isinstance(result, dict) else None
            if not next_page:
                break
            offset = next_page
        print(f"\nF3 scroll cross-face -> status={f3_status}, unique ids seen: "
              f"{len(got_ids)} over {pages} page(s)")
        expected_ids = set(SEEDED_IDS)
        if got_ids != expected_ids:
            missing = expected_ids - got_ids
            extra = got_ids - expected_ids
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F3: count "
                  f"face says {N_SEED} but scroll face returns {len(got_ids)} "
                  f"unique ids (missing={sorted(missing)[:10]}, "
                  f"extra={sorted(extra)[:10]}) — cross-face disagreement: "
                  f"{f3_raw[:300]}")
            return
        print(f"F3: scroll id set == seeded 12-id set (count/scroll faces agree)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
