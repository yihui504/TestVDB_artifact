#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_facet_005
# strategy: upsert_idempotence
# endpoint: facet
# constraint_ids: qdrant_behavioral_facet_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/facet
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (upsert overwrite must move the facet count by exactly one)
"""
Attack: upsert idempotence (Strategy 3) x qdrant_behavioral_facet_001 — the
  facet count of a value is the number of POINTS carrying it; re-upserting
  an identical point must not double-count, and overwriting a point's value
  must move the counts by exactly one on both the losing and the gaining
  value. Data: keyword index on 'city'; seed A:2 (ids 1,2), B:3 (ids 3,4,5).
  (L1 idempotent re-upsert) re-upsert ids 1,2 with identical {A} payloads
    and id 5 with {B} -> facet stays {A:2, B:3} (duplicate writes do not
    inflate counts — count tracks points, not write occurrences).
  (L2 overwrite moves one) upsert id 3 with {B} -> {A} -> facet {A:3, B:2}
    (exactly one point left B and joined A).
  (L3 overwrite to a new value) upsert id 1 with {A} -> {C} -> facet
    {A:2, B:2, C:1} (old value loses the point, new value appears with 1).
  (L4 key-absent point) upsert id 6 with a payload that has NO 'city' key
    -> facet stays {A:2, B:2, C:1} while the exact point count face reads 6
    (a point without the key contributes to no value's count).
  Every leg: exact=true facet readout, wait=true upserts, shape-checked
  result.hits[] envelope; every count transition cross-checked against the
  expected multiset computed from the tracked state.
Oracle: after every leg the facet multiset equals the tracked per-value
  point frequencies (L1 {A:2,B:3}; L2 {A:3,B:2}; L3 {A:2,B:2,C:1}; L4
  {A:2,B:2,C:1} with point count 6) — a stale, inflated, or non-moving
  count = Type4_StateLogicViolation; 5xx with /healthz alive =
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
    PFX = "sf5_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    def upsert(tag, points):
        s, raw = safe_request("PUT", "upsert_points", path_params={"name": C},
                              body={"points": points}, query_params={"wait": "true"})
        print(f"[{tag} upsert] status={s} raw={str(raw)[:150]}")
        if s not in (200, 201):
            print(f"SETUP_ERROR: upsert returned {s}")
            return False
        return True

    def facet_city(tag):
        s, raw = safe_request("POST", "facet",
                              body={"key": "city", "limit": 10, "exact": True},
                              path_params={"collection_name": C})
        print(f"[{tag} facet] status={s} raw={str(raw)[:240]}")
        if s == 0:
            liveness(tag)
            return None
        if 500 <= s <= 599:
            if liveness(tag):
                DEFECTS.append(f"({tag}) facet returned {s} with service alive - "
                               f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
            return None
        if s != 200:
            DEFECTS.append(f"({tag}) facet returned {s} on the indexed key - "
                           f"Type1_IllegalSuccess - raw={str(raw)[:160]}")
            return None
        shape_ok, m, note = parse_facet(raw)
        if not shape_ok:
            DEFECTS.append(f"({tag}) facet 200 but shape violation ({note}) - "
                           f"Type4_StateLogicViolation - raw={str(raw)[:160]}")
            return None
        return m

    def expect_counts(tag, want, point_count=None):
        m = facet_city(tag)
        if m is None:
            return False
        if m != want:
            DEFECTS.append(f"({tag}) facet counts {m} but the tracked point state "
                           f"demands {want} - count readout lies - "
                           f"Type4_StateLogicViolation (qdrant_behavioral_facet_001)")
            return False
        if point_count is not None:
            cs, craw = safe_request("POST", "count", body={"exact": True},
                                    path_params={"name": C})
            print(f"[{tag} count-face] status={cs} raw={str(craw)[:180]}")
            if cs != 200:
                return False
            cnt, note = parse_count(craw)
            if cnt != point_count:
                DEFECTS.append(f"({tag}) exact point count face reads {cnt}, expected "
                               f"{point_count} - Type4_StateLogicViolation")
                return False
        print(f"[{tag}] OK: counts {want}")
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
        print(f"[setup index] status={s} raw={str(raw)[:150]}")
        if s != 200:
            print(f"SETUP_ERROR: create_index returned {s}")
            return "SCRIPT_ERROR"

        # seed: A:2 (ids 1,2), B:3 (ids 3,4,5)
        if not upsert("seed", [
                {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"city": "A"}},
                {"id": 2, "vector": [0.2, 0.3, 0.4, 0.5], "payload": {"city": "A"}},
                {"id": 3, "vector": [0.3, 0.4, 0.5, 0.6], "payload": {"city": "B"}},
                {"id": 4, "vector": [0.4, 0.5, 0.6, 0.7], "payload": {"city": "B"}},
                {"id": 5, "vector": [0.5, 0.6, 0.7, 0.8], "payload": {"city": "B"}}]):
            return "SCRIPT_ERROR"
        if not expect_counts("seed", {"A": 2, "B": 3}, point_count=5):
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"

        # ---- (L1) identical re-upsert: counts must NOT inflate ----
        if not upsert("L1", [
                {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"city": "A"}},
                {"id": 2, "vector": [0.2, 0.3, 0.4, 0.5], "payload": {"city": "A"}},
                {"id": 5, "vector": [0.5, 0.6, 0.7, 0.8], "payload": {"city": "B"}}]):
            return "SCRIPT_ERROR"
        if not expect_counts("L1 idempotent", {"A": 2, "B": 3}, point_count=5):
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"

        # ---- (L2) value overwrite: id 3 moves B -> A ----
        if not upsert("L2", [
                {"id": 3, "vector": [0.3, 0.4, 0.5, 0.6], "payload": {"city": "A"}}]):
            return "SCRIPT_ERROR"
        if not expect_counts("L2 overwrite", {"A": 3, "B": 2}, point_count=5):
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"

        # ---- (L3) overwrite into a brand-new value: id 1 moves A -> C ----
        if not upsert("L3", [
                {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"city": "C"}}]):
            return "SCRIPT_ERROR"
        if not expect_counts("L3 new-value", {"A": 2, "B": 2, "C": 1}, point_count=5):
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"

        # ---- (L4) key-absent point: id 6 without 'city' changes nothing ----
        if not upsert("L4", [
                {"id": 6, "vector": [0.6, 0.7, 0.8, 0.9], "payload": {"other": "x"}}]):
            return "SCRIPT_ERROR"
        if not expect_counts("L4 key-absent", {"A": 2, "B": 2, "C": 1}, point_count=6):
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"

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
