#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_groups_semantics_001
# strategy: strategy5 search-semantic-correctness attack — the MEANING of
#           group_size (max points per group, default 3) and limit (max
#           amount of groups, default 10) measured against a deterministic
#           12-group fixture with exact search
# endpoint: points+query+groups
# constraint_ids: qdrant_range_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift — the spec pins defaults that are
#            rarely exercised: group_size default 3, limit default 10; a
#            drifted default silently changes every client that omits them)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy5 search_correctness x qdrant_range_points_query_groups_001 —
  fixture: 12 groups by payload field grp; g01..g03 have 4 points each at
  fully separable Euclid distances from the query anchor (exact search ON so
  HNSW approximation non-determinism — a documented by-design trait — is
  taken out of play); g04..g12 are singletons ranked 4th..12th. Legs:
    L1 group_size=2, limit=3 -> exactly 3 groups [g01,g02,g03], each with
       exactly its 2 best-by-distance hits ([1101,1102] etc.) — group_size
       = best-points-per-group, limit = best-groups
    L2 group_size=4, limit=3 -> each rich group returns all 4 hits (closure)
    L3 group_size OMITTED, limit=3 -> each group carries exactly 3 hits
       (the 3 best) — documents the DEFAULT group_size=3
    L4 limit OMITTED, group_size=4 -> exactly 10 groups, the 10 best
       (g01..g10; g11,g12 dropped) — documents the DEFAULT limit=10
    L5 membership: with_payload on L2 -> every hit's payload.grp equals its
       group id (no cross-group bleed)
  [chunk_points+query+groups semantic coverage (9 scripts): illegal_rejection
  min-1 closure + 0/-1 rejection x qdrant_range_points_query_groups_001
  (bounds_001); type_coercion string/float/bool group_size+limit x
  qdrant_range_points_query_groups_001 (typecoerce_001); search_correctness
  group_size/limit semantics + defaults x qdrant_range_points_query_groups_001
  (semantics_001); metamorphic offset invariance x
  qdrant_state_points_query_groups_001 (offset_001); metamorphic offset
  disposition cross-face G9 x qdrant_state_points_query_groups_001
  (offset_faces_001); behavioral_contract 200-shape/invalid-group_by-400/404
  x qdrant_behavioral_points_query_groups_001 (behavior_001);
  diagnosis_quality 400/404 message rubric x
  qdrant_behavioral_points_query_groups_001 (diag_001); filter_semantics
  exact-set closure + must_not + range x
  qdrant_behavioral_points_query_groups_001 (filter_001); type_coercion
  R33/R40 dual-key family third face x
  qdrant_behavioral_points_query_groups_001 (dualkey_001)]
Oracle: L1 -> 200, group ids in order [g01,g02,g03], per-group hit id lists
  [[1101,1102],[1201,1202],[1301,1302]]; L2 -> per-group hit lists are the
  full 4-point sets [1101..1104]/[1201..1204]/[1301..1304]; L3 -> per-group
  hit lists [1101,1102,1103]/[1201,1202,1203]/[1301,1302,1303] (default
  group_size=3 — returning 4 hits = default drifted = Type4); L4 -> exactly
  10 groups with set {g01..g10} (default limit=10 — returning 12 = default
  drifted = Type4); L5 -> every hit payload.grp == its group id; any count/
  set/order/membership deviation = Type4_StateLogicViolation; 5xx with
  /healthz alive = Type3_RuntimeFailure; transport failure -> /healthz
  liveness re-check then SCRIPT_ERROR (constraint
  qdrant_range_points_query_groups_001).
Constraint: qdrant_range_points_query_groups_001 — "group_size minimum 1
  (default 3, max points per group); limit minimum 1 (default 10, max amount
  of groups)" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+groups -> POST /collections/{collection_name}/points/query/groups
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  field index create  -> PUT  /collections/{collection_name}/index
  healthz             -> GET  /healthz
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
BASE3 = [10.0, 10.0, 10.0]
ANCHOR = [0.0, 10.0, 10.0, 10.0]

SEED = []
for gi, d0 in ((1, 0.0), (2, 0.5), (3, 1.0)):
    for k in range(4):
        d = d0 + 0.1 * k
        SEED.append({"id": gi * 1000 + 100 + k, "vector": [d] + BASE3,
                     "payload": {"grp": "g%02d" % gi, "val": d}})
for gi in range(4, 13):
    SEED.append({"id": 1400 + gi, "vector": [float(gi)] + BASE3,
                 "payload": {"grp": "g%02d" % gi, "val": float(gi)}})

RICH_ALL = {"g01": [1101, 1102, 1103, 1104],
            "g02": [1201, 1202, 1203, 1204],
            "g03": [1301, 1302, 1303, 1304]}


def safe_request(method, endpoint, json=None, timeout=60, params=None):
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


def healthz_alive():
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def bail_transport(where):
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")


def handle_5xx(rs, rraw, leg):
    if not (500 <= rs <= 599):
        return False
    alive, _, _ = healthz_alive()
    if alive:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{leg}]: {rs} "
              f"with service alive: {rraw[:300]}")
    else:
        print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
    return True


def groups_of(body):
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, dict) and isinstance(r.get("groups"), list):
            return r["groups"]
    return None


def fingerprint(groups, with_payload):
    """[(group id, [hit ids ...], [hit payload grp ...])]"""
    fp = []
    for g in groups or []:
        if not isinstance(g, dict):
            return None
        hits = g.get("hits")
        if not isinstance(hits, list):
            return None
        ids = [h.get("id") for h in hits if isinstance(h, dict)]
        grps = [((h.get("payload") or {}).get("grp") if isinstance(h.get("payload"), dict) else None)
                for h in hits if isinstance(h, dict)]
        fp.append((g.get("id"), ids, grps if with_payload else None))
    return fp


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqgS1" + tag
    qpath = f"/collections/{coll}/points/query/groups"

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": SEED}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        s, _, raw = safe_request("PUT", f"/collections/{coll}/index",
                                 json={"field_name": "grp", "field_schema": "keyword"},
                                 params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"NOTE setup: grp index create returned {s}: {raw[:200]}")

        def run(name, group_size, limit, with_payload=False):
            body = {"query": {"nearest": ANCHOR}, "group_by": "grp",
                    "params": {"exact": True}, "with_payload": with_payload}
            if group_size is not None:
                body["group_size"] = group_size
            if limit is not None:
                body["limit"] = limit
            rs, rbody, rraw = safe_request("POST", qpath, json=body, timeout=60)
            print(f"[{name}] status={rs} raw: {rraw[:500]}")
            if rs == -1:
                bail_transport(name)
                return "BAIL"
            if handle_5xx(rs, rraw, name):
                return "STOP"
            if not (200 <= rs <= 299):
                print(f"VERDICT: SCRIPT_ERROR — {name} unexpected status {rs}; no defect conclusion")
                return "STOP"
            return fingerprint(groups_of(rbody), with_payload)

        # ---- L1: group_size=2, limit=3 ----
        fp = run("L1 group_size=2 limit=3", 2, 3)
        if fp in ("BAIL", "STOP"):
            return
        got = [(g[0], g[1]) for g in fp]
        exp = [("g01", [1101, 1102]), ("g02", [1201, 1202]), ("g03", [1301, 1302])]
        print(f"L1 fingerprint = {got}")
        if got != exp:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L1 expected "
                  f"{exp} (3 best groups, 2 best hits each, ranked), got {got}")
            return

        # ---- L2: group_size=4, limit=3 (closure: all 4 hits per rich group) ----
        fp = run("L2 group_size=4 limit=3", 4, 3, with_payload=True)
        if fp in ("BAIL", "STOP"):
            return
        got = [(g[0], g[1]) for g in fp]
        exp = [("g01", RICH_ALL["g01"]), ("g02", RICH_ALL["g02"]), ("g03", RICH_ALL["g03"])]
        print(f"L2 fingerprint = {got}")
        if got != exp:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L2 expected "
                  f"{exp} (group_size=4 returns each rich group's full point set), got {got}")
            return

        # ---- L5: membership (payload grp == group id on every hit) ----
        for gid, _ids, pgrps in fp:
            if any(p != gid for p in pgrps):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L5 group "
                      f"{gid} contains hits whose payload grp != group id: {pgrps} "
                      f"(cross-group membership bleed)")
                return
        print("L5 membership holds: every hit's payload grp equals its group id")

        # ---- L3: group_size OMITTED -> default 3 ----
        fp = run("L3 group_size omitted (default 3)", None, 3)
        if fp in ("BAIL", "STOP"):
            return
        got = [(g[0], g[1]) for g in fp]
        exp = [("g01", [1101, 1102, 1103]), ("g02", [1201, 1202, 1203]),
               ("g03", [1301, 1302, 1303])]
        print(f"L3 fingerprint = {got}")
        if got != exp:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L3 omitted "
                  f"group_size must default to 3 (spec: 'default 3'): expected {exp}, "
                  f"got {got}")
            return

        # ---- L4: limit OMITTED -> default 10 ----
        fp = run("L4 limit omitted (default 10)", 4, None)
        if fp in ("BAIL", "STOP"):
            return
        got_ids = [g[0] for g in fp]
        print(f"L4 group ids = {got_ids}")
        if got_ids != ["g%02d" % i for i in range(1, 11)]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L4 omitted "
                  f"limit must default to 10 (spec: 'default 10'): expected exactly "
                  f"groups g01..g10 in rank order (12 groups available), got "
                  f"{got_ids} (n={len(got_ids)})")
            return

        print("L1/L2/L3/L4/L5 all match the documented group_size/limit semantics "
              "including both defaults")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
