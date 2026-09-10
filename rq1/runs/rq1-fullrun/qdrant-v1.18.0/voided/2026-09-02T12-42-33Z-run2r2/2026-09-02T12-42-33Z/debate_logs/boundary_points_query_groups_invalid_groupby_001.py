#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_groups_invalid_groupby_001
# strategy: strategy2 type-boundary attack on the group_by parameter
#           (required string face of the grouped query API) plus the
#           documented 404 face for a missing collection — each invalid
#           shape must draw a clean 400, the missing collection a 404
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the REST layer is
#            assumed to validate the one required body field; a null/int/
#            empty group_by sliding through serde produces undefined
#            grouping behavior instead of a clean 4xx)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type x qdrant_behavioral_points_query_groups_001 — the
  contract asserts "grouping requires payload values for the group_by
  field; ... 400 on an invalid group_by; 404 for a missing collection" on
  POST /collections/{c}/points/query/groups, and request_required_paths
  lists group_by as the sole required body field. Negative faces on a
  3-point seeded collection (grp=a, dim 4, Euclid):
    Cvalid  group_by="grp" (live positive control)  -> 200 (face proven
                                                      alive before negatives)
    GBmiss  group_by omitted (required field absent)-> 400
    GBempty group_by="" (empty field selector)      -> 400
    GBint   group_by=123 (type confusion)           -> 400
    GBnull  group_by=null (null injection)          -> 400
    GBabsent group_by="definitely_missing_field_xyz" -> 400 (no point
             carries it: grouping cannot satisfy "requires payload values",
             i.e. an invalid group_by per the assertion's own wording)
    C404    the fully valid body against a collection that does not exist
            -> 404 (documented mapping)
  [chunk_points+query+groups coverage (8 scripts): strategy1 group_size
  boundary x range_points_query_groups_001 (groupsize_001); strategy1 limit
  boundary x range_points_query_groups_001 (limit_001); strategy6 limit x
  group_size resource combo x range_points_query_groups_001 (resource_001);
  state offset-not-allowed reject-or-omit x state_points_query_groups_001
  (offset_001); behavioral positive grouping-correctness + keyless-point
  exclusion x behavioral_points_query_groups_001 (groupby_values_001);
  strategy2 invalid group_by faces + 404 x behavioral_points_query_groups_001
  (this script); strategy2 R33/R40 dual-key oneOf cross-face
  (single vs groups) x behavioral_points_query_groups_001 (dualkey_001);
  strategy7 malformed stream x behavioral_points_query_groups_001
  (malformed_001)]
Oracle: Cvalid -> 200 with a groups array (proves the face; 4xx here =
  Type1_IllegalSuccess, setup-face); GBmiss/GBempty/GBint/GBnull/GBabsent ->
  400 or 422 each (a 200 = Type1_IllegalSuccess: invalid group_by accepted,
  contradicting the assertion's explicit "400 on an invalid group_by"); 5xx
  on any leg with /healthz alive = Type3_RuntimeFailure; C404 -> 404 (200 =
  Type1_IllegalSuccess: a missing collection reported as success; 5xx =
  Type3; a different 4xx is RECORDED as a status-mapping deviation for
  judge weighing — validation-ordering is an implementation detail — and
  does not end the verdict); /healthz down = SCRIPT_ERROR (constraint
  qdrant_behavioral_points_query_groups_001).
Constraint: qdrant_behavioral_points_query_groups_001 (bare id) —
  "grouping requires payload values for the group_by field; returns 200
  {groups: [{id, hits}]}; 400 on an invalid group_by; 404 for a missing
  collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+groups -> POST /collections/{collection_name}/points/query/groups
  points+upsert       -> PUT  /collections/{collection_name}/points
  index+create        -> PUT  /collections/{collection_name}/index
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
  (wait is a query parameter on the upsert/index faces — passed via params=)
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
GRP = "grp"
V = [0.5, 0.25, 0.125, 0.0625]


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/consistency) via params= — never stuffed into the body.
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


def transport_or_5xx(label, s, raw):
    """Returns True (with verdict printed) when the leg must stop; None = fine."""
    if s == -1:
        alive, _, _ = healthz_alive()
        if alive:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: request did "
                  f"not complete (transport error) while /healthz alive (hang/DoS): {str(raw)[:200]}")
        else:
            print("VERDICT: SCRIPT_ERROR — transport failure and healthz down")
        return True
    if 500 <= s <= 599:
        alive, _, _ = healthz_alive()
        if alive:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: got {s} "
                  f"with service alive: {str(raw)[:300]}")
        else:
            print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
        return True
    return None


def extract_groups(body):
    """
    Locate the groups array in the response envelope.
    Contract response_shape: result (object) -> result.groups (array).
    """
    if not isinstance(body, dict):
        return None, "body-not-dict"
    result = body.get("result")
    if isinstance(result, dict):
        g = result.get("groups")
        return (g if isinstance(g, list) else None), "result.groups"
    if isinstance(result, list):
        return result, "result-array-observed"
    return None, "result-missing"


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bqgsI" + tag
    ghost_coll = "bqgsNo_" + tag + "_missing"

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{"id": i,
                "vector": [v * (1.0 + i / 100.0) for v in V],
                "payload": {GRP: "a"}} for i in range(1, 4)]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        s_ix, _, _ = safe_request("PUT", f"/collections/{coll}/index",
                                  json={"field_name": GRP, "field_schema": {"type": "keyword"}},
                                  params={"wait": "true"}, timeout=60)
        print(f"setup payload index on '{GRP}': status={s_ix} (best-effort, non-fatal)")

        # ---- Leg Cvalid: live positive control (G4 — prove the face first) ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/query/groups",
                                 json={"query": {"nearest": V}, "group_by": GRP, "limit": 3},
                                 timeout=60)
        print(f"\nleg Cvalid group_by='grp' -> status={s}")
        print(f"raw: {raw[:400]}")
        if transport_or_5xx("Cvalid", s, raw):
            return
        groups, shape = extract_groups(b)
        if s in (400, 404, 422):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [Cvalid]: documented "
                  f"valid group query rejected with {s}: {raw[:300]}")
            return
        if s != 200 or groups is None:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status/envelope {s} ({shape}); no defect conclusion")
            return
        print(f"leg Cvalid OK: 200 with {len(groups)} group(s) — face alive")

        # ---- Negative legs: invalid group_by shapes -> clean 4xx ----
        OMIT = object()  # sentinel: leave the required field out entirely
        negative_legs = (
            ("GBmiss group_by-omitted", OMIT),
            ("GBempty group_by=''", ""),
            ("GBint group_by=123", 123),
            ("GBnull group_by=null", None),
            ("GBabsent group_by='definitely_missing_field_xyz'",
             "definitely_missing_field_xyz"),
        )
        for label, gb in negative_legs:
            body = {"query": {"nearest": V}, "limit": 3, "group_size": 3}
            if gb is not OMIT:
                body["group_by"] = gb
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query/groups",
                                     json=body, timeout=60)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if transport_or_5xx(label, s, raw):
                return
            if s == 200:
                groups, _ = extract_groups(b)
                n = len(groups) if groups is not None else -1
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: the "
                      f"contract maps an invalid group_by to 400, but the request was "
                      f"ACCEPTED with 200 ({n} groups returned): {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return
            # Type2 observation only (R29: error-naming carries no verdict weight)
            named = "group_by" in raw.lower()
            print(f"leg {label} OK: rejected with {s} (error names 'group_by': {named})")

        # ---- Leg C404: fully valid body against a missing collection ----
        s, b, raw = safe_request("POST", f"/collections/{ghost_coll}/points/query/groups",
                                 json={"query": {"nearest": V}, "group_by": GRP, "limit": 3},
                                 timeout=60)
        print(f"\nleg C404 missing collection '{ghost_coll}' -> status={s}")
        print(f"raw: {raw[:400]}")
        if transport_or_5xx("C404", s, raw):
            return
        if s == 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [C404]: a group query "
                  f"against a NONEXISTENT collection returned 200 success: {raw[:300]}")
            return
        if s == 404:
            print("leg C404 OK: 404 for the missing collection (documented mapping)")
        elif 400 <= s <= 499:
            # recorded deviation only — validation-vs-existence ordering is an
            # implementation detail; the client still receives a 4xx
            print(f"leg C404 DEVIATION RECORDED: documented mapping is 404, got {s} "
                  f"(judge weighing: validation ordering); not a defect by itself")
        # any 5xx already handled by transport_or_5xx

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
