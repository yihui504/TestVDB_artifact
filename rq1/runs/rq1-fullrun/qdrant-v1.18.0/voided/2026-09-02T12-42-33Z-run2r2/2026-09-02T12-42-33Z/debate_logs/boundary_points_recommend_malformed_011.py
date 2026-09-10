#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_recommend_malformed_011
# strategy: strategy7 malformed input / character fuzzing — the recommend
#           face's request STREAM attacked with raw bytes (data= channel so
#           the client-side json= serializer cannot pre-reject them; the
#           server parser is the component under test)
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde trusts the
#            incoming stream is legal JSON encoding legal Unicode; the
#            3 prior TPs of this class (malformed JSON + NUL/UTF-16)
#            were invisible to value-level strategies)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-stream x qdrant_behavioral_points_recommend_001 —
  the request stream of the recommend face is attacked with four malformed
  bodies sent as RAW BYTES (data=, so the client-side json= serializer
  cannot pre-reject them) on a live seeded collection (12 points, dim 4,
  Euclid, binary-exact — R27):
    G  guard: the SAME body well-formed and serialized, sent via the raw
       data= channel -> 200, result array 1..3 — proves the raw-bytes
       channel itself works, so malformed-face failures attribute to the
       malformation, not to the channel.
    M1 truncated JSON: b'{"positive": [1], "limit": 3'
       -> 400/422 clean parser rejection; 5xx/panic/internal-error leak =
       Type3_RuntimeFailure; 2xx = Type1_IllegalSuccess (a truncated body
       parsed into a full request — pending judge-doc verification).
    M2 bare NUL byte inside a JSON string value: using="te\\x00xt"
       (raw 0x00, not the legal \\u0000 escape — control characters are
       not allowed unescaped in JSON strings)
       -> 400/422 clean; 5xx = Type3; 2xx = Type1 pending judge-doc.
    M3 non-finite NaN token in a raw vector example:
       b'{"positive": [[0.5, NaN, 0.125, 0.0625]], "limit": 3}'
       (NaN is not a legal JSON token)
       -> 400/422 clean; 5xx = Type3; 2xx = Type1 pending judge-doc.
    M4 UTF-16 lone surrogate escape in a string value: using="\\ud800"
       (a legal JSON escape that decodes to a lone surrogate — not a
       legal Unicode scalar)
       -> 400/422 clean; 5xx = Type3; 2xx = Type1 pending judge-doc.
  [chunk_points+recommend coverage (11 scripts): strategy1 limit boundary
  matrix x qdrant_range_points_recommend_001 (limit_001); strategy1 offset
  boundary matrix + huge-offset x qdrant_range_points_recommend_001
  (offset_002); behavioral positive core by-id/by-vector/strategy-enum
  closure x qdrant_behavioral_points_recommend_001 (positive_003); BS-10
  missing referenced point ids 400-legs x qdrant_behavioral_points_
  recommend_001 (missing_ref_004); using-vector characteristics mismatch
  (lookup dim + named partial) x qdrant_behavioral_points_recommend_001
  (using_mismatch_005); 404 status-mapping legs x qdrant_behavioral_
  points_recommend_001 (404_006); strategy2 RecommendExample oneOf element
  type-confusion + raw-vector dimension x qdrant_behavioral_points_
  recommend_001 (example_type_007); R33/R40 dual-key silent-drop family on
  mixed recommend examples x qdrant_behavioral_points_recommend_001
  (dualkey_008); strategy2 filter type-confusion family mirror x
  qdrant_behavioral_points_recommend_001 (filter_type_009); strategy6
  conservative single-extreme + modest-product resource x
  qdrant_range_points_recommend_001 (resource_010); strategy7 malformed
  raw-byte stream x qdrant_behavioral_points_recommend_001 (this
  script)]
Oracle: G -> 200 with result array 1..3 (non-200 = raw channel broken,
  setup-attribution failure, no defect conclusion); M1..M4 -> 400/422
  clean rejection (2xx = Type1_IllegalSuccess pending judge-doc
  verification — a malformed stream silently accepted; 5xx or panic/
  internal/serde/utf/decode tokens in the body with /healthz alive =
  Type3_RuntimeFailure); transport failure -> /healthz liveness re-check
  then SCRIPT_ERROR (constraint qdrant_behavioral_points_recommend_001).
Constraint: qdrant_behavioral_points_recommend_001 (bare id) — "returns
  200 [ScoredPoint]; 400 when a positive/negative references a point
  without the used vector or a missing point (fetched vectors must match
  the using-vector characteristics); 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+recommend      -> POST /collections/{collection_name}/points/recommend
  points+upsert         -> PUT  /collections/{collection_name}/points
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
  healthz               -> GET  /healthz
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
V = [0.5, 0.25, 0.125, 0.0625]


def safe_request(method, endpoint, json=None, timeout=60, params=None, data=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    data= accepts raw bytes so malformed streams bypass client serialization.
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, data=data, headers=headers,
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


def extract_scored(body):
    """Contract response_shape: result is a top-level array of ScoredPoints."""
    if not isinstance(body, dict):
        return None, "body-not-dict"
    result = body.get("result")
    if isinstance(result, list):
        return result, "result-array"
    return None, "result-missing-or-not-array"


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bprX11" + tag

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{"id": i, "vector": [v * (1.0 + i / 100.0) for v in V]} for i in range(1, N_SEED + 1)]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        endpoint = f"/collections/{coll}/points/recommend"

        # ---- Leg G: raw-channel guard (same body, well-formed, data=) ----
        good = json.dumps({"positive": [1], "limit": 3, "params": {"exact": True}}).encode("utf-8")
        s, b, raw = safe_request("POST", endpoint, data=good, timeout=60)
        print(f"\nleg G raw-channel guard -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1 or 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if s == -1:
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive
                      else "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            elif alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [G]: {s} with "
                      f"service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        scored, shape = extract_scored(b)
        if s != 200 or scored is None or not (1 <= len(scored) <= 3):
            print(f"VERDICT: SCRIPT_ERROR — raw channel broken ({s}, {shape}); malformed legs "
                  f"unattributable")
            return
        print("leg G OK: raw-bytes channel works")

        # ---- Legs M1..M4: malformed raw-byte streams ----
        m_legs = (
            ("M1 truncated JSON", b'{"positive": [1], "limit": 3'),
            ("M2 bare NUL in string value", b'{"positive": [1], "limit": 3, "using": "te\x00xt"}'),
            ("M3 NaN token in vector", b'{"positive": [[0.5, NaN, 0.125, 0.0625]], "limit": 3}'),
            ("M4 lone surrogate escape", json.dumps({"positive": [1], "limit": 3,
                                                     "using": "\ud800"}).encode("utf-8")),
        )
        for label, payload in m_legs:
            s, b, raw = safe_request("POST", endpoint, data=payload, timeout=60)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, _, _ = healthz_alive()
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                      "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
                return
            low = raw.lower()
            leak_tokens = [k for k in ("panic", "internal", "serde", "utf", "decode")
                           if k in low]
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: "
                          f"malformed input produced {s} with service alive"
                          + (f" (leak tokens {leak_tokens})" if leak_tokens else "")
                          + f": {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if 200 <= s <= 299:
                scored, shape = extract_scored(b)
                n = len(scored) if scored is not None else -1
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: malformed "
                      f"stream silently ACCEPTED with {s} ({n} points returned) — pending "
                      f"judge-doc verification: {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return
            print(f"leg {label} OK: rejected with {s} (parser leak tokens: {leak_tokens})")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
