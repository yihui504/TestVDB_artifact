#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_count_malformed_006
# strategy: strategy7 malformed-input / character-boundary attack (raw body
#           stream malformation on the count face; general JSON-over-HTTP
#           dimension — no DB-specific field is assumed)
# endpoint: points+count
# constraint_ids: qdrant_behavioral_points_count_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/count-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (serde trusted with malformed streams) — raw bodies are
#            sent via data= bytes so client-side json= serialization cannot
#            pre-reject the probe; only the server's parser answers
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-body x qdrant_behavioral_points_count_001 —
  the count promise ("HTTP 200 with {count}") presupposes a well-formed JSON
  body; malformed input streams must be answered with a clean 4xx, never a
  crash. All probes are sent as RAW BYTES via data= (bypassing client json=
  serialization) against a LIVE 12-point collection:
    F1 truncated JSON  b'{"filter": {"must": [{"key": "city"' — no closing
       brackets: RFC-invalid; 400/422 clean; 2xx = Type1 (malformed stream
       accepted); 5xx = Type3.
    F2 trailing comma  b'{"exact": true,}' — RFC-invalid; same posture.
    F3 raw NUL byte inside a JSON string key b'"ci\\x00ty"' — control chars
       MUST be escaped per RFC 8259, a raw NUL makes the stream invalid;
       400/422 clean; 2xx = Type1 (invalid control char accepted); 5xx =
       Type3.
    F4 VALID JSON with escaped NUL in a match value
       b'{"filter":{"must":[{"key":"city","match":{"value":"ber\\u0000lin"}}]}}'
       — legal JSON, unsatisfiable value: 200 with count == 0 (or a clean
       4xx rejection of the control character IN a value); 200 with
       count > 0 = Type4 (value that was never seeded cannot match);
       5xx = Type3.
  [chunk_points+count coverage: strategy7 malformed-input x request body x
  qdrant_behavioral_points_count_001 (this script; strategy1 baselines in
  boundary_points_count_all_001 / boundary_points_count_filter_arith_002,
  strategy2 type faces in boundary_points_count_filter_type_003 /
  boundary_points_count_min_should_004 / boundary_points_count_exact_type_005)]
Oracle: F1/F2/F3 -> 400/422 clean rejection; any 2xx =
  Type1_IllegalSuccess (RFC-invalid JSON stream silently accepted); any 5xx
  with /healthz alive = Type3_RuntimeFailure (parser must not crash);
  F4 -> 200 with result.count == 0 or clean 4xx; 200 with count > 0 =
  Type4_StateLogicViolation (unseeded value matched); transport failure ->
  /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_count_001).
Constraint: qdrant_behavioral_points_count_001 (bare id) — "exact=true
  (default) performs an exact count (slower); an omitted filter counts all
  points" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+count         -> POST /collections/{collection_name}/points/count
  collections+create   -> PUT  /collections/{collection_name}
  collections+delete   -> DELETE /collections/{collection_name}
  points+upsert        -> PUT  /collections/{collection_name}/points
  healthz              -> GET  /healthz
  (wait is a query parameter on the upsert face — passed via params=)
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
N_SEED = 12
BERLIN_N = 8
PARIS_N = 4  # BERLIN_N + PARIS_N == N_SEED
V = [0.1, 0.2, 0.3, 0.4]


def safe_request(method, endpoint, json=None, timeout=60, params=None, data=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params via params=; raw body streams via data= (bytes) so malformed
    probes reach the server parser without client-side serialization.
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, headers=headers,
            timeout=timeout, params=params, data=data,
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
    """Transport-branch liveness re-check (lightweight healthz face only)."""
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return False


# Raw probe bodies (bytes; \\x00 is a REAL NUL byte, \\u0000 is the ESCAPED form)
PROBE_TRUNCATED = b'{"filter": {"must": [{"key": "city"'
PROBE_TRAILING_COMMA = b'{"exact": true,}'
PROBE_RAW_NUL_KEY = (b'{"filter": {"must": [{"key": "ci\x00ty", '
                     b'"match": {"value": "berlin"}}]}, "exact": true}')
PROBE_ESCAPED_NUL_VALUE = (b'{"filter": {"must": [{"key": "city", '
                           b'"match": {"value": "ber\\u0000lin"}}]}}')

coll = ""


def run_probe(raw_body, label):
    """POST one raw-body count probe; returns (s, count_or_None, raw)."""
    s, b, raw = safe_request("POST", f"/collections/{coll}/points/count",
                             data=raw_body, timeout=60)
    print(f"\n{label} -> status={s}")
    print(f"body bytes: {raw_body[:120]!r}")
    print(f"raw: {raw[:400]}")
    if s == -1:
        transport_dead(label)
        return None, None, None
    count = None
    if s == 200 and isinstance(b, dict) and isinstance(b.get("result"), dict):
        count = b["result"].get("count")
    return s, count, raw


def main():
    global coll
    tag = uuid.uuid4().hex[:8]
    coll = "bpcX6" + tag

    # Arrange: own collection + live data-bearing target (wait=true => durable)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    points = []
    for i in range(1, N_SEED + 1):
        city = "berlin" if i <= BERLIN_N else "paris"
        points.append({"id": i, "vector": V, "payload": {"city": city}})
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": points}, params={"wait": "true"}, timeout=120)
    if s not in (200, 201):
        print(f"setup upsert failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # Control face: a well-formed body still counts all points (proves the
        # malformed probes below hit a healthy endpoint, not a broken one)
        s0, b0, raw0 = safe_request("POST", f"/collections/{coll}/points/count",
                                    json={}, timeout=60)
        if s0 == -1:
            transport_dead("control well-formed count")
            return
        ctrl = None
        if s0 == 200 and isinstance(b0, dict) and isinstance(b0.get("result"), dict):
            ctrl = b0["result"].get("count")
        if ctrl != N_SEED:
            print(f"control count = {ctrl}, expected {N_SEED} — endpoint unhealthy "
                  f"for probing, no defect conclusion")
            print("VERDICT: SCRIPT_ERROR — control face mismatch")
            return
        print(f"control: well-formed count == {N_SEED} (endpoint healthy)")

        # ---- F1: truncated JSON ----
        s, count, raw = run_probe(PROBE_TRUNCATED, "F1 truncated JSON body")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F1: "
                      f"truncated JSON crashed the count face with {s}: "
                      f"{raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F1 5xx and healthz down")
            return
        if 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F1: RFC-invalid "
                  f"truncated JSON stream accepted with {s} (count={count}): "
                  f"{raw[:300]}")
            return
        print(f"F1: rejected with {s} (clean)")

        # ---- F2: trailing comma ----
        s, count, raw = run_probe(PROBE_TRAILING_COMMA, "F2 trailing-comma JSON body")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F2: "
                      f"trailing-comma JSON crashed the count face with {s}: "
                      f"{raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F2 5xx and healthz down")
            return
        if 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F2: RFC-invalid "
                  f"trailing comma accepted with {s} (count={count}): "
                  f"{raw[:300]}")
            return
        print(f"F2: rejected with {s} (clean)")

        # ---- F3: raw NUL byte inside a JSON string key ----
        s, count, raw = run_probe(PROBE_RAW_NUL_KEY, "F3 raw NUL byte in JSON key")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F3: raw NUL "
                      f"in a JSON string crashed the count face with {s}: "
                      f"{raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F3 5xx and healthz down")
            return
        if 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F3: raw NUL "
                  f"control char (must be escaped per RFC 8259) accepted with "
                  f"{s} (count={count}): {raw[:300]}")
            return
        print(f"F3: rejected with {s} (clean)")

        # ---- F4: VALID JSON, escaped NUL inside a match value ----
        s, count, raw = run_probe(PROBE_ESCAPED_NUL_VALUE,
                                  "F4 escaped \\u0000 in match value (valid JSON, "
                                  "unseeded value)")
        if s is None:
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F4: escaped-"
                      f"NUL value crashed the count face with {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F4 5xx and healthz down")
            return
        if 200 <= s <= 299:
            if not (isinstance(count, int) and not isinstance(count, bool)):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F4: "
                      f"result.count not an integer: {raw[:300]}")
                return
            if count == 0:
                print("F4: 200 with count == 0 (legal JSON, unsatisfiable value)")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F4: "
                      f"no seeded point carries 'ber\\u0000lin', the exact count "
                      f"must be 0, got {count}: {raw[:300]}")
                return
        else:
            print(f"F4: rejected with {s} (clean rejection of escaped NUL in a "
                  f"value — defensible)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
