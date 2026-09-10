#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_facet_004
# strategy: resource_bound_state_survival
# endpoint: facet
# constraint_ids: qdrant_resource_facet_limit_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/facet
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-07 (resource-extreme spec-legal input must not kill the service)
"""
Attack: resource_bound_state_survival x qdrant_resource_facet_limit_001
  (inferred: any spec-legal limit (>= 1) must complete, be rejected with an
  error, or fail with a documented service error - never crash the service).
  G4 both-direction probes on POST facet's limit over one keyword-indexed
  collection with 1000 points / 500 distinct values (2 per value):
  (P1 positive min-face) limit=1 -> 200 and exactly 1 hit with count 2
    (the minimum-limit face works and reads true state).
  (P2 extreme escalation) spec-legal limits with no documented maximum:
    limit=1_000_000 (above cardinality), limit=1_000_000_000_000 (1e12),
    limit=9_000_000_000_000_000_000 (9e18, below usize/u64 max so the JSON
    parses into the schema type). Every probe must end in ONE of the three
    graceful outcomes the constraint allows: 200 with hits (bounded by the
    500 distinct values), a 4xx rejection with a descriptive error, or a
    documented service error - NEVER a service crash/hang. A connection
    abort/reset or 5xx triggers an inline /healthz liveness probe pair:
    healthz not 200 (service dead) = Type3_RuntimeFailure; 5xx with healthz
    alive and an undiagnostic body = Type3_RuntimeFailure.
  (P3 repeated extreme) the 9e18 probe is repeated 3x consecutively —
    mutation rationale (G6): an allocation/sizing bug on the astronomic
    limit path needs repeated pressure to surface (capacity-overflow panics
    are often only reachable on the 2nd+ request after caches warm).
  (P4 post-attack control) facet limit=10 -> 200 with 10 hits AND
    POST points/count exact -> 200 count=1000: the service must still serve
    correct state after the extremes (ghost degradation = Type3).
Oracle: every spec-legal limit probe (1, 1e6, 1e12, 9e18 x3) returns 200 or
  a descriptive 4xx/5xx with /healthz still 200 — never a connection
  abort/reset with /healthz failing (Type3_RuntimeFailure = service death
  or panic); after the extremes the control facet returns 10 hits and the
  count face reads 1000 (qdrant_resource_facet_limit_001)
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
                 query_params=None, timeout=60):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks.
    Timeout 60s: an extreme-limit probe that outlives this is a hang signal
    handled by the transport branch (never judged a defect without healthz)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_facet(raw):
    """(shape_ok, hits_len_or_None, note) per materialized response_shape
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
    return True, len(hits), ""


def healthz_ok(tag):
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:140]}")
    return hs == 200


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sf4_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    EXTREMES = [1_000_000, 1_000_000_000_000, 9_000_000_000_000_000_000]

    # 1000 points: value t{i} (i=0..499) carried by exactly 2 points each
    pts = []
    pid = 0
    for i in range(500):
        for _ in range(2):
            pid += 1
            pts.append({"id": pid, "vector": [0.01 * i, 0.2, 0.3, 0.4],
                        "payload": {"tier": f"t{i}"}})
    assert len(pts) == 1000, len(pts)

    def probe_extreme(tag, limit, expect_hits):
        """One extreme-limit facet probe. Returns:
        True = graceful (200 / descriptive 4xx / descriptive 5xx w/ alive
        healthz), False = defect recorded, None = env-class abort."""
        s, raw = safe_request("POST", "facet",
                              body={"key": "tier", "limit": limit},
                              path_params={"collection_name": C})
        print(f"[{tag}] facet limit={limit} status={s} raw={str(raw)[:260]}")
        if s == 0:
            # transport failure: liveness re-check before any conclusion
            if not healthz_ok(tag + "-transport"):
                DEFECTS.append(f"({tag}) spec-legal limit={limit} killed the service "
                               f"(transport failure + /healthz not 200) - "
                               f"Type3_RuntimeFailure (qdrant_resource_facet_limit_001)")
                return False
            print(f"[{tag}] transport failure but /healthz alive (env/transient)")
            return None
        if 500 <= s <= 599:
            if not healthz_ok(tag):
                DEFECTS.append(f"({tag}) spec-legal limit={limit} killed the service "
                               f"(5xx + /healthz not 200) - Type3_RuntimeFailure")
                return False
            low = str(raw).lower()
            if "internal" in low or "panic" in low or low.strip() == "":
                DEFECTS.append(f"({tag}) spec-legal limit={limit} returned 5xx {s} "
                               f"with service alive and no documented error - "
                               f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
                return False
            print(f"[{tag}] 5xx {s} with a documented error while service alive "
                  f"(graceful per constraint wording)")
            return True
        if s in (400, 422):
            print(f"[{tag}] rejected {s} with an error (graceful outcome per "
                  f"constraint wording)")
            return True
        if s != 200:
            print(f"[{tag}] unexpected status {s} - recorded, service alive")
            return None
        shape_ok, n, note = parse_facet(raw)
        if not shape_ok:
            DEFECTS.append(f"({tag}) facet 200 but shape violation ({note}) - "
                           f"Type4_StateLogicViolation - raw={str(raw)[:160]}")
            return False
        if n != expect_hits:
            DEFECTS.append(f"({tag}) facet 200 limit={limit} returned {n} hits; "
                           f"expected {expect_hits} (bounded by the 500 distinct "
                           f"values) - Type4_StateLogicViolation")
            return False
        print(f"[{tag}] OK: 200 with {n} hits (graceful completion)")
        return True

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

        # ---- (P1) positive minimum face ----
        r = probe_extreme("P1 min-limit", 1, expect_hits=1)
        if r is False:
            return "DEFECT_FOUND"
        if r is None:
            return "SCRIPT_ERROR"

        # ---- (P2) extreme escalation 1e6 -> 1e12 -> 9e18 ----
        for lim in EXTREMES:
            r = probe_extreme("P2", lim, expect_hits=500)
            if r is False:
                return "DEFECT_FOUND"
            if r is None:
                return "SCRIPT_ERROR"

        # ---- (P3) repeated 9e18 x3 (warm-path pressure) ----
        for rep in range(3):
            r = probe_extreme(f"P3-rep{rep + 1}", 9_000_000_000_000_000_000,
                              expect_hits=500)
            if r is False:
                return "DEFECT_FOUND"
            if r is None:
                return "SCRIPT_ERROR"

        # ---- (P4) post-attack control: state still served correctly ----
        s, raw = safe_request("POST", "facet", body={"key": "tier", "limit": 10},
                              path_params={"collection_name": C})
        print(f"[P4 control facet] status={s} raw={str(raw)[:220]}")
        if s == 0 or 500 <= s <= 599:
            if not healthz_ok("P4"):
                DEFECTS.append("(P4) control facet after the extreme probes: service "
                               "dead - Type3_RuntimeFailure")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if s != 200:
            DEFECTS.append(f"(P4) control facet returned {s} after the extreme probes "
                           f"(service degraded) - Type3_RuntimeFailure")
            return "DEFECT_FOUND"
        shape_ok, n10, note = parse_facet(raw)
        if not shape_ok or n10 != 10:
            DEFECTS.append(f"(P4) control facet after extremes returned {n10} hits "
                           f"(expected 10) - ghost state degradation - "
                           f"Type3_RuntimeFailure")
            return "DEFECT_FOUND"
        cs, craw = safe_request("POST", "count", body={"exact": True},
                                path_params={"name": C})
        print(f"[P4 control count] status={cs} raw={str(craw)[:200]}")
        if cs != 200:
            DEFECTS.append(f"(P4) control count returned {cs} after the extreme probes "
                           f"- Type3_RuntimeFailure")
            return "DEFECT_FOUND"
        try:
            cnt = json.loads(craw)["result"]["count"]
        except Exception:
            cnt = None
        if cnt != 1000:
            DEFECTS.append(f"(P4) control count reads {cnt}, expected 1000 after the "
                           f"extreme probes - state corruption - Type4_StateLogicViolation")
            return "DEFECT_FOUND"
        print(f"[P4] OK: control facet 10 hits and count 1000 after extremes")

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
