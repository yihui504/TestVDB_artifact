#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_groups_malformed_001
# strategy: strategy7 malformed-input / character-boundary attack on the
#           request stream of the grouped query face (raw-bytes legs sent
#           via data= so the CLIENT serializer cannot pre-reject them —
#           what is measured is the server's parser, not json.dumps)
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — parser robustness at
#            the stream level is assumed: malformed JSON, unescaped control
#            characters and lone surrogates are expected to draw a clean
#            4xx, not a 5xx/panic from deep inside serde)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed stream x qdrant_behavioral_points_query_groups_001
  — every JSON-over-HTTP face must parse-or-reject hostile input streams
  with a clean 400 (RFC 8259 conformance); the grouped query face POST
  /collections/{c}/points/query/groups is probed with raw-byte bodies on a
  3-point seeded collection (grp=a, dim 4, Euclid):
    MF1 truncated JSON   '{"query": {"nearest": [...]}, "group_by": "grp", "limit": 2'
                         (no closing brace)                 -> 400
    MF2 trailing comma   '{..., "limit": 2,}'               -> 400
    MF3 single quotes    "{'group_by': 'grp', ...}"         -> 400
    MF4 comment inject.  '{"group_by": "grp", // c\\n ...}' -> 400 (JSON has
                         no comments)                          (MF6 in table)
    MF5 lone surrogate   escape \\uD800 inside group_by      -> 400 (not
                         legal Unicode; strict parsers reject)
    MF6 bare NUL byte    raw 0x00 inside the group_by string -> 400 (RFC
                         8259: control chars must be escaped)   (MF5 in table)
  Every leg is sent with data=<bytes> + explicit Content-Type so the
  client library performs NO validation of its own.
  [chunk_points+query+groups coverage (8 scripts): strategy1 group_size
  boundary x range_points_query_groups_001 (groupsize_001); strategy1 limit
  boundary x range_points_query_groups_001 (limit_001); strategy6 limit x
  group_size resource combo x range_points_query_groups_001 (resource_001);
  state offset-not-allowed reject-or-omit x state_points_query_groups_001
  (offset_001); behavioral positive grouping-correctness + keyless-point
  exclusion x behavioral_points_query_groups_001 (groupby_values_001);
  strategy2 invalid group_by faces + 404 x behavioral_points_query_groups_001
  (invalid_groupby_001); strategy2 R33/R40 dual-key oneOf cross-face
  (single vs groups) x behavioral_points_query_groups_001 (dualkey_001);
  strategy7 malformed stream x behavioral_points_query_groups_001 (this
  script)]
Oracle: every leg -> a clean 400 (or 422) client rejection of the
  unparseable body; DEFECT (Type3_RuntimeFailure) on 5xx with /healthz
  alive, on panic/serde internal-error leakage in the body, or on transport
  failure with /healthz alive (parser crash signal); DEFECT
  (Type1_IllegalSuccess, pending judge-doc verification) on 200 — a server
  executing an unparseable/hostile stream means the body was never parsed
  but reported success; /healthz down = SCRIPT_ERROR; any other status =
  SCRIPT_ERROR, no defect conclusion (constraint
  qdrant_behavioral_points_query_groups_001).
Constraint: qdrant_behavioral_points_query_groups_001 (bare id) —
  "grouping requires payload values for the group_by field; returns 200
  {groups: [{id, hits}]}; 400 on an invalid group_by; 404 for a missing
  collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+groups -> POST /collections/{collection_name}/points/query/groups
  points+upsert       -> PUT  /collections/{collection_name}/points
  index+create        -> PUT  /collections/{collection_name}/index
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
  (wait is a query parameter on the upsert/index faces — passed via params=)
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
GRP = "grp"
V = [0.5, 0.25, 0.125, 0.0625]
PARSER_LEAK_MARKERS = ("panic", "serde", "rust", "backtrace", "internal error",
                       "utf-8", "decode", "deserialize")


def safe_request(method, endpoint, json=None, timeout=60, params=None, data=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/consistency) via params= — never stuffed into the body.
    Raw-byte legs use data= (client-side serialization bypassed by design).
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


def leak_text(raw):
    low = str(raw).lower()
    return next((m for m in PARSER_LEAK_MARKERS if m in low), None)


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bqgsM" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{"id": i,
                "vector": [v * (1.0 + i / 100.0) for v in V],
                "payload": {GRP: "a"}} for i in range(1, 4)]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        s_ix, _, _ = safe_request("PUT", f"/collections/{coll}/index",
                                  json={"field_name": GRP, "field_schema": {"type": "keyword"}},
                                  params={"wait": "true"}, timeout=60)
        print(f"setup payload index on '{GRP}': status={s_ix} (best-effort, non-fatal)")

        vec_json = json.dumps(V)
        groups_path = f"/collections/{coll}/points/query/groups"

        malformed_legs = (
            ("MF1 truncated JSON",
             ('{"query": {"nearest": %s}, "group_by": "%s", "limit": 2' % (vec_json, GRP)).encode("utf-8")),
            ("MF2 trailing comma",
             ('{"query": {"nearest": %s}, "group_by": "%s", "limit": 2,}' % (vec_json, GRP)).encode("utf-8")),
            ("MF3 single quotes",
             ("{'group_by': '%s', 'query': {'nearest': %s}}" % (GRP, vec_json)).encode("utf-8")),
            ("MF4 comment injection",
             ('{"group_by": "%s", // comments are not JSON\n"query": {"nearest": %s}}' % (GRP, vec_json)).encode("utf-8")),
            ("MF5 lone surrogate escape",
             ('{"group_by": "g\\uD800x", "query": {"nearest": %s}}' % vec_json).encode("utf-8")),
            ("MF6 bare NUL byte",
             ('{"group_by": "g\x00x", "query": {"nearest": %s}}' % vec_json).encode("utf-8")),
        )

        for label, payload in malformed_legs:
            s, b, raw = safe_request("POST", groups_path, data=payload, timeout=60)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: malformed "
                          f"input caused a transport failure/reset while /healthz alive "
                          f"(parser crash signal): {str(raw)[:200]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — transport failure and healthz down")
                return
            if s in (500, 502, 503, 504):
                alive, _, _ = healthz_alive()
                if alive:
                    marker = leak_text(raw)  # color only — the 5xx itself is the defect
                    detail = f"status={s}" + (f", body mentions '{marker}'" if marker else "")
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: malformed "
                          f"input drew a 5xx instead of a clean 4xx ({detail}): {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s in (400, 422):
                # Type2 observation only (R29: error quality carries no verdict weight)
                print(f"leg {label} OK: clean {s} rejection of the unparseable body")
                continue
            if s == 200:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: an "
                      f"unparseable/hostile body stream returned 200 success (pending "
                      f"judge-doc verification of stream-validation semantics): {raw[:300]}")
                return
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
