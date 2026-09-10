#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_facet_003
# strategy: count_consistency
# endpoint: facet
# constraint_ids: qdrant_range_facet_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/facet
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (limit truncation must never re-aggregate the counts)
"""
Attack: count_consistency x qdrant_range_facet_001 — 'limit minimum 1
  (default 10); the v-1-18-x spec documents no maximum'. The range face is
  probed through the state readout it must leave invariant: limit only
  truncates the hits LIST, it must never change the counts of the values
  that do come back (truncation, not re-aggregation). Seed: keyword index
  on 'tier', values v1..v25 with strictly distinct frequencies 25..1
  (325 points; no ties anywhere, so every top-K is deterministic).
  (A default closure) facet WITHOUT limit -> 200 with exactly the top-10
    multiset {v1:25, v2:24, ..., v10:16} (default 10 per the assertion).
  (B min closure) facet limit=1 -> 200, exactly 1 hit, and that hit is
    v1 with count 25 (the global max; top-1 of a strictly-ordered seed).
  (C invariance across limits) the count of every value present under
    limit=5 must equal its count under limit=25 — limit truncates the list
    but must not re-scale/denormalize/alter the counts.
  (D above-cardinality legal) facet limit=25 and limit=50 -> both return
    all 25 values with unchanged counts (values above the limit are legal;
    no error, no crash).
  (E below-min rejection) facet limit=0 and limit=-1 -> 400 (assertion:
    minimum 1; acceptance here = Type1_IllegalSuccess — a silent
    '0 means default' or 'negative clamped' would violate the range).
Oracle: omitted limit -> 200 with exactly the top-10 multiset
  {v1:25..v10:16}; limit=1 -> 200 with the single hit v1:25; per-value
  counts identical between limit=5 and limit=25 readouts; limit 25/50 ->
  200 with all 25 values; limit 0/-1 -> 400. Deviations = Type4 for
  count drift / Type1 for a below-min limit accepted as 200; 5xx with
  /healthz alive = Type3_RuntimeFailure (qdrant_range_facet_001)
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
    """(shape_ok, [{value, count}], note) per materialized response_shape
    result.hits[].value/.count."""
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
    for h in hits:
        if not isinstance(h, dict) or "value" not in h or not isinstance(h.get("count"), int):
            return False, None, f"malformed hit: {str(h)[:120]}"
    return True, list(hits), ""


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sf3_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    WANT_TOP10 = {f"v{i}": 26 - i for i in range(1, 11)}   # v1:25 .. v10:16
    WANT_ALL25 = {f"v{i}": 26 - i for i in range(1, 26)}   # v1:25 .. v25:1

    # 325 points: value v_i (i=1..25) carried by (26-i) points
    pts = []
    pid = 0
    for i in range(1, 26):
        for _ in range(26 - i):
            pid += 1
            pts.append({"id": pid, "vector": [0.1 * i, 0.2, 0.3, 0.4],
                        "payload": {"tier": f"v{i}"}})
    assert len(pts) == 325, len(pts)

    def facet_limit(tag, limit=None):
        body = {"key": "tier", "exact": True}
        if limit is not None:
            body["limit"] = limit
        s, raw = safe_request("POST", "facet", body=body,
                              path_params={"collection_name": C})
        print(f"[{tag}] facet limit={limit} status={s} raw={str(raw)[:260]}")
        if s == 0:
            liveness(tag)
            return None
        if 500 <= s <= 599:
            if liveness(tag):
                DEFECTS.append(f"({tag}) facet returned {s} with service alive - "
                               f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
            return None
        if s != 200:
            DEFECTS.append(f"({tag}) facet limit={limit} on indexed key returned {s} "
                           f"(limit {limit} is spec-legal) - Type1_IllegalSuccess - "
                           f"raw={str(raw)[:160]}")
            return None
        shape_ok, hits, note = parse_facet(raw)
        if not shape_ok:
            DEFECTS.append(f"({tag}) facet 200 but shape violation ({note}) - "
                           f"Type4_StateLogicViolation - raw={str(raw)[:160]}")
            return None
        return {h["value"]: h["count"] for h in hits}

    try:
        # ---- setup ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: create failed: {err[:200]}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "create_index", path_params={"name": C},
                              body={"field_name": "tier",
                                    "field_schema": {"type": "keyword"}},
                              query_params={"wait": "true"})
        print(f"[setup index] status={s} raw={str(raw)[:150]}")
        if s != 200:
            print(f"SETUP_ERROR: create_index returned {s}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points", path_params={"name": C},
                              body={"points": pts}, query_params={"wait": "true"})
        print(f"[setup upsert] status={s} raw={str(raw)[:150]}")
        if s not in (200, 201):
            print("SETUP_ERROR: upsert failed")
            return "SCRIPT_ERROR"

        # ---- (A) default-10 closure ----
        m = facet_limit("A default-10", limit=None)
        if m is None:
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        if m != WANT_TOP10:
            DEFECTS.append(f"(A) facet without limit returned {len(m)} hits {m} but "
                           f"the assertion pins default limit 10 -> the top-10 "
                           f"multiset {WANT_TOP10} - Type4_StateLogicViolation "
                           f"(qdrant_range_facet_001)")
            return "DEFECT_FOUND"
        print("[A] OK: omitted limit -> exactly the top-10 multiset (default 10)")

        # ---- (B) min closure: limit=1 -> single top hit v1:25 ----
        m = facet_limit("B limit=1", limit=1)
        if m is None:
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        if m != {"v1": 25}:
            DEFECTS.append(f"(B) facet limit=1 returned {m} but the strictly-ordered "
                           f"seed pins the single hit v1:25 - Type4_StateLogicViolation")
            return "DEFECT_FOUND"
        print("[B] OK: limit=1 -> single hit v1:25 (minimum-limit closure)")

        # ---- (C) invariance: counts under limit=5 == counts under limit=25 ----
        m5 = facet_limit("C limit=5", limit=5)
        m25 = facet_limit("C2 limit=25", limit=25)
        if m5 is None or m25 is None:
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        if len(m5) != 5 or m25 != WANT_ALL25:
            DEFECTS.append(f"(C) limit=5 -> {len(m5)} hits / limit=25 -> {len(m25)} "
                           f"hits; expected 5 and 25 with the seed multiset - "
                           f"Type4_StateLogicViolation")
            return "DEFECT_FOUND"
        for v, c in m5.items():
            if m25.get(v) != c:
                DEFECTS.append(f"(C) value {v} count {c} under limit=5 but {m25.get(v)} "
                               f"under limit=25 - limit truncated the list but altered "
                               f"the count - Type4_StateLogicViolation")
                return "DEFECT_FOUND"
        print("[C] OK: counts invariant across limit=5 and limit=25 readouts")

        # ---- (D) above-cardinality legal limits ----
        m50 = facet_limit("D limit=50", limit=50)
        if m50 is None:
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        if m50 != WANT_ALL25:
            DEFECTS.append(f"(D) facet limit=50 returned {len(m50)} hits; expected all "
                           f"25 values unchanged - Type4_StateLogicViolation")
            return "DEFECT_FOUND"
        print("[D] OK: limit=50 above cardinality -> all 25 values, no error")

        # ---- (E) below-min rejection: limit=0 and limit=-1 must be 400 ----
        for lv in (0, -1):
            s, raw = safe_request("POST", "facet",
                                  body={"key": "tier", "exact": True, "limit": lv},
                                  path_params={"collection_name": C})
            print(f"[E limit={lv}] status={s} raw={str(raw)[:220]}")
            if s == 0 or 500 <= s <= 599:
                liveness(f"E-{lv}")
                return "SCRIPT_ERROR"
            if s == 200:
                shape_ok, hits, note = parse_facet(raw)
                got = len(hits) if shape_ok else f"unparsed ({note})"
                DEFECTS.append(f"(E) facet limit={lv} (below the asserted minimum 1) "
                               f"was ACCEPTED with 200 and {got} hits - "
                               f"Type1_IllegalSuccess (qdrant_range_facet_001)")
                return "DEFECT_FOUND"
            if s not in (400, 422):
                DEFECTS.append(f"(E) facet limit={lv} returned {s}; expected a 400 "
                               f"validation rejection - Type4_StateLogicViolation")
                return "DEFECT_FOUND"
            print(f"[E limit={lv}] OK: rejected with {s} (minimum-1 range enforced)")

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
