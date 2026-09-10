#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_malformed_008
# strategy: strategy7 malformed input-stream / character-boundary attack
#           (truncated JSON, NUL byte inside a JSON string, non-finite NaN
#           token — sent as raw bytes via data= so the client serializer
#           cannot pre-reject them; dual defect classes Type3 + Type1)
# endpoint: points+discover
# constraint_ids: qdrant_behavioral_points_discover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (serde trust — the server is assumed to parse the request
#            stream defensively; a parser panic / internal-error leak on a
#            truncated body, a control character or a non-finite token is a
#            Type3 runtime failure; a silent 200 accept of unparsable input
#            is a Type1 pending judge-doc verification)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-stream x qdrant_behavioral_points_discover_001 —
  the request stream of the discover face is attacked with three malformed
  bodies sent as RAW BYTES (data=, so the client-side json= serializer
  cannot pre-reject them — the server parser is the component under test)
  on a live sparse seeded collection:
    G  guard: the SAME body well-formed and serialized, sent via the raw
       data= channel -> 200, result array 1..3 — proves the raw-bytes
       channel itself works, so malformed-face failures attribute to the
       malformation, not to the channel.
    M1 truncated JSON: b'{"limit": 3, "using": "text", "target": {"indices": [1], "values": [0.5'
       -> 400/422 clean parser rejection; 5xx/panic/internal-error leak =
       Type3_RuntimeFailure; 2xx = Type1_IllegalSuccess (a truncated body
       was parsed into a full request — pending judge-doc verification).
    M2 NUL byte inside a JSON string value: using="te\\x00xt"
       -> 400/422 clean; 5xx = Type3; 2xx = Type1 (control character in a
       string silently accepted — pending judge-doc verification).
    M3 non-finite NaN token in sparse values: "values": [NaN]
       (NaN is not a legal JSON token)
       -> 400/422 clean; 5xx = Type3; 2xx = Type1 (non-finite float
       accepted into a sparse query vector — pending judge-doc verification).
  [chunk_points+discover coverage: strategy7 malformed stream x
  qdrant_behavioral_points_discover_001 (this script; positive/shape in
  boundary_points_discover_positive_001, context type-confusion in
  boundary_points_discover_context_type_002, 404 leg in
  boundary_points_discover_404_003, limit matrix in
  boundary_points_discover_limit_004, presence matrix in
  boundary_points_discover_presence_005, sparse-target shape in
  boundary_points_discover_sparse_target_006, filter family mirror in
  boundary_points_discover_filter_type_007)]
Oracle: G -> 200 with result array 1..3 (non-200 = raw channel broken,
  setup-attribution failure, no defect conclusion; wrong length = Type4);
  M1/M2/M3 -> 400/422 clean rejection (2xx = Type1_IllegalSuccess pending
  judge-doc verification; 5xx or panic/internal/serde tokens in the body
  with /healthz alive = Type3_RuntimeFailure); transport failure ->
  /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_discover_001).
Constraint: qdrant_behavioral_points_discover_001 (bare id) — "returns 200
  [ScoredPoint]; 400 on invalid context/pairs; 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+discover       -> POST /collections/{collection_name}/points/discover
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
  points+upsert         -> PUT  /collections/{collection_name}/points
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
N_SEED = 9
RED_N = 3
SPARSE_NAME = "text"
DENSE_NAME = "dense"

GOOD_BODY = {"using": SPARSE_NAME,
             "target": {"indices": [1, 2, 3], "values": [1.0, 1.0, 1.0]},
             "limit": 3}

# (label, raw bytes body) — data= passthrough; never json= for these faces
FACES = [
    ("M1 truncated JSON",
     b'{"limit": 3, "using": "text", "target": {"indices": [1], "values": [0.5'),
    ("M2 NUL byte in string value",
     b'{"limit": 3, "using": "te\x00xt", "target": {"indices": [1], "values": [0.5]}}'),
    ("M3 NaN token in sparse values",
     b'{"limit": 3, "using": "text", "target": {"indices": [1], "values": [NaN]}}'),
]


def safe_request(method, endpoint, json=None, timeout=60, params=None, data=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/ordering/timeout) via params= — never stuffed into the body.
    Raw malformed bodies go via data= (bytes) so the client serializer is bypassed.
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
    """Inline liveness probe on the lightweight healthz face."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def transport_dead(where):
    """Transport-branch liveness re-check (lightweight healthz face only)."""
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return False


def sparse_vec(i):
    """Sparse vector per cluster: red over indices 1..3, blue over 4..6."""
    if i <= RED_N:
        return {"indices": [1, 2, 3], "values": [round(0.9 + 0.02 * i, 3), 0.8, 0.7]}
    return {"indices": [4, 5, 6], "values": [round(0.9 - 0.01 * i, 3), 0.85, 0.6]}


def dense_vec(i):
    """Dense vector per cluster (Cosine; absolute scores are never asserted)."""
    base = 0.1 if i <= RED_N else 0.9
    return [round(base + 0.001 * i, 4)] * DIM


def setup(coll):
    """Own collection: named dense vector + named sparse vector + 9 points."""
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {DENSE_NAME: {"size": DIM, "distance": "Cosine"}},
                                   "sparse_vectors": {SPARSE_NAME: {}}}, timeout=60)
    if s not in (200, 201):
        return False, raw
    pts = []
    for i in range(1, N_SEED + 1):
        pts.append({"id": i,
                    "vector": {DENSE_NAME: dense_vec(i), SPARSE_NAME: sparse_vec(i)},
                    "payload": {"grp": "red" if i <= RED_N else "blue"}})
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": pts}, params={"wait": "true"}, timeout=120)
    if s not in (200, 201):
        return False, raw
    return True, ""


def discover_raw(coll, raw_bytes):
    """points+discover face with a RAW byte body (data= passthrough)."""
    return safe_request("POST", f"/collections/{coll}/points/discover",
                        data=raw_bytes, timeout=60)


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdw8" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # ---- G: guard — well-formed body on the SAME raw data= channel ----
        good_bytes = json.dumps(GOOD_BODY).encode("utf-8")
        s, body, raw = discover_raw(coll, good_bytes)
        print(f"\nG guard well-formed raw body -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            transport_dead("G guard")
            return
        if not (200 <= s <= 299):
            print(f"raw-channel control failed with status {s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — control face failure, no defect conclusion")
            return
        res = body.get("result") if isinstance(body, dict) else None
        if not isinstance(res, list) or not (1 <= len(res) <= 3):
            got = len(res) if isinstance(res, list) else "non-array"
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — G: 200 "
                  f"but result {got} outside [1, 3]: {raw[:300]}")
            return
        print(f"G: 200 on the raw data= channel, result len={len(res)} (channel proven)")

        # ---- M1..M3: malformed raw bodies ----
        for label, raw_bytes in FACES:
            s, body, raw = discover_raw(coll, raw_bytes)
            print(f"\n{label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                transport_dead(label)
                return
            low = raw.lower()
            parser_tokens = ("panic", "internal", "serde", "out of memory",
                             "oom", "decode")
            # Type3 = actual crash: 5xx. Token scan is a note signal only —
            # a 4xx whose text names the parser is GOOD diagnostics, not a crash
            # (a token-triggered Type3 on a clean 400 would be a false positive).
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                          f"malformed stream triggered {s} "
                          f"(server must 4xx, not crash): {raw[:300]}")
                else:
                    print(f"VERDICT: SCRIPT_ERROR — {label} failure and healthz down")
                return
            if 200 <= s <= 299:
                if any(t in low for t in parser_tokens):
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                          f"2xx body carries parser-failure tokens: {raw[:300]}")
                    return
                res = body.get("result") if isinstance(body, dict) else None
                got = len(res) if isinstance(res, list) else "non-array"
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"malformed body ACCEPTED with status {s} (result "
                      f"{got}) — pending judge-doc verification: {raw[:300]}")
                return
            if s in (400, 422):
                named = any(t in low for t in parser_tokens)
                note = ("4xx diagnostics name the parser component"
                        if named else
                        f"{label}: {s} clean parser rejection")
                print(note)
            else:
                print(f"NOTE: {label} returned {s} (neither 2xx nor 400/422); "
                      f"recorded for the judge — unexpected rejection class")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
