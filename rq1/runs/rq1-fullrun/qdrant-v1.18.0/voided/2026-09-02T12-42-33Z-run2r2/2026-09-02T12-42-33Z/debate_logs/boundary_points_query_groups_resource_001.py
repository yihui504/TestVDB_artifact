#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_groups_resource_001
# strategy: strategy6 resource-limit attack — limit x group_size BOTH
#           extreme simultaneously on the grouped query face (the qdrant
#           #8406 shape: allocator preallocation driven by the product of
#           the two caps; single-parameter extremes included as controls)
# endpoint: points+query+groups
# constraint_ids: qdrant_range_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-07 (Resource Exhaustion Optimism — the docs give only
#            minima for limit/group_size; implementers assume clients send
#            sane products, so a huge limit x group_size product may hit an
#            unchecked capacity computation: OOM / panic / 5xx)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 resource x qdrant_range_points_query_groups_001 — the
  contract bounds group_size/limit only from BELOW (min 1 each); the
  resource class probes the implementation's UPPER behavior on a 12-point
  seeded collection (4 groups x 3 points, dim 4, Euclid), per the qdrant
  #8406 shape (limit x group_size product drives allocator capacity):
    R1     limit=1e6, group_size=1e6 (both extreme)   -> 200 with <= 12
                                                       hits and <= 4 groups,
                                                       or clean 400/422
    R2     limit=1e8, group_size=1e8 (both extreme)   -> same expectation
    Rmax   limit=INT_MAX(2147483647), group_size=INT_MAX -> same expectation
  Key (strategy6 differs from strategy1): 200 accepting a huge value is NOT
  a defect (the caps are upper bounds; returning fewer results is legal);
  the defect signal is a CRASH — 5xx, OOM/panic text, connection reset, a
  transport failure while /healthz stays alive (hang), or REQUEST-TRIGGERED
  SERVER DEATH: transport death on an extreme leg with /healthz DOWN
  afterward (R11 framing — contract-legal parameters with no documented
  maxima killing the server are the resource_bound violation itself, not a
  script error; docker-level OOMKilled/exit-137 facts supplied by the
  executor corroborate what this HTTP-level script observes).
  [chunk_points+query+groups coverage (8 scripts): strategy1 group_size
  boundary x range_points_query_groups_001 (groupsize_001); strategy1 limit
  boundary x range_points_query_groups_001 (limit_001); strategy6 limit x
  group_size resource combo x range_points_query_groups_001 (this script);
  state offset-not-allowed reject-or-omit x state_points_query_groups_001
  (offset_001); behavioral positive grouping-correctness + keyless-point
  exclusion x behavioral_points_query_groups_001 (groupby_values_001);
  strategy2 invalid group_by faces + 404 x behavioral_points_query_groups_001
  (invalid_groupby_001); strategy2 R33/R40 dual-key oneOf cross-face
  (single vs groups) x behavioral_points_query_groups_001 (dualkey_001);
  strategy7 malformed stream x behavioral_points_query_groups_001
  (malformed_001)]
Oracle: every leg -> 200 with total hits <= 12 and group count <= 4, or a
  clean 400/422 (either disposition is the resource-class norm); DEFECT
  (Type3_RuntimeFailure) on 5xx with /healthz alive, on OOM/panic/capacity-
  overflow text in the body, on transport failure with /healthz alive
  (hang/DoS), and on transport death (disconnect/reset) during an extreme
  leg with /healthz DOWN after it — server killed by the request
  (resource_bound; R11 framing); DEFECT (Type4_StateLogicViolation) if 200
  returns MORE than the 12 stored points or more than 4 groups; /healthz
  down BEFORE any extreme leg was sent = SCRIPT_ERROR (environment noise
  guard) (constraint qdrant_range_points_query_groups_001).
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
N_SEED = 12  # 4 groups x 3 points
GRP = "grp"
V = [0.5, 0.25, 0.125, 0.0625]
CRASH_MARKERS = ("oom", "out of memory", "panic", "capacity overflow", "killed")


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


def group_hits(g):
    if isinstance(g, dict):
        h = g.get("hits")
        if isinstance(h, list):
            return h
    return None


def crash_text(raw):
    low = str(raw).lower()
    return next((m for m in CRASH_MARKERS if m in low), None)


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bqgsR" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = []
        for i in range(1, N_SEED + 1):
            grp_value = ["gA", "gB", "gC", "gD"][(i - 1) // 3]
            pts.append({
                "id": i,
                "vector": [v * (1.0 + i / 100.0) for v in V],
                "payload": {GRP: grp_value},
            })
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        s_ix, _, raw_ix = safe_request("PUT", f"/collections/{coll}/index",
                                       json={"field_name": GRP, "field_schema": {"type": "keyword"}},
                                       params={"wait": "true"}, timeout=60)
        print(f"setup payload index on '{GRP}': status={s_ix} (best-effort, non-fatal)")

        # environment-noise guard: a later healthz-DOWN death verdict is
        # attributable to the request only if the server was alive before
        # any extreme leg fired; dead-before-any-leg stays SCRIPT_ERROR
        alive0, hs0, _ = healthz_alive()
        if not alive0:
            print(f"VERDICT: SCRIPT_ERROR — /healthz down before any extreme leg "
                  f"(environment noise guard): status={hs0}")
            return

        # ---- Resource legs: limit x group_size both extreme ----
        for label, lim, gsize in (
            ("R1 limit=1e6 group_size=1e6", 1000000, 1000000),
            ("R2 limit=1e8 group_size=1e8", 100000000, 100000000),
            ("Rmax limit=INT_MAX group_size=INT_MAX", 2147483647, 2147483647),
        ):
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query/groups",
                                     json={"query": {"nearest": V}, "group_by": GRP,
                                           "limit": lim, "group_size": gsize},
                                     timeout=180)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: request "
                          f"did not complete (transport error/reset) while /healthz alive "
                          f"(allocator/OOM hang signal): {str(raw)[:200]}")
                else:
                    # death oracle (R11 framing, 8d.5 send-back): the leg
                    # parameters are contract-legal (documented minima only,
                    # no maxima), so a transport death coinciding with
                    # /healthz going DOWN means the request KILLED the
                    # server — the resource_bound violation itself, not a
                    # script error.
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}] "
                          f"limit={lim} group_size={gsize}: transport death (disconnect/reset) "
                          f"+ /healthz DOWN post-request = server killed by request "
                          f"(resource_bound; R11 framing)")
                return
            marker = crash_text(raw)
            if marker:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: crash marker "
                      f"'{marker}' in response body: {raw[:300]}")
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: huge "
                          f"limit x group_size returned {s} with service alive (OOM/DoS): {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s in (400, 422):
                print(f"leg {label} OK: clean {s} rejection (resource-class norm)")
                continue
            if s == 200:
                groups, shape = extract_groups(b)
                if groups is None:
                    print(f"VERDICT: SCRIPT_ERROR — 200 but no groups array ({shape}); no defect conclusion")
                    return
                n_hits = sum(len(group_hits(g) or []) for g in groups)
                if len(groups) > 4:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: only "
                          f"4 groups exist but {len(groups)} returned: {raw[:300]}")
                    return
                if n_hits > N_SEED:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: only "
                          f"{N_SEED} points exist but {n_hits} hits returned: {raw[:300]}")
                    return
                print(f"leg {label} OK: 200 with {len(groups)} groups / {n_hits} hits "
                      f"<= caps (upper-bound semantics, no crash)")
                continue
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
            return

        # post-batch liveness confirmation (container may die AFTER responding)
        alive, hs, hraw = healthz_alive()
        print(f"\npost-batch /healthz: alive={alive} status={hs}")
        if not alive:
            print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — service died after the "
                  "resource legs completed (delayed OOM/crash)")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
