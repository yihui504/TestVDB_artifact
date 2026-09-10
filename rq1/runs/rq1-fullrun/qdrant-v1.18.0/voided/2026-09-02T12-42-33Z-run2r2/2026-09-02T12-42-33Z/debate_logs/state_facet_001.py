#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_facet_001
# strategy: index_state
# endpoint: facet
# constraint_ids: qdrant_state_facet_001
# source_url: https://qdrant.tech/documentation/manage-data/payload/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-03 (state of the payload-index resource vs the facet readout face)
"""
Attack: index_state x qdrant_state_facet_001 — the facet readout must be
  gated PER KEY by the presence of a MatchValue-capable (keyword) payload
  index on that key: 'facet on a field without a suitable (keyword-like)
  payload index is rejected with 400'. State lifecycle over two keyword
  payload keys k_city / k_region on one collection:
  (A negative) facet k_city BEFORE any index exists -> 400 (assertion);
    200 here would be Type1_IllegalSuccess (the gating promise broken).
  (B positive)  create keyword index on k_city -> facet k_city -> 200 with
    value/count hits (positive leg proves the promise's existence).
  (C per-key gate) k_region still carries keyword payloads but is NOT
    indexed -> facet k_region -> 400 even though the collection itself is
    now 'index-capable' (gating is key-scoped, not collection-scoped).
  (D closure) index k_region -> facet k_region -> 200.
  (E index-drop transition) delete the k_city index -> facet k_city -> 400
    again (availability must follow the index resource state in both
    directions; a facet that keeps returning 200 after its backing index
    was dropped = stale-state Type4/Type1 per the assertion).
  (F) facet on k_city values with index re-created -> 200 (restore).
  Wait=true is used on every index create/delete and on upserts so the
  index state transition is quiescent before each facet probe.
  [chunk_facet coverage: index_state x qdrant_state_facet_001 (no-index 400
   / keyword-index 200 / per-key gating / index-drop reversion / restore)]
Oracle: facet on an UNINDEXED keyword key returns 400 at every lifecycle
  point (before any index, and again after its index is deleted); facet on
  an indexed keyword key returns 200 with hits; any 200-on-unindexed-key =
  Type1_IllegalSuccess, any 400-on-indexed-key = Type1_IllegalSuccess
  (rejection of legal input), 5xx with /healthz alive = Type3_RuntimeFailure
  (qdrant_state_facet_001)
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

# facet is not yet in the runtime PATHS whitelist (verified against
# sorted(rt.PATHS.keys()) at import); register its URL VERBATIM from
# raw_knowledge.json api_endpoints[].url:
#   {"path": "facet", "method": "POST",
#    "url": "/collections/{collection_name}/facet"}
rt.PATHS["facet"] = "/collections/{collection_name}/facet"
_avail = sorted(rt.PATHS.keys())
print(f"[PATHS] registered facet; total keys={len(_avail)}; "
      f"facet present={_avail.count('facet')}")
if rt.PATHS.get("facet") != "/collections/{collection_name}/facet":
    print("VERDICT: SCRIPT_ERROR - facet URL registration failed")
    sys.exit(2)


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_facet_hits(raw):
    """Materialized response_shape of POST facet pins the envelope
    result: object -> result.hits[] with value(any)/count(integer).
    Returns (shape_ok, hits_list_or_None, note)."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return False, None, "non-JSON body"
    if not isinstance(b, dict):
        return False, None, "body not an object"
    res = b.get("result")
    if not isinstance(res, dict):
        return False, None, "result missing or not an object"
    hits = res.get("hits")
    if not isinstance(hits, list):
        return False, None, "result.hits missing or not an array"
    for h in hits:
        if not isinstance(h, dict) or "value" not in h or "count" not in h:
            return False, None, f"hit entry malformed: {str(h)[:120]}"
        if not isinstance(h.get("count"), int):
            return False, None, f"hit count not an integer: {str(h)[:120]}"
    return True, hits, ""


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sf1_" + TS + "_"
    C = PFX + "col"
    K_CITY = "city"
    K_REGION = "region"
    DEFECTS = []
    results = []

    # 12 points: every point carries BOTH city and region keyword payloads
    pts = [
        {"id": i, "vector": [0.1 * i, 0.2, 0.3, 0.4],
         "payload": {"city": f"c{i % 4}", "region": f"r{i % 3}"}}
        for i in range(1, 13)
    ]

    def probe_facet(tag, key, expect_status):
        """One facet probe. expect_status: 200 or 400.
        Records a typed defect when the observed status contradicts the
        per-key index-state expectation. Returns True=ok / False=defect /
        None=abort (transport or 5xx)."""
        s, raw = safe_request("POST", "facet",
                              body={"key": key, "limit": 10},
                              path_params={"collection_name": C})
        print(f"[{tag}] facet key={key} status={s} raw={str(raw)[:220]}")
        if s == 0:
            liveness(tag)
            return None
        if 500 <= s <= 599:
            if liveness(tag):
                DEFECTS.append(f"({tag}) facet returned {s} with service alive - "
                               f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
                return False
            return None
        if s == 400 and expect_status == 400:
            print(f"[{tag}] OK: 400 as asserted (no suitable index on key {key})")
            return True
        if s == 200 and expect_status == 200:
            shape_ok, hits, note = parse_facet_hits(raw)
            if not shape_ok:
                DEFECTS.append(f"({tag}) facet 200 but response violates the pinned "
                               f"shape result.hits[].value/.count ({note}) - "
                               f"Type4_StateLogicViolation - raw={str(raw)[:160]}")
                return False
            if len(hits) == 0:
                DEFECTS.append(f"({tag}) facet 200 on indexed key {key} returned an "
                               f"empty hits list although 12 points carry the key - "
                               f"Type4_StateLogicViolation")
                return False
            print(f"[{tag}] OK: 200 with {len(hits)} hits on indexed key {key}")
            return True
        # expectation/observation contradiction
        DEFECTS.append(
            f"({tag}) facet on key {key} returned {s} but the key's index state "
            f"(expect_status={expect_status}) demands "
            f"{'400 (unindexed key must be rejected)' if expect_status == 400 else '200 (indexed key must facet)'} "
            f"- Type1_IllegalSuccess - raw={str(raw)[:160]} "
            f"(qdrant_state_facet_001)")
        return False

    try:
        # ---- setup: create collection (setup gate) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: create {C} failed: {err[:200]}")
            return "SCRIPT_ERROR"

        s, raw = safe_request("PUT", "upsert_points", path_params={"name": C},
                              body={"points": pts}, query_params={"wait": "true"})
        print(f"[setup upsert] status={s} raw={str(raw)[:150]}")
        if s not in (200, 201):
            print("SETUP_ERROR: upsert failed - cannot judge facet gating")
            return "SCRIPT_ERROR"

        # ---- (A) no index anywhere -> facet must 400 ----
        r = probe_facet("A no-index", K_CITY, 400)
        if r is None:
            return "SCRIPT_ERROR"
        results.append(r)

        # ---- (B) keyword index on city -> facet city 200 ----
        s, raw = safe_request("PUT", "create_index", path_params={"name": C},
                              body={"field_name": K_CITY,
                                    "field_schema": {"type": "keyword"}},
                              query_params={"wait": "true"})
        print(f"[B index city] status={s} raw={str(raw)[:150]}")
        if s != 200:
            print(f"SETUP_ERROR: create_index returned {s} - cannot judge facet gating")
            return "SCRIPT_ERROR"
        r = probe_facet("B indexed-city", K_CITY, 200)
        if r is None:
            return "SCRIPT_ERROR"
        results.append(r)

        # ---- (C) region still unindexed (but carries keyword payloads) -> 400 ----
        r = probe_facet("C unindexed-region", K_REGION, 400)
        if r is None:
            return "SCRIPT_ERROR"
        results.append(r)

        # ---- (D) index region too -> facet region 200 ----
        s, raw = safe_request("PUT", "create_index", path_params={"name": C},
                              body={"field_name": K_REGION,
                                    "field_schema": {"type": "keyword"}},
                              query_params={"wait": "true"})
        print(f"[D index region] status={s} raw={str(raw)[:150]}")
        if s != 200:
            print(f"SETUP_ERROR: create_index(region) returned {s}")
            return "SCRIPT_ERROR"
        r = probe_facet("D indexed-region", K_REGION, 200)
        if r is None:
            return "SCRIPT_ERROR"
        results.append(r)

        # ---- (E) drop the city index -> facet city must revert to 400 ----
        s, raw = safe_request("DELETE", "delete_index", path_params={"name": C,
                                                                     "field_name": K_CITY},
                              query_params={"wait": "true"})
        print(f"[E delete index city] status={s} raw={str(raw)[:150]}")
        if s != 200:
            print(f"SETUP_ERROR: delete_index returned {s}")
            return "SCRIPT_ERROR"
        r = probe_facet("E after-index-drop", K_CITY, 400)
        if r is None:
            return "SCRIPT_ERROR"
        results.append(r)

        # ---- (F) re-create city index -> facet city 200 again (restore) ----
        s, raw = safe_request("PUT", "create_index", path_params={"name": C},
                              body={"field_name": K_CITY,
                                    "field_schema": {"type": "keyword"}},
                              query_params={"wait": "true"})
        print(f"[F re-index city] status={s} raw={str(raw)[:150]}")
        if s != 200:
            print(f"SETUP_ERROR: re-create_index returned {s}")
            return "SCRIPT_ERROR"
        r = probe_facet("F restored-city", K_CITY, 200)
        if r is None:
            return "SCRIPT_ERROR"
        results.append(r)

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
