#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_get_005
# strategy: strategy7_malformed_input
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-input x qdrant_behavioral_collections_get_001 (path-parameter malformation on the describe face: NUL byte %00, encoded slash %2F inside the name, invalid percent-sequence %zz, UTF-8 lone-surrogate %ED%A0%80, dot-segments . / .. — every probe is a NEVER-CREATED name, so the describe face owes 404 (or a clean 400 for unparseable input), never 5xx and never 200-with-config)
Oracle: for each malformed path probe, HTTP 404 or 400/422 = clean (unknown name or explicit parse rejection); HTTP 2xx = Type1_IllegalSuccess (config served for a nonexistent/malformed name - the assertion's 'never 200 with config'); HTTP 5xx = Type3_RuntimeFailure (parser/routing crash on malformed input); any other 3xx/4xx channel = Type4_StateLogicViolation; dot-segment probes (., ..) additionally tolerate HTTP 200 of a NON-describe shape (routing may normalize to the list face - out of this assertion's scope) but still fail on 5xx or on a 200 whose body is a describe envelope (result dict with a config object)
Constraint (bare id): qdrant_behavioral_collections_get_001
  expected_behavior: "missing collection: HTTP 404 with an error message,
  never 200 with config"
  evidence_tier: explicit; level: endpoint; defect_type_if_violated:
  Type1_IllegalSuccess.
Strategy-7 general dimensions applied DB-neutrally to the URL path parameter
(the only user-input channel of the GET describe face; there is no body to
malform): NUL bytes, invalid percent-escapes, encoded path separators, invalid
UTF-8 (lone surrogate), dot-segments. Client-side discipline: probes are
pre-encoded and sent via safe_request on the raw path so no client serializer
can sanitize them first (the data= lesson adapted to the path channel).

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  collections+get -> GET /collections/{collection_name}
  healthz         -> GET /healthz
"""

import json
import os
import sys
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    _root = Path(__file__).resolve()
    for _p in (_root, *_root.parents):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or TARGET != "qdrant":
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)

# URL registry - verbatim from raw_knowledge.json api_endpoints[].url
PATH_GET = "/collections/{collection_name}"   # collections+get

# Malformed path probes, ALREADY percent-encoded (sent as raw path text).
# None of these names was ever created -> the face owes 404/400, never 200/5xx.
PROBES = [
    ("nul_byte",          "b5cget_mf_%00nul"),          # NUL inside the name
    ("encoded_slash",     "b5cget_mf_a%2Fb"),           # '/' smuggled via %2F
    ("invalid_pct_seq",   "b5cget_mf_%zzgarbage"),      # not a legal escape
    ("lone_surrogate",    "b5cget_mf_%ED%A0%80sur"),    # invalid UTF-8 (surrogate half)
    ("dot_segment_self",  "."),                          # /collections/.
    ("dot_segment_parent", ".."),                        # /collections/..
]


def looks_like_describe_envelope(body):
    """A describe-shaped 200: envelope dict with result dict carrying config."""
    return (isinstance(body, dict) and isinstance(body.get("result"), dict)
            and isinstance(body["result"].get("config"), dict))


def main():
    for label, seg in PROBES:
        print(f"--- probe [{label}]: GET /collections/{seg} ---")
        st, body, raw = safe_request("GET", PATH_GET.format(collection_name=seg), timeout=30)
        print(f"status={st}")
        print(f"raw: {raw[:300]}")

        if st == -1:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"transport failure on probe (healthz status={hs}: {hraw[:200]})")
            print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
            return
        if 500 <= st <= 599:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - malformed path "
                  f"[{label}] triggered server error {st}: {raw[:300]}")
            return
        if st in (404, 400, 422):
            print(f"OK: [{label}] cleanly handled with {st}")
            continue
        if 200 <= st <= 299:
            if label.startswith("dot_segment"):
                if looks_like_describe_envelope(body):
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - dot-segment "
                          f"[{label}] returned a DESCRIBE envelope 200 for a nonexistent "
                          f"collection: {raw[:300]}")
                    return
                print(f"OK: [{label}] 200 of a non-describe shape (routing "
                      f"normalization; observation only, not this face)")
                continue
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - malformed "
                  f"never-created name [{label}] returned HTTP {st} "
                  f"(config served for a nonexistent collection: {raw[:300]})")
            return
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - unexpected "
              f"channel {st} for malformed unknown name [{label}]: {raw[:300]}")
        return

    print("OK: all malformed path probes handled cleanly (404/400/422 or "
          "non-describe 200 for dot-segments; never 5xx, never describe-200)")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
