#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_variant_domain_001
# strategy: strategy1 behavioral-contract attack (query variant oneOf domain closure)
# endpoint: points+query
# constraint_ids: qdrant_type_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust) + BS-05 (query-variant
#            validation is this endpoint's first listed blindspot)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy1 variant-domain closure x qdrant_type_points_query_001 —
  the contract fixes the query variant domain as a oneOf: nearest | recommend
  | discover | context | order_by | fusion | sample | neartext | nearimage
  (neartext/nearimage are inference variants, unimplemented per the spec WARN
  inside the constraint description -> SKIPPED: out of contract scope, they
  target the inference-server integration, not the query engine).
  Legs on a 12-point Euclid dim-4 collection (binary-exact float vectors):
    P1 nearest  (dense vector)      -> top-1 must be the query point, score 1.0
    P2 sample    ("random")         -> 200, exactly limit points, ids subset
    P3 recommend (positive id)      -> 200, non-empty, membership
    P4 context   (pos/neg pair)     -> 200, non-empty, membership
    P5 discover  (target + context) -> derivable: target satisfies its own
                                       context constraint (d(t,pos) < d(t,neg)
                                       by construction), so target MUST appear
    P6 order_by  (payload key ts)   -> ts strictly ascending over all 12
    P7 fusion    (rrf, 2 prefetch)  -> two IDENTICAL prefetch rankings fuse to
                                       the same ranking -> top-1 == nearest top-1
    N1 unknown variant key          -> 4xx (domain violated if 2xx)
    N2 dual variant keys            -> oneOf ambiguity; disposition recorded as
                                       NOTE only (untagged-enum tolerance)
    N3 nearest = non-vector/non-uuid string -> 4xx (VectorInput oneOf violated)
    N4 sample    = bogus enum value -> 4xx
  [chunk_points+query semantic coverage (10 scripts): type-domain x
  qdrant_type_points_query_001 (this); metamorphic default-limit x
  qdrant_range_points_query_001 (default_limit_001); params-range x
  qdrant_range_points_query_002 (params_bounds_001); by-id-lookup x
  qdrant_state_points_query_001 (byid_lookup_001); status-faces x
  qdrant_behavioral_points_query_001 (status_faces_001); large-offset x
  qdrant_behavioral_points_query_002 (large_offset_001); exact-pagination x
  qdrant_behavioral_points_query_003 (exact_pagination_001); id-order x
  qdrant_behavioral_points_query_004 (id_order_001); filter_semantics
  min_should x TMA-order#1 (minshould_001); filter_semantics nested x
  TMA-order#2 (nested_filter_001)]
Oracle: every P-leg -> HTTP 200 with result.points a list of seeded ids (P1/P7
  top-1 id 101 score 1.0 Euclid; P2 exactly 5 points; P5 contains id 105; P6
  ts strictly ascending over 12); every hard N-leg (N1/N3/N4) -> 4xx; any
  2xx on N1/N3/N4 = Type1_IllegalSuccess (query variant domain not enforced);
  wrong P-leg membership/count = Type4_StateLogicViolation; 5xx with
  /healthz alive = Type3_RuntimeFailure; transport failure -> /healthz
  re-check then SCRIPT_ERROR (constraint qdrant_type_points_query_001).
Constraint: qdrant_type_points_query_001 (bare id) — "query variant domain:
  nearest | recommend | discover | context | order_by | fusion | sample |
  neartext | nearimage (oneOf)" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query        -> POST /collections/{collection_name}/points/query
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
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
QUERY_PATH = "/collections/{c}/points/query"
UPSERT_PATH = "/collections/{c}/points"


def v_of(base):
    """Deterministic distinct dim-4 vectors, values exactly representable in f32."""
    return [float(base % 3), float((base * 2) % 5), float((base * 7) % 4), float(base % 2)]


IDS = list(range(101, 113))  # 12 points, base = id - 101
SEED = [{"id": i, "vector": v_of(i - 101), "payload": {"ts": i - 101}} for i in IDS]


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
    """Inline liveness probe on the lightweight healthz face."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def transport_dead(where):
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")


def handle_5xx(rs, rraw, leg):
    """5xx branch with liveness re-check; True means handled (caller returns)."""
    if not (500 <= rs <= 599):
        return False
    alive, _, _ = healthz_alive()
    if alive:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{leg}]: {rs} "
              f"with service alive: {rraw[:300]}")
    else:
        print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
    return True


def get_points(body):
    """Extract result.points per published QueryResponse shape (result.points)."""
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, dict) and isinstance(r.get("points"), list):
            return r["points"]
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqV1" + tag

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        s, _, raw = safe_request("PUT", UPSERT_PATH.format(c=coll),
                                 json={"points": SEED}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        qpath = QUERY_PATH.format(c=coll)

        def fail(vtype, leg, why):
            print(f"VERDICT: DEFECT_FOUND ({vtype}) — leg [{leg}]: {why}")

        # ---- P1: nearest (dense vector) ----
        s, body, raw = safe_request("POST", qpath,
                                    json={"query": {"nearest": v_of(0)},
                                          "params": {"exact": True}, "limit": 3}, timeout=60)
        print(f"P1 nearest -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            transport_dead("P1 nearest"); return
        if handle_5xx(s, raw, "P1 nearest"):
            return
        pts = get_points(body)
        if s != 200 or pts is None or not pts:
            fail("Type1_IllegalSuccess", "P1 nearest",
                 f"documented variant rejected/malformed: status={s}: {raw[:250]}"); return
        if pts[0].get("id") != 101 or abs(float(pts[0].get("score", 0.0)) - 1.0) > 1e-6:
            fail("Type4_StateLogicViolation", "P1 nearest",
                 f"exact Euclid self-match must be top-1 id 101 score 1.0, got "
                 f"id={pts[0].get('id')} score={pts[0].get('score')}: {raw[:250]}"); return
        print("P1 OK: nearest top-1 == query point, score 1.0")

        # ---- P2: sample ("random") ----
        s, body, raw = safe_request("POST", qpath,
                                    json={"query": {"sample": "random"}, "limit": 5}, timeout=60)
        print(f"P2 sample -> status={s}")
        if s == -1:
            transport_dead("P2 sample"); return
        if handle_5xx(s, raw, "P2 sample"):
            return
        pts = get_points(body)
        if s != 200 or pts is None:
            fail("Type1_IllegalSuccess", "P2 sample",
                 f"documented variant rejected: status={s}: {raw[:250]}"); return
        ids = [p.get("id") for p in pts]
        if len(pts) != 5 or any(i not in IDS for i in ids):
            fail("Type4_StateLogicViolation", "P2 sample",
                 f"limit=5 over 12 points must give exactly 5 seeded ids, got {ids}: {raw[:250]}"); return
        print("P2 OK: sample returned exactly 5 seeded ids")

        # ---- P3: recommend (positive point id) ----
        s, body, raw = safe_request("POST", qpath,
                                    json={"query": {"recommend": {"positive": [102]}},
                                          "params": {"exact": True}, "limit": 12}, timeout=60)
        print(f"P3 recommend -> status={s}")
        if s == -1:
            transport_dead("P3 recommend"); return
        if handle_5xx(s, raw, "P3 recommend"):
            return
        pts = get_points(body)
        if s != 200 or pts is None or not pts:
            fail("Type1_IllegalSuccess", "P3 recommend",
                 f"documented variant rejected/empty: status={s}: {raw[:250]}"); return
        ids = [p.get("id") for p in pts]
        if any(i not in IDS for i in ids):
            fail("Type4_StateLogicViolation", "P3 recommend",
                 f"results outside collection: {ids}: {raw[:250]}"); return
        if 102 not in ids:
            print(f"NOTE P3: recommend(positive=[102]) did not include the anchor id "
                  f"102 in results ({ids[:6]}...) — membership convention, not judged")
        print("P3 OK: recommend accepted with seeded results")

        # ---- P4: context (pos/neg pair) ----
        s, body, raw = safe_request("POST", qpath,
                                    json={"query": {"context": [{"positive": 102, "negative": 103}]},
                                          "params": {"exact": True}, "limit": 12}, timeout=60)
        print(f"P4 context -> status={s}")
        if s == -1:
            transport_dead("P4 context"); return
        if handle_5xx(s, raw, "P4 context"):
            return
        pts = get_points(body)
        if s != 200 or pts is None or not pts:
            fail("Type1_IllegalSuccess", "P4 context",
                 f"documented variant rejected/empty: status={s}: {raw[:250]}"); return
        ids = [p.get("id") for p in pts]
        if any(i not in IDS for i in ids):
            fail("Type4_StateLogicViolation", "P4 context",
                 f"results outside collection: {ids}: {raw[:250]}"); return
        print("P4 OK: context accepted with seeded results")

        # ---- P5: discover (target + context); target qualifies by construction ----
        # d(105,102)=sqrt(2) < d(105,103)=sqrt(3) -> target satisfies its context
        s, body, raw = safe_request("POST", qpath,
                                    json={"query": {"discover": {"target": 105,
                                                                 "context": [{"positive": 102, "negative": 103}]}},
                                          "params": {"exact": True}, "limit": 12}, timeout=60)
        print(f"P5 discover -> status={s}")
        if s == -1:
            transport_dead("P5 discover"); return
        if handle_5xx(s, raw, "P5 discover"):
            return
        pts = get_points(body)
        if s != 200 or pts is None:
            fail("Type1_IllegalSuccess", "P5 discover",
                 f"documented variant rejected: status={s}: {raw[:250]}"); return
        ids = [p.get("id") for p in pts]
        if 105 not in ids:
            fail("Type4_StateLogicViolation", "P5 discover",
                 f"target 105 satisfies its own context constraint (d(t,pos)=1.414 < "
                 f"d(t,neg)=1.732) so it MUST appear in discover results, got {ids}: {raw[:250]}"); return
        print("P5 OK: discover includes its qualifying target")

        # ---- P6: order_by (payload key ts, ascending) ----
        s, body, raw = safe_request("POST", qpath,
                                    json={"query": {"order_by": {"key": "ts", "direction": "asc"}},
                                          "limit": 12, "with_payload": True}, timeout=60)
        print(f"P6 order_by -> status={s}")
        if s == -1:
            transport_dead("P6 order_by"); return
        if handle_5xx(s, raw, "P6 order_by"):
            return
        pts = get_points(body)
        if s != 200 or pts is None:
            fail("Type1_IllegalSuccess", "P6 order_by",
                 f"documented variant rejected: status={s}: {raw[:250]}"); return
        ts_seq = [p.get("payload", {}).get("ts") for p in pts]
        if len(pts) != 12 or any(t is None for t in ts_seq):
            fail("Type4_StateLogicViolation", "P6 order_by",
                 f"order_by over 12 points with ts must return all 12 with payload, "
                 f"got {len(pts)} ts={ts_seq}: {raw[:250]}"); return
        if ts_seq != sorted(ts_seq):
            fail("Type4_StateLogicViolation", "P6 order_by",
                 f"direction=asc must give strictly ascending ts, got {ts_seq}: {raw[:250]}"); return
        print("P6 OK: order_by ts ascending over all 12 points")

        # ---- P7: fusion (rrf over two identical prefetch rankings) ----
        pre = {"query": {"nearest": v_of(0)}, "limit": 10, "params": {"exact": True}}
        s, body, raw = safe_request("POST", qpath,
                                    json={"prefetch": [pre, pre],
                                          "query": {"fusion": "rrf"}, "limit": 3}, timeout=60)
        print(f"P7 fusion -> status={s}")
        if s == -1:
            transport_dead("P7 fusion"); return
        if handle_5xx(s, raw, "P7 fusion"):
            return
        pts = get_points(body)
        if s != 200 or pts is None or not pts:
            fail("Type1_IllegalSuccess", "P7 fusion",
                 f"documented variant rejected/empty: status={s}: {raw[:250]}"); return
        if pts[0].get("id") != 101:
            fail("Type4_StateLogicViolation", "P7 fusion",
                 f"RRF of two IDENTICAL rankings preserves that ranking, top-1 must "
                 f"be 101, got {pts[0].get('id')}: {raw[:250]}"); return
        print("P7 OK: fusion of identical rankings preserves top-1")

        # ---- N1: unknown variant key -> must be rejected ----
        s, _, raw = safe_request("POST", qpath,
                                 json={"query": {"totally_bogus_variant": {}}, "limit": 3}, timeout=60)
        print(f"N1 unknown variant -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1:
            transport_dead("N1"); return
        if handle_5xx(s, raw, "N1 unknown variant"):
            return
        if 200 <= s <= 299:
            fail("Type1_IllegalSuccess", "N1 unknown variant",
                 f"'totally_bogus_variant' matches NO member of the documented oneOf "
                 f"domain but was accepted with {s}: {raw[:250]}"); return
        if not (400 <= s <= 499):
            print(f"VERDICT: SCRIPT_ERROR — N1 unexpected status {s}; no defect conclusion"); return
        print("N1 OK: unknown variant rejected by 4xx")

        # ---- N2: dual variant keys (oneOf ambiguity) -> disposition NOTE only ----
        s, body, raw = safe_request("POST", qpath,
                                    json={"query": {"order_by": {"key": "ts"},
                                                    "nearest": v_of(0)},
                                          "limit": 3}, timeout=60)
        print(f"N2 dual variant -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1:
            transport_dead("N2"); return
        if handle_5xx(s, raw, "N2 dual variant"):
            return
        if 200 <= s <= 299:
            pts = get_points(body)
            first = pts[0].get("id") if pts else None
            looks = "order_by (lowest ts first)" if first == 101 else f"other (first id {first})"
            print(f"NOTE N2: dual-variant query accepted with {s} — untagged-enum "
                  f"tolerance, executed as {looks}; oneOf ambiguity disposition "
                  f"recorded, not judged (serde tolerance convention)")
        else:
            print("NOTE N2: dual-variant query rejected with "
                  f"{s} — strict oneOf enforcement; disposition recorded")

        # ---- N3: nearest = string that is neither vector nor UUID ----
        s, _, raw = safe_request("POST", qpath,
                                 json={"query": {"nearest": "not-a-uuid-or-vector"},
                                       "limit": 3}, timeout=60)
        print(f"N3 nearest=bad string -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1:
            transport_dead("N3"); return
        if handle_5xx(s, raw, "N3 nearest bad string"):
            return
        if 200 <= s <= 299:
            fail("Type1_IllegalSuccess", "N3 nearest bad string",
                 f"VectorInput oneOf has no branch for a plain non-UUID string, "
                 f"accepted with {s}: {raw[:250]}"); return
        print("N3 OK: non-vector/non-uuid nearest rejected by 4xx")

        # ---- N4: sample = bogus enum value ----
        s, _, raw = safe_request("POST", qpath,
                                 json={"query": {"sample": "bogus"}, "limit": 3}, timeout=60)
        print(f"N4 sample=bogus -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1:
            transport_dead("N4"); return
        if handle_5xx(s, raw, "N4 sample bogus"):
            return
        if 200 <= s <= 299:
            fail("Type1_IllegalSuccess", "N4 sample bogus",
                 f"Sample enum is documented as {'random'} only, 'bogus' accepted "
                 f"with {s}: {raw[:250]}"); return
        print("N4 OK: bogus sample enum rejected by 4xx")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
