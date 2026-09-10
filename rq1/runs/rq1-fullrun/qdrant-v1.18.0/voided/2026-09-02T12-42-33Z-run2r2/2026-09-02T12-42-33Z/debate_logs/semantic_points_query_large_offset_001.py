#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_large_offset_001
# strategy: strategy1 behavioral-contract attack (large-offset legality face)
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_002
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-04 (boundary value optimism at large offsets) — the TMA lists
#            "offset with large values" in this endpoint's attack order
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy1 large-offset legality x qdrant_behavioral_points_query_002 —
  the contract documents large offset values as LEGAL inputs that "may cause
  performance issues": slowness itself is documented behavior and is NOT
  judged (G3 avoidance); the semantic promise under attack is legality —
  a large offset must not crash, hang, or be mis-served. Legs on an
  8-point collection, deterministic id-ordered no-query mode plus the
  nearest-query face:
    F1 offset=8 (=N)          -> 200 with EXACTLY 0 points (hard oracle)
    F2 offset=8+100000        -> 200 with 0 points (timing recorded,
                                 generous timeout, never flagged)
    F3 offset=1000000 limit=3 -> 200 with 0 points
    F4 offset=3 limit=5       -> exactly 5 points (arithmetic control that
                                 proves the offset machinery works before
                                 the large legs — G4 pairing)
    F5 nearest-query face offset=8 -> 200 with 0 points
  Disposition policy (G5): 4xx on F2/F3 with a clear guardrail message is
  recorded as NOTE (strict-mode guardrails exist as a documented feature;
  the doc phrasing does not fix an upper bound) — but 4xx on F1 (offset
  exactly N) is a hard Type1 defect: an offset equal to the collection
  size is plainly within the documented domain.
  [chunk_points+query semantic coverage — see variant_domain_001 for the
  full 10-script coverage list; this script = large-offset x
  qdrant_behavioral_points_query_002]
Oracle: F1/F4/F5 -> HTTP 200 with result.points of length 0 / 5 / 0
  respectively (arithmetic-derived: 8 seeded ids, offset skips the first
  offset ids); F2/F3 -> 200 with 0 points (NOTE on clean 4xx); any 5xx =
  Type3_RuntimeFailure after /healthz liveness re-check; 4xx on F1 =
  Type1_IllegalSuccess; transport failure -> /healthz re-check then
  SCRIPT_ERROR (constraint qdrant_behavioral_points_query_002).
Constraint: qdrant_behavioral_points_query_002 (bare id) — "large offsets
  are legal but may degrade performance; slowness on large offsets is
  documented, not a defect" (evidence_tier: explicit; level: endpoint)

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
import time
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
N = 8
IDS = list(range(81, 81 + N))
SEED = [{"id": i, "vector": [float(i - 81), 1.0, 0.0, 0.5]} for i in IDS]


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


def transport_dead(where):
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


def get_points(body):
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, dict) and isinstance(r.get("points"), list):
            return r["points"]
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqO1" + tag

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

        qpath = f"/collections/{coll}/points/query"

        def run(leg, body_json, timeout=60):
            t0 = time.time()
            s, body, raw = safe_request("POST", qpath, json=body_json, timeout=timeout)
            dt = time.time() - t0
            print(f"{leg} -> status={s} elapsed={dt:.2f}s")
            print(f"raw: {raw[:300]}")
            return s, body, raw, dt

        # ---- F4 (control first): offset=3 limit=5 -> exactly 5 points ----
        s, body, raw, _ = run("F4 offset=3 limit=5 (control)", {"limit": 5, "offset": 3})
        if s == -1:
            transport_dead("F4"); return
        if handle_5xx(s, raw, "F4 control"):
            return
        pts = get_points(body)
        if s != 200 or pts is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F4: in-range "
                  f"offset=3 rejected with {s}: {raw[:250]}")
            return
        if len(pts) != 5 or [p.get("id") for p in pts] != sorted(IDS)[3:8]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F4: "
                  f"offset=3/limit=5 must slice the id order to "
                  f"{sorted(IDS)[3:8]}, got {[p.get('id') for p in pts]}: {raw[:250]}")
            return
        print("F4 OK: offset machinery verified (slice arithmetic exact)")

        # ---- F1: offset == N -> exactly 0 points (hard oracle) ----
        s, body, raw, _ = run("F1 offset=8 (=N)", {"limit": 5, "offset": N})
        if s == -1:
            transport_dead("F1"); return
        if handle_5xx(s, raw, "F1 offset=N"):
            return
        pts = get_points(body)
        if 400 <= s <= 499:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F1: offset "
                  f"equal to the collection size (8) is within the documented "
                  f"domain (min 0, large values legal), rejected with {s}: "
                  f"{raw[:250]}")
            return
        if s != 200 or pts is None or len(pts) != 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F1: "
                  f"offset=N over N points must return 0 points with 200, got "
                  f"status={s} len={len(pts) if pts is not None else 'None'}: "
                  f"{raw[:250]}")
            return
        print("F1 OK: offset=N -> 200 with 0 points")

        # ---- F2: offset = N + 100000 ----
        s, body, raw, _ = run("F2 offset=100008", {"limit": 5, "offset": N + 100000},
                              timeout=120)
        if s == -1:
            transport_dead("F2"); return
        if handle_5xx(s, raw, "F2 large offset"):
            return
        if 200 <= s <= 299:
            pts = get_points(body)
            if pts is None or len(pts) != 0:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F2: "
                      f"offset far beyond collection size must yield 0 points, "
                      f"got {len(pts) if pts is not None else 'None'}: {raw[:250]}")
                return
            print("F2 OK: large offset -> 200 with 0 points (elapsed recorded, "
                  "slowness documented — not judged)")
        elif 400 <= s <= 499:
            print("NOTE F2: large offset rejected with 4xx "
                  f"({str(raw)[:150]}) — guardrail-vs-doc judge call, recorded")
        else:
            print(f"VERDICT: SCRIPT_ERROR — F2 unexpected status {s}; no defect "
                  f"conclusion")
            return

        # ---- F3: offset = 1000000 with limit ----
        s, body, raw, _ = run("F3 offset=1000000 limit=3", {"limit": 3, "offset": 1000000},
                              timeout=120)
        if s == -1:
            transport_dead("F3"); return
        if handle_5xx(s, raw, "F3 million offset"):
            return
        if 200 <= s <= 299:
            pts = get_points(body)
            if pts is None or len(pts) != 0:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F3: "
                      f"offset=1000000 must yield 0 points, got "
                      f"{len(pts) if pts is not None else 'None'}: {raw[:250]}")
                return
            print("F3 OK: million-scale offset -> 200 with 0 points")
        elif 400 <= s <= 499:
            print("NOTE F3: million-scale offset rejected with 4xx — same "
                  "guardrail-vs-doc disposition as F2, recorded")
        else:
            print(f"VERDICT: SCRIPT_ERROR — F3 unexpected status {s}; no defect "
                  f"conclusion")
            return

        # ---- F5: nearest-query face with offset=N ----
        s, body, raw, _ = run("F5 nearest offset=8", {
            "query": {"nearest": [0.0, 1.0, 0.0, 0.5]},
            "params": {"exact": True}, "limit": 5, "offset": N})
        if s == -1:
            transport_dead("F5"); return
        if handle_5xx(s, raw, "F5 nearest offset"):
            return
        pts = get_points(body)
        if s != 200 or pts is None or len(pts) != 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F5: "
                  f"nearest query with offset=N must return 0 points with 200, "
                  f"got status={s} len={len(pts) if pts is not None else 'None'}: "
                  f"{raw[:250]}")
            return
        print("F5 OK: nearest-query large-offset face consistent")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
