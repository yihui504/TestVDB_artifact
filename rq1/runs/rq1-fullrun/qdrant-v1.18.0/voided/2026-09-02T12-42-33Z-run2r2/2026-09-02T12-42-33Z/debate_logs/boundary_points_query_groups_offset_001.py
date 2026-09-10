#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_groups_offset_001
# strategy: state-consistency attack on the documented "groups endpoints do
#           not allow offset (pagination)" restriction — reject-or-omit
#           adjudication with an identical-results fingerprint (G4: a live
#           no-offset baseline makes "omit" falsifiable, not assumed)
# endpoint: points+query+groups
# constraint_ids: qdrant_state_points_query_groups_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-04 (Boundary Default Optimism — the docs promise pagination
#            is NOT available with groups; a server that silently HONORS an
#            offset on this face contradicts its own documented restriction
#            and strands clients who port paginated code from the plain
#            query face)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state/doc-consistency x qdrant_state_points_query_groups_001 — the
  contract asserts "the groups query API does not allow offset
  (pagination)... pagination is not available with groups" on POST
  /collections/{c}/points/query/groups. The contract parameter list for
  this endpoint indeed has NO offset parameter, so the documented promise
  admits exactly two conforming dispositions when a client sends offset
  anyway: REJECT (clean 400/422) or OMIT (200 with results IDENTICAL to
  the no-offset baseline — the stray key has no effect). Measured on a
  12-point seeded collection (3 groups x 4 points, dim 4, Euclid,
  params.exact=true for deterministic fingerprints):
    B      baseline, no offset            -> 200; fingerprint F0 (ordered
                                             [(group id, ordered hit ids)])
    O0     offset=0                       -> 400/422, or 200 with F == F0
    O1     offset=1                       -> 400/422, or 200 with F == F0
    O5     offset=5                       -> 400/422, or 200 with F == F0
    Ohuge  offset=999999                  -> 400/422, or 200 with F == F0
  The defect signal is the third, undocumented disposition: 200 with
  F != F0 — offset actually PAGINATED the groups result (groups skipped or
  shifted), contradicting "pagination is not available with groups".
  [chunk_points+query+groups coverage (8 scripts): strategy1 group_size
  boundary x range_points_query_groups_001 (groupsize_001); strategy1 limit
  boundary x range_points_query_groups_001 (limit_001); strategy6 limit x
  group_size resource combo x range_points_query_groups_001 (resource_001);
  state offset-not-allowed reject-or-omit x state_points_query_groups_001
  (this script); behavioral positive grouping-correctness + keyless-point
  exclusion x behavioral_points_query_groups_001 (groupby_values_001);
  strategy2 invalid group_by faces + 404 x behavioral_points_query_groups_001
  (invalid_groupby_001); strategy2 R33/R40 dual-key oneOf cross-face
  (single vs groups) x behavioral_points_query_groups_001 (dualkey_001);
  strategy7 malformed stream x behavioral_points_query_groups_001
  (malformed_001)]
Oracle: B -> 200 with 3 groups (a/b/c) and 4 hits each, establishing
  fingerprint F0; every offset leg -> either clean 400/422 (reject branch,
  conforms) or 200 with fingerprint IDENTICAL to F0 (omit branch, conforms);
  DEFECT (Type4_StateLogicViolation) on any offset leg returning 200 with
  F != F0 (offset paginated the groups face — documented restriction
  violated); DEFECT (Type3_RuntimeFailure) on 5xx with /healthz alive or
  transport failure with /healthz alive; /healthz down or unenveloped 200 =
  SCRIPT_ERROR; 4xx on the baseline B itself = Type1_IllegalSuccess (valid
  documented group query rejected) (constraint
  qdrant_state_points_query_groups_001).
Constraint: qdrant_state_points_query_groups_001 (bare id) — "the groups
  query API does not allow offset (pagination); the same restriction
  applies to the legacy search/recommend groups variants" (evidence_tier:
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
GRP = "grp"
V = [0.5, 0.25, 0.125, 0.0625]
GROUPS = {"a": [1, 2, 3, 4], "b": [5, 6, 7, 8], "c": [9, 10, 11, 12]}


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


def fingerprint(groups):
    """Ordered fingerprint [(group id, [hit ids in order])]."""
    fp = []
    for g in groups:
        if not isinstance(g, dict):
            fp.append(("<non-dict-group>", []))
            continue
        ids = [h.get("id") for h in (g.get("hits") or []) if isinstance(h, dict)]
        fp.append((g.get("id"), ids))
    return fp


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bqgsO" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = []
        for gval, ids in GROUPS.items():
            for i in ids:
                pts.append({
                    "id": i,
                    "vector": [v * (1.0 + i / 100.0) for v in V],
                    "payload": {GRP: gval},
                })
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

        body = {"query": {"nearest": V}, "group_by": GRP, "limit": 3,
                "group_size": 4, "params": {"exact": True}}

        # ---- Leg B: live baseline, no offset ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/query/groups",
                                 json=body, timeout=60)
        print(f"\nleg B baseline (no offset) -> status={s}")
        print(f"raw: {raw[:500]}")
        if transport_or_5xx("B baseline", s, raw):
            return
        groups, shape = extract_groups(b)
        if s in (400, 404, 422):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [B baseline]: the "
                  f"documented group query without offset was rejected with {s}: {raw[:300]}")
            return
        if s != 200 or groups is None:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status/envelope {s} ({shape}); no defect conclusion")
            return
        if len(groups) != 3:
            print(f"VERDICT: SCRIPT_ERROR — baseline expected 3 groups (a/b/c, limit=3, "
                  f"group_size=4), got {len(groups)}; no defect conclusion")
            return
        F0 = fingerprint(groups)
        print(f"leg B OK: baseline fingerprint F0 = {F0}")

        # ---- Offset legs: reject or omit; anything else is a defect ----
        for label, off in (("O0 offset=0", 0), ("O1 offset=1", 1),
                           ("O5 offset=5", 5), ("Ohuge offset=999999", 999999)):
            leg_body = dict(body)
            leg_body["offset"] = off
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query/groups",
                                     json=leg_body, timeout=60)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if transport_or_5xx(label, s, raw):
                return
            if s in (400, 422):
                # Type2 observation only (R29: error-naming carries no verdict weight)
                named = "offset" in raw.lower()
                print(f"leg {label} OK: clean {s} rejection — reject branch conforms "
                      f"(error names 'offset': {named})")
                continue
            if s == 200:
                groups, shape = extract_groups(b)
                if groups is None:
                    print(f"VERDICT: SCRIPT_ERROR — 200 but no groups array ({shape}); no defect conclusion")
                    return
                F = fingerprint(groups)
                if F != F0:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: "
                          f"the contract states pagination is NOT available on the groups face, "
                          f"but offset changed the result — offset was silently HONORED "
                          f"(baseline F0={F0} vs offset F={F}): {raw[:300]}")
                    return
                print(f"leg {label} OK: 200 with fingerprint identical to baseline — omit "
                      f"branch conforms (offset has no effect)")
                continue
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
