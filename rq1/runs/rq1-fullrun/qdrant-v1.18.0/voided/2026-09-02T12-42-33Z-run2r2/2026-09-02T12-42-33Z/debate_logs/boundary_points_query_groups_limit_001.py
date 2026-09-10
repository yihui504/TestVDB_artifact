#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_groups_limit_001
# strategy: strategy1 boundary-value attack on the limit parameter of the
#           grouped universal query API (min-1 promise + default-10-groups
#           promise), with a strategy2 type-confusion cross-leg
# endpoint: points+query+groups
# constraint_ids: qdrant_range_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — clients trust limit>=1 is
#            enforced and that omitting limit yields the documented default
#            of 10 groups; a server accepting 0/-1 or returning a different
#            group count silently breaks group pagination arithmetic)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary x qdrant_range_points_query_groups_001 — the
  contract asserts "limit minimum 1 (default 10, max amount of groups)" on
  POST /collections/{c}/points/query/groups. Boundary matrix on a 12-group
  seeded collection (12 distinct group values, 1 point each, dim 4, Euclid):
    L1    limit=1 (min legal closure)   -> 200, EXACTLY 1 group
    L2    limit=2 (interior point)      -> 200, EXACTLY 2 groups
    Ldef  limit omitted (default leg)   -> 200, EXACTLY 10 groups
                                           (documented default 10; 12 exist)
    L0    limit=0 (min-1 boundary)      -> 400/422 reject
    Lneg  limit=-1 (negative boundary)  -> 400/422 reject
    Ltype limit="10" (string, strategy2 -> 400/422 reject
          cross-leg)
  [chunk_points+query+groups coverage (8 scripts): strategy1 group_size
  boundary x range_points_query_groups_001 (groupsize_001); strategy1 limit
  boundary x range_points_query_groups_001 (this script); strategy6 limit x
  group_size resource combo x range_points_query_groups_001 (resource_001);
  state offset-not-allowed reject-or-omit x state_points_query_groups_001
  (offset_001); behavioral positive grouping-correctness + keyless-point
  exclusion x behavioral_points_query_groups_001 (groupby_values_001);
  strategy2 invalid group_by faces + 404 x behavioral_points_query_groups_001
  (invalid_groupby_001); strategy2 R33/R40 dual-key oneOf cross-face
  (single vs groups) x behavioral_points_query_groups_001 (dualkey_001);
  strategy7 malformed stream x behavioral_points_query_groups_001
  (malformed_001)]
Oracle: L1 -> 200 with exactly 1 group; L2 -> 200 with exactly 2 groups;
  Ldef -> 200 with exactly 10 groups (arithmetic closure: 12 groups exist,
  default cap must be 10; any other group count = Type4_StateLogicViolation);
  L0/Lneg/Ltype -> 400 or 422 (200 = Type1_IllegalSuccess: min-1 promise
  violated); 4xx on L1/L2/Ldef = Type1_IllegalSuccess (valid documented
  request rejected); 5xx with /healthz alive = Type3_RuntimeFailure;
  transport error with /healthz alive = Type3 hang, healthz down =
  SCRIPT_ERROR (constraint qdrant_range_points_query_groups_001).
Constraint: qdrant_range_points_query_groups_001 (bare id) — "group_size
  minimum 1 (default 3); limit minimum 1 (default 10)" (evidence_tier:
  explicit; level: endpoint)

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
N_GROUPS = 12  # 12 distinct group values, 1 point each
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
    Contract response_shape: result (object) -> result.groups (array of
    {id, hits, lookup}). A legacy/direct list-form result is tolerated and
    reported so the observed envelope shape reaches the judge.
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
    coll = "bqgsL" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{
            "id": i,
            "vector": [v * (1.0 + i / 100.0) for v in V],
            "payload": {GRP: f"g{i:02d}"},
        } for i in range(1, N_GROUPS + 1)]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        # best-effort payload index on the group_by field (prudence per the
        # R40 order_by lesson; the contract does NOT require an index here)
        s_ix, _, raw_ix = safe_request("PUT", f"/collections/{coll}/index",
                                       json={"field_name": GRP, "field_schema": {"type": "keyword"}},
                                       params={"wait": "true"}, timeout=60)
        print(f"setup payload index on '{GRP}': status={s_ix} (best-effort, non-fatal)")

        base = {"query": {"nearest": V}, "group_by": GRP, "group_size": 3}

        # ---- Positive legs: limit closure + default (G4) ----
        for label, extra, expect_groups in (
            ("L1 limit=1", {"limit": 1}, 1),
            ("L2 limit=2", {"limit": 2}, 2),
            ("Ldef limit-omitted", {}, 10),
        ):
            body = dict(base)
            body.update(extra)
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query/groups",
                                     json=body, timeout=60)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if transport_or_5xx(label, s, raw):
                return
            groups, shape = extract_groups(b)
            if s in (400, 404, 422):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: documented "
                      f"legal limit rejected with {s}: {raw[:300]}")
                return
            if s != 200 or groups is None:
                print(f"VERDICT: SCRIPT_ERROR — unexpected status/envelope {s} ({shape}); no defect conclusion")
                return
            if len(groups) != expect_groups:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: {N_GROUPS} "
                      f"groups exist and the cap for this leg is {expect_groups}, but "
                      f"{len(groups)} groups returned: {raw[:300]}")
                return
            print(f"leg {label} OK: exactly {expect_groups} groups (envelope {shape})")

        # ---- Negative legs: L0 / Lneg / Ltype -> must be rejected ----
        for label, lim in (("L0 limit=0", 0), ("Lneg limit=-1", -1),
                           ("Ltype limit='10'", "10")):
            body = dict(base)
            body["limit"] = lim
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query/groups",
                                     json=body, timeout=60)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if transport_or_5xx(label, s, raw):
                return
            if s == 200:
                groups, _ = extract_groups(b)
                n = len(groups) if groups is not None else -1
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: contract "
                      f"asserts limit minimum 1, but the request was ACCEPTED with 200 "
                      f"({n} groups returned): {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return
            # Type2 observation only (R29: error-naming carries no verdict weight)
            named = "limit" in raw.lower()
            print(f"leg {label} OK: rejected with {s} (error names 'limit': {named})")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
