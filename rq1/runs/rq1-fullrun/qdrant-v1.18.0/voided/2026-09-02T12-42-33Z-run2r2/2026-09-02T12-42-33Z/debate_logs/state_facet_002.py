#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_facet_002
# strategy: count_consistency
# endpoint: facet
# constraint_ids: qdrant_behavioral_facet_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/facet
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-09 (facet count readout vs the point-count face must not drift)
"""
Attack: CRUD-then-COUNT consistency (Strategy 1) x qdrant_behavioral_facet_001
  — facet on an indexed key returns 200 with value/count hits whose counts
  are the true payload-value frequencies, tracked across the point CRUD
  lifecycle and cross-checked against a second state face (POST points/count
  exact=true). Data: 300 points over one keyword-indexed key 'city'
  (A:150, B:100, C:50) and a second keyword field 'region' (EU:200, AP:100,
  matched 1:1 with city: A->120 EU/30 AP, B->80 EU/20 AP, C->0 EU/50 AP).
  Legs (all facets exact=true, wait=true on writes so every readout is
  quiescent):
  (A positive shape+counts) facet city limit=10 -> 200; hits multiset
    exactly {A:150, B:100, C:50}; every hit has value+integer count
    (result.hits[] envelope per materialized response_shape).
  (B cross-face) sum(facet city counts) == POST count(exact, no filter)
    == 300 (both faces of the same state agree).
  (C filter scope) facet city with filter region=EU -> 200 hits
    {A:120, B:80} (C absent: its region is AP) and sum ==
    count(exact, region=EU) == 200.
  (D upsert transition) upsert 25 more A/EU points -> facet city ->
    A:175, B:100, C:50 (CRUD write must move the readout).
  (E delete transition) delete_points filter city=C (wait) -> facet city
    -> {A:175, B:100} exactly: C must VANISH (a stale {C:50} entry, a
    resurrected C after delete, or a wrong count = count-lie).
  (F 404 clause) facet on a never-created unique collection -> 404 (the
    assertion's missing-collection branch; any other status = violation).
Oracle: facet counts equal the seeded/CRUD-tracking frequencies at every leg
  (A:{A:150,B:100,C:50}; C:{A:120,B:80}; D:{A:175,B:100,C:50};
  E:{A:175,B:100} with C absent), each facet-sum equals the exact point
  count face over the same scope, and facet on a missing collection is 404;
  a mismatch = Type4_StateLogicViolation, 5xx with /healthz alive =
  Type3_RuntimeFailure (qdrant_behavioral_facet_001)
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

# facet is not yet in the runtime PATHS whitelist; register its URL VERBATIM
# from raw_knowledge.json api_endpoints[].url:
#   {"path": "facet", "method": "POST",
#    "url": "/collections/{collection_name}/facet"}
rt.PATHS["facet"] = "/collections/{collection_name}/facet"
if rt.PATHS.get("facet") != "/collections/{collection_name}/facet":
    print("VERDICT: SCRIPT_ERROR - facet URL registration failed")
    sys.exit(2)


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_facet(raw):
    """(shape_ok, {value: count} dict or None, note) per the materialized
    response_shape result.hits[].value/.count."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return False, None, "non-JSON body"
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        return False, None, "result missing or not an object"
    hits = res.get("hits")
    if not isinstance(hits, list):
        return False, None, "result.hits missing or not an array"
    out = {}
    for h in hits:
        if not isinstance(h, dict) or "value" not in h or not isinstance(h.get("count"), int):
            return False, None, f"malformed hit: {str(h)[:120]}"
        out[h["value"]] = h["count"]
    return True, out, ""


def parse_count(raw):
    """result.count integer from the points/count face."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None, "non-JSON body"
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict) or not isinstance(res.get("count"), int):
        return None, "result.count missing or not an integer"
    return res["count"], ""


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sf2_" + TS + "_"
    C = PFX + "col"
    NEVER = PFX + "never_created"
    DEFECTS = []

    # 300 points; city A:150 (120 EU + 30 AP), B:100 (80 EU + 20 AP),
    # C:50 (50 AP); region EU:200, AP:100
    pts = []
    pid = 0
    for city, eu, ap in (("A", 120, 30), ("B", 80, 20), ("C", 0, 50)):
        for _ in range(eu):
            pid += 1
            pts.append({"id": pid, "vector": [0.1, 0.2, 0.3, 0.4],
                        "payload": {"city": city, "region": "EU"}})
        for _ in range(ap):
            pid += 1
            pts.append({"id": pid, "vector": [0.2, 0.3, 0.4, 0.5],
                        "payload": {"city": city, "region": "AP"}})
    assert len(pts) == 300, len(pts)

    def facet_city(tag, filter_region=None, limit=10):
        body = {"key": "city", "limit": limit, "exact": True}
        if filter_region is not None:
            body["filter"] = {"must": [{"key": "region", "match": {"value": filter_region}}]}
        s, raw = safe_request("POST", "facet", body=body,
                              path_params={"collection_name": C})
        print(f"[{tag}] facet status={s} raw={str(raw)[:260]}")
        if s == 0:
            liveness(tag)
            return None
        if 500 <= s <= 599:
            if liveness(tag):
                DEFECTS.append(f"({tag}) facet returned {s} with service alive - "
                               f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
                return None
            return None
        if s != 200:
            DEFECTS.append(f"({tag}) facet on indexed key returned {s} (assertion "
                           f"pins 200 with hits) - Type1_IllegalSuccess - "
                           f"raw={str(raw)[:160]}")
            return None
        shape_ok, m, note = parse_facet(raw)
        if not shape_ok:
            DEFECTS.append(f"({tag}) facet 200 but shape violation ({note}) - "
                           f"Type4_StateLogicViolation - raw={str(raw)[:160]}")
            return None
        return m

    def expect_counts(tag, want, filter_region=None):
        m = facet_city(tag, filter_region=filter_region)
        if m is None:
            return False
        if m != want:
            DEFECTS.append(f"({tag}) facet counts {m} but the tracked state demands "
                           f"{want} - count readout lies about point state - "
                           f"Type4_StateLogicViolation (qdrant_behavioral_facet_001)")
            return False
        total = sum(m.values())
        # cross-face: exact point count over the same scope must equal the
        # facet sum (every point carries 'city', so the sum covers all points)
        cbody = {"exact": True}
        if filter_region is not None:
            cbody["filter"] = {"must": [{"key": "region", "match": {"value": filter_region}}]}
        cs, craw = safe_request("POST", "count", body=cbody,
                                path_params={"name": C})
        print(f"[{tag} cross-face count] status={cs} raw={str(craw)[:200]}")
        if cs == 0 or 500 <= cs <= 599:
            liveness(tag + "-count")
            return False
        cnt, cnote = parse_count(craw) if cs == 200 else (None, f"status {cs}")
        if cnt is None:
            DEFECTS.append(f"({tag}) count face unusable ({cnote}) - cannot cross-check")
            return False
        if cnt != total:
            DEFECTS.append(f"({tag}) facet sum {total} disagrees with the exact point "
                           f"count face {cnt} over the same scope - the two state "
                           f"faces drifted - Type4_StateLogicViolation")
            return False
        print(f"[{tag}] OK: counts {want} and facet-sum {total} == count face {cnt}")
        return True

    try:
        # ---- setup ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: create failed: {err[:200]}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "create_index", path_params={"name": C},
                              body={"field_name": "city",
                                    "field_schema": {"type": "keyword"}},
                              query_params={"wait": "true"})
        print(f"[setup index city] status={s} raw={str(raw)[:150]}")
        if s != 200:
            print(f"SETUP_ERROR: create_index returned {s}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "create_index", path_params={"name": C},
                              body={"field_name": "region",
                                    "field_schema": {"type": "keyword"}},
                              query_params={"wait": "true"})
        print(f"[setup index region] status={s} raw={str(raw)[:150]}")
        if s != 200:
            print(f"SETUP_ERROR: create_index(region) returned {s}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points", path_params={"name": C},
                              body={"points": pts}, query_params={"wait": "true"})
        print(f"[setup upsert] status={s} raw={str(raw)[:150]}")
        if s not in (200, 201):
            print("SETUP_ERROR: upsert failed - cannot judge facet counts")
            return "SCRIPT_ERROR"

        # ---- (A) full-scope counts ----
        if not expect_counts("A seeded", {"A": 150, "B": 100, "C": 50}):
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        # ---- (C) filter-scoped counts ----
        if not expect_counts("C region=EU", {"A": 120, "B": 80}, filter_region="EU"):
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        if not expect_counts("C2 region=AP", {"A": 30, "B": 20, "C": 50},
                             filter_region="AP"):
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"

        # ---- (D) upsert 25 more A/EU points (ids 301..325) ----
        extra = [{"id": 300 + i, "vector": [0.3, 0.4, 0.5, 0.6],
                  "payload": {"city": "A", "region": "EU"}} for i in range(1, 26)]
        s, raw = safe_request("PUT", "upsert_points", path_params={"name": C},
                              body={"points": extra}, query_params={"wait": "true"})
        print(f"[D upsert 25x A/EU] status={s} raw={str(raw)[:150]}")
        if s not in (200, 201):
            print("SETUP_ERROR: D upsert failed")
            return "SCRIPT_ERROR"
        if not expect_counts("D after-upsert", {"A": 175, "B": 100, "C": 50}):
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"

        # ---- (E) delete all C points by filter ----
        s, raw = safe_request("POST", "delete_points", path_params={"name": C},
                              body={"filter": {"must": [{"key": "city",
                                                         "match": {"value": "C"}}]}},
                              query_params={"wait": "true"})
        print(f"[E delete city=C] status={s} raw={str(raw)[:150]}")
        if s != 200:
            print(f"SETUP_ERROR: delete returned {s}")
            return "SCRIPT_ERROR"
        if not expect_counts("E after-delete", {"A": 175, "B": 100}):
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"

        # ---- (F) missing collection -> 404 ----
        s, raw = safe_request("POST", "facet", body={"key": "city", "limit": 10},
                              path_params={"collection_name": NEVER})
        print(f"[F missing-collection] status={s} raw={str(raw)[:200]}")
        if s == 0 or 500 <= s <= 599:
            liveness("F")
            return "SCRIPT_ERROR"
        if s != 404:
            DEFECTS.append(f"(F) facet on a never-created collection returned {s} "
                           f"(assertion pins 404) - Type4_StateLogicViolation - "
                           f"raw={str(raw)[:160]}")
            return "DEFECT_FOUND"

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
