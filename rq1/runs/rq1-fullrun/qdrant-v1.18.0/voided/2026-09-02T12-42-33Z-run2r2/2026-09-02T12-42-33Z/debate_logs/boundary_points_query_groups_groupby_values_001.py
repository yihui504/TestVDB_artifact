#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_groups_groupby_values_001
# strategy: behavioral positive-closure attack (G4) — grouping correctness
#           on the group_by payload field: envelope shape {groups:[{id,
#           hits}]}, group ids == distinct payload values, membership
#           correctness (hit payload == its group id), and the "grouping
#           requires payload values" promise (keyless points must be
#           excluded from every group)
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Semantic Contract Optimism — grouping is trusted to
#            bucket by payload value; a bucket that mixes values, invents a
#            null group for keyless points, or drops a populated group
#            corrupts every downstream consumer silently)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral positive x qdrant_behavioral_points_query_groups_001 —
  the contract asserts "grouping requires payload values for the group_by
  field; returns 200 {groups: [{id, hits}]}" on POST /collections/{c}/
  points/query/groups. Positive closure on a 7-point seeded collection
  (dim 4, Euclid, params.exact=true, with_payload=true):
    keyed points:   id1,id2 -> grp=a   id3,id4 -> grp=b   id5 -> grp=c
    keyless points: id6, id7 carry NO grp payload key
  P1  200 envelope: result.groups is an array whose entries carry id+hits
  P2  exactly 3 groups, ids exactly {a, b, c} (no null/missing group id —
      keyless points must not materialize a group)
  P3  cardinality closure: a=2 hits, b=2 hits, c=1 hit (limit=10 and
      group_size=10 exceed every cardinality, so caps cannot mask a miss)
  P4  membership correctness: every hit's payload[grp] == its group id
  P5  keyless exclusion: ids 6 and 7 appear in NO group's hits ("grouping
      requires payload values for the group_by field")
  [chunk_points+query+groups coverage (8 scripts): strategy1 group_size
  boundary x range_points_query_groups_001 (groupsize_001); strategy1 limit
  boundary x range_points_query_groups_001 (limit_001); strategy6 limit x
  group_size resource combo x range_points_query_groups_001 (resource_001);
  state offset-not-allowed reject-or-omit x state_points_query_groups_001
  (offset_001); behavioral positive grouping-correctness + keyless-point
  exclusion x behavioral_points_query_groups_001 (this script); strategy2
  invalid group_by faces + 404 x behavioral_points_query_groups_001
  (invalid_groupby_001); strategy2 R33/R40 dual-key oneOf cross-face
  (single vs groups) x behavioral_points_query_groups_001 (dualkey_001);
  strategy7 malformed stream x behavioral_points_query_groups_001
  (malformed_001)]
Oracle: P1 -> 200 with result.groups[] entries each carrying id and hits
  (missing envelope = SCRIPT_ERROR); P2 -> group ids exactly {a,b,c} — a
  null/absent/extra group id = Type4_StateLogicViolation; P3 -> per-group
  hit counts exactly 2/2/1 — any other count with caps at 10 =
  Type4_StateLogicViolation; P4 -> every hit payload[grp] equals its group
  id — a mismatched hit = Type4_StateLogicViolation; P5 -> keyless ids 6,7
  absent from all hits — their presence = Type4_StateLogicViolation
  (violates the documented "grouping requires payload values" promise);
  4xx on this fully valid request = Type1_IllegalSuccess; 5xx with
  /healthz alive = Type3_RuntimeFailure; transport with /healthz alive =
  Type3 hang, healthz down = SCRIPT_ERROR (constraint
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
  (wait is a query parameter on the upsert/index faces — passed via params=;
   with_payload=true is passed explicitly — its default is false, by-design)
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
# keyed: id -> group value; keyless ids carry no grp payload key at all
KEYED = {1: "a", 2: "a", 3: "b", 4: "b", 5: "c"}
KEYLESS = [6, 7]
EXPECT = {"a": 2, "b": 2, "c": 1}


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
    coll = "bqgsV" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = []
        for pid, gval in KEYED.items():
            pts.append({"id": pid,
                        "vector": [v * (1.0 + pid / 100.0) for v in V],
                        "payload": {GRP: gval}})
        for pid in KEYLESS:
            pts.append({"id": pid,
                        "vector": [v * (1.0 + pid / 100.0) for v in V],
                        "payload": {"other": "no-group-key-here"}})
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

        # ---- P1: 200 envelope with groups[{id, hits}] ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/query/groups",
                                 json={"query": {"nearest": V}, "group_by": GRP,
                                       "limit": 10, "group_size": 10,
                                       "with_payload": True, "params": {"exact": True}},
                                 timeout=60)
        print(f"\nleg P (valid group query) -> status={s}")
        print(f"raw: {raw[:600]}")
        if transport_or_5xx("P valid group query", s, raw):
            return
        groups, shape = extract_groups(b)
        if s in (400, 404, 422):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [P]: the documented "
                  f"valid group query (payload values present) was rejected with {s}: {raw[:300]}")
            return
        if s != 200 or groups is None:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status/envelope {s} ({shape}); no defect conclusion")
            return
        malformed = [i for i, g in enumerate(groups)
                     if not isinstance(g, dict) or "id" not in g or not isinstance(g.get("hits"), list)]
        if malformed:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [P]: contract "
                  f"promises groups entries of {{id, hits}}; malformed entries at "
                  f"indexes {malformed}: {raw[:300]}")
            return
        print(f"leg P1 OK: 200, groups[{len(groups)}] entries carry id+hits (envelope {shape})")

        # ---- P2: exactly the 3 populated groups, no null/extra group id ----
        gids = [g.get("id") for g in groups]
        print(f"observed group ids: {gids}")
        if sorted(map(str, gids)) != ["a", "b", "c"]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [P2]: group ids "
                  f"must be exactly the populated payload values a/b/c (keyless points must "
                  f"not materialize a group), got {gids}: {raw[:300]}")
            return
        print("leg P2 OK: group ids exactly {a, b, c}; no null/extra group")

        # ---- P3 + P4 + P5: cardinality, membership, keyless exclusion ----
        for g in groups:
            gid = g.get("id")
            hits = g.get("hits") or []
            if len(hits) != EXPECT[gid]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [P3]: group "
                      f"'{gid}' has {EXPECT[gid]} keyed points and caps are 10, but "
                      f"{len(hits)} hits returned: {raw[:300]}")
                return
            for h in hits:
                pl = h.get("payload") or {}
                if pl.get(GRP) != gid:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [P4]: hit "
                          f"{h.get('id')} sits in group '{gid}' but its payload grp is "
                          f"{pl.get(GRP)!r} — bucket membership corrupted: {raw[:300]}")
                    return
            leaked = [h.get("id") for h in hits if h.get("id") in KEYLESS]
            if leaked:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [P5]: keyless "
                      f"points {leaked} appear in group '{gid}' — the contract states grouping "
                      f"REQUIRES payload values for the group_by field: {raw[:300]}")
                return
        total = sum(len(g.get("hits") or []) for g in groups)
        print(f"leg P3/P4/P5 OK: cardinalities 2/2/1, membership correct, keyless "
              f"ids {KEYLESS} excluded (total hits = {total} == 5 keyed points)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
