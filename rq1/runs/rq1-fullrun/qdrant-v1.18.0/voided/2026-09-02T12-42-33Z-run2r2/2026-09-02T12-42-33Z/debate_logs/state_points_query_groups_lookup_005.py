#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_groups_lookup_005
# strategy: state_consistency (broken cross-collection dependency, Pattern C)
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: with_lookup dependency chain x
  qdrant_behavioral_points_query_groups_001 (200 {groups:[{id,hits}]})
  via Pattern C (broken dependency chain). The groups query supports
  with_lookup enrichment from a SECOND collection (contract parameter
  with_lookup: WithLookup "lookup into another collection"; response
  shape declares result.groups[].lookup). Group values are fixed UUIDs so
  they can equal point ids in the lookup collection (qdrant point ids
  must be uint or UUID). Positive face: enrichment present on every
  group. Attack: DROP the lookup collection, re-issue the IDENTICAL
  groups query — the correct disposition is a graceful 4xx naming the
  missing dependency; a 500 is Type3; a 200 is defective in either of
  its two forms: enrichment silently vanished (silent dependency loss —
  the 200 no longer reflects the request) or enrichment still present
  (phantom read from a dropped collection). Restore leg (Pattern A):
  recreate the lookup collection with the same ids — the identical query
  must return the same enrichment as the positive face (recovery
  consistency).
  [chunk_points+query+groups coverage: state_consistency x
  qdrant_behavioral_points_query_groups_001 (with_lookup broken-chain:
  drop lookup -> graceful 4xx expected; silent-loss / phantom-read 200 =
  Type4; 500 = Type3; restore round-trip)]
Oracle: positive face -> 200 with result.groups[].lookup populated on
  all 4 groups (absent everywhere = WARN, comparison leg skipped); after
  dropping the lookup collection the identical query -> 404/400 (graceful
  dependency error); 500 with /healthz alive = Type3_RuntimeFailure; 200
  with lookup gone on groups that had it = Type4 silent dependency loss;
  200 with lookup still populated = Type4 phantom read; after restore the
  enrichment set == positive face (mismatch = Type4).
"""

import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p / "scripts")
            break
if not _sd or not Path(_sd, "runtime", "__init__.py").exists():
    print("VERDICT: SCRIPT_ERROR - runtime scripts dir not found (TESTVDB_SCRIPTS_DIR unset)")
    sys.exit(2)
sys.path.insert(0, _sd)

if not os.environ.get("TESTVDB_TARGET"):
    for _p in Path(__file__).resolve().parents:
        _c = _p / "structured_contract.json"
        if _c.exists():
            try:
                _t = json.loads(_c.read_text(encoding="utf-8")).get("target", "")
                if _t:
                    os.environ["TESTVDB_TARGET"] = str(_t).lower()
            except Exception:
                pass
            break

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('query_groups', 'upsert_points', 'count', 'create_index', 'drop_collection', 'healthz')]}")

DEFECTS = []
WARNINGS = []
ABORT = [False]

UUIDS = ["11111111-1111-1111-1111-111111111111",
         "22222222-2222-2222-2222-222222222222",
         "33333333-3333-3333-3333-333333333333",
         "44444444-4444-4444-4444-444444444444"]


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def handle_transport(tag, status, raw):
    if status == 0:
        if not liveness(tag):
            ABORT[0] = True
            return True
        WARNINGS.append(f"({tag}) transport failure {str(raw)[:100]} but /healthz alive")
        return False
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {status} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
            return True
    return False


def groups_body(lookup_coll):
    return {"query": [1.0, 1.0, 1.0, 1.0], "group_by": "grp",
            "limit": 10, "group_size": 3, "params": {"exact": True},
            "with_lookup": {"collection": lookup_coll}}


def parse_face(status, raw, tag):
    """Return (groups list) on 200 with structure defects recorded; else None."""
    try:
        body = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        body = None
    if not isinstance(body, dict):
        if status == 200:
            DEFECTS.append(f"({tag}) 200 with unparseable body — "
                           f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return None
    res = body.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("groups"), list):
        if status == 200:
            DEFECTS.append(f"({tag}) 200 but result.groups missing/not array — "
                           f"result-completeness violation (R40 lesson) — "
                           f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return None
    return res["groups"]


def enrichment_map(groups):
    """{group_id: lookup-present?} — lookup key present and non-null."""
    emap = {}
    for g in groups:
        if not isinstance(g, dict):
            continue
        lk = g.get("lookup", None)
        emap[str(g.get("id"))] = bool(lk is not None and lk != {} and lk != [])
    return emap


def seed_lookup(coll):
    ok, err = rt.setup_default(coll, 4, "Cosine")
    if not ok:
        return False
    pts = [{"id": u, "vector": [float(i + 1), 1.0, 0.5, 0.25],
            "payload": {"name": f"lookup-{i}"}}
           for i, u in enumerate(UUIDS)]
    s, raw = safe_request("PUT", "upsert_points", path_params={"name": coll},
                          body={"points": pts}, query_params={"wait": "true"})
    print(f"[lookup seed] status={s} raw={str(raw)[:140]}")
    return s in (200, 201)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spqg5_" + TS + "_"
    M = PFX + "main"       # grouped collection
    L = PFX + "lookup"     # lookup collection (ids == group values)

    try:
        if not seed_lookup(L):
            print("SETUP_ERROR: lookup collection seed failed")
            return "SCRIPT_ERROR"
        ok, err = rt.setup_default(M, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: main setup failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": (i + 1) * 10 + j, "vector": [float(j), 1.0, float(i + 1), 0.5],
                "payload": {"grp": u}}
               for i, u in enumerate(UUIDS) for j in (1, 2, 3)]
        s_up, raw_up = safe_request("PUT", "upsert_points", path_params={"name": M},
                                    body={"points": pts},
                                    query_params={"wait": "true"})
        print(f"[main seed] status={s_up}")
        if s_up not in (200, 201):
            return "SCRIPT_ERROR"
        s_ix, _ = safe_request("PUT", "create_index", path_params={"name": M},
                               body={"field_name": "grp", "field_schema": "keyword"},
                               query_params={"wait": "true"})
        if s_ix not in (200, 201):
            return "SCRIPT_ERROR"

        # ---- positive face: enrichment present ----
        s1, r1 = safe_request("POST", "query_groups", path_params={"name": M},
                              body=groups_body(L))
        print(f"[positive] status={s1} raw={str(r1)[:300]}")
        if handle_transport("positive", s1, r1):
            return verdict()
        if s1 != 200:
            print(f"SETUP_ERROR: positive with_lookup query returned {s1}")
            return "SCRIPT_ERROR"
        gs1 = parse_face(s1, r1, "positive")
        if gs1 is None:
            return verdict()
        enriched1 = enrichment_map(gs1)
        n_groups = len(gs1)
        n_enriched = sum(1 for v in enriched1.values() if v)
        print(f"[positive] groups={n_groups} enriched={n_enriched} map={enriched1}")
        baseline_ok = (n_groups == len(UUIDS) and n_enriched == len(UUIDS))
        if not baseline_ok:
            WARNINGS.append(f"(positive) with_lookup enrichment incomplete on "
                            f"the positive face ({n_enriched}/{n_groups}) — "
                            f"comparison legs adjudicated on disposition only")

        # ---- attack: drop the lookup collection ----
        s_del, r_del = safe_request("DELETE", "drop_collection",
                                    path_params={"name": L})
        print(f"[drop lookup] status={s_del} raw={str(r_del)[:140]}")
        if s_del not in (200, 201, 404):
            handle_transport("drop-lookup", s_del, r_del)
            print("SETUP_ERROR: drop lookup failed")
            return "SCRIPT_ERROR"

        s2, r2 = safe_request("POST", "query_groups", path_params={"name": M},
                              body=groups_body(L))
        print(f"[broken-chain] status={s2} raw={str(r2)[:300]}")
        if handle_transport("broken-chain", s2, r2):
            return verdict()
        if s2 in (404, 400, 422):
            print(f"[broken-chain] OK: graceful {s2} naming the missing dependency")
        elif s2 == 200:
            gs2 = parse_face(s2, r2, "broken-chain")
            if gs2 is not None:
                enriched2 = enrichment_map(gs2)
                print(f"[broken-chain] 200 map={enriched2}")
                still = sum(1 for v in enriched2.values() if v)
                if still > 0:
                    DEFECTS.append(f"(broken-chain) 200 with lookup enrichment "
                                   f"still present on {still} groups after the "
                                   f"lookup collection was DROPPED — phantom read "
                                   f"of a deleted collection — "
                                   f"Type4_StateLogicViolation")
                elif baseline_ok:
                    DEFECTS.append(f"(broken-chain) 200 with enrichment silently "
                                   f"vanished (positive face had {n_enriched}/{n_groups}, "
                                   f"now 0) — silent dependency loss: the 200 no "
                                   f"longer reflects the with_lookup request — "
                                   f"Type4_StateLogicViolation")
                else:
                    WARNINGS.append("(broken-chain) 200 without enrichment, but "
                                    "positive face was not fully enriched either "
                                    "— not adjudicable, recorded")
        elif 400 <= s2 <= 499:
            WARNINGS.append(f"(broken-chain) status {s2} — raw={str(r2)[:120]}")

        # ---- restore leg: recreate lookup, enrichment must return ----
        if seed_lookup(L):
            time.sleep(0.5)
            s3, r3 = safe_request("POST", "query_groups", path_params={"name": M},
                                  body=groups_body(L))
            print(f"[restore] status={s3} raw={str(r3)[:300]}")
            if handle_transport("restore", s3, r3):
                return verdict()
            if s3 == 200:
                gs3 = parse_face(s3, r3, "restore")
                if gs3 is not None and baseline_ok:
                    enriched3 = enrichment_map(gs3)
                    if enriched3 != enriched1:
                        DEFECTS.append(f"(restore) after recreating the lookup "
                                       f"collection the enrichment map differs "
                                       f"from the positive face {enriched1} -> "
                                       f"{enriched3} — recovery inconsistency — "
                                       f"Type4_StateLogicViolation")
                    else:
                        print("[restore] OK: enrichment identical to positive face")
        else:
            WARNINGS.append("(restore) lookup reseed failed — restore leg skipped")

        return verdict()
    finally:
        for _c in (M, L):
            try:
                rt.drop_collection(_c)
            except Exception:
                pass


def verdict():
    for w in WARNINGS:
        print(f"WARN: {w}")
    if DEFECTS:
        for d in DEFECTS:
            print(f"DEFECT: {d}")
        return "DEFECT_FOUND"
    if ABORT[0]:
        print("ABORT: environment/transport unavailable mid-run")
        return "SCRIPT_ERROR"
    return "NO_DEFECT"


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
