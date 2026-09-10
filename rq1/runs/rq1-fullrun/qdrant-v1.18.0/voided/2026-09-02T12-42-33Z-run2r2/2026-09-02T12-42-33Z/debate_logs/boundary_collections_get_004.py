#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_get_004
# strategy: strategy4_special_value
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust) + BS-04 (Boundary Default Optimism)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy4 special-value x qdrant_behavioral_collections_get_001 (unicode/CJK/emoji collection_name round-trip on the describe face + near-miss discrimination + G9 create/get face consistency: if the create face ACCEPTS a unicode name, the describe face must return 200 with the same collection's config for that exact name and 404 for a one-character near-miss; if the create face REJECTS the name, the describe face must not 200 it)
Oracle: PUT-create b4cget_*-name containing ü/中文/🎯 (percent-encoded via quote) -> if create=2xx then GET describe on the identical encoded name = 200 with result dict carrying result.config, and GET on the near-miss name (🎯 swapped for 🎪) = 404 exactly (no fuzzy matching); if create=4xx rejection then GET on that name must be 4xx (404 expected), never 200; describe 200 on a name create rejected = Type4_StateLogicViolation, near-miss 200 = Type1_IllegalSuccess (config for a different collection), 5xx anywhere = Type3_RuntimeFailure
Constraint (bare id): qdrant_behavioral_collections_get_001
  expected_behavior: "existing collection: HTTP 200 with resolved config;
  missing collection: HTTP 404 with an error message, never 200 with config"
  evidence_tier: explicit; level: endpoint.
Strategy-4 values (DB-neutral unicode boundary set applied to the path
parameter of the describe face): non-ASCII letters (ü), CJK (中文), emoji
(🎯 vs near-miss 🎪), underscore separators. The concern is silent mojibake or
NFD/NFC normalization divergence between the write face and the read face -
the describe face must resolve EXACTLY the name that was created.

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url;
R12 lesson - established pattern):
  collections+get    -> GET    /collections/{collection_name}
  collections+create -> PUT    /collections/{collection_name}
  collections+delete -> DELETE /collections/{collection_name}
  healthz            -> GET    /healthz
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

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
PATH_GET = "/collections/{collection_name}"            # collections+get
PATH_CREATE = "/collections/{collection_name}"         # collections+create
PATH_DELETE = "/collections/{collection_name}"         # collections+delete


def safe_request(method, endpoint, json=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md).
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, headers=headers, timeout=timeout
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


TS = int(time.time())
COLL = f"b4cget_sp_ünï_中文_🎯_{TS}"          # exact name under test
NEAR_MISS = f"b4cget_sp_ünï_中文_🎪_{TS}"     # differs in exactly one character
CREATE_BODY = {"vectors": {"size": 4, "distance": "Cosine"}}


def cleanup():
    """Teardown: best-effort delete of the collection WE created (if create accepted it)."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")), timeout=15)
    except Exception:
        pass


def main():
    enc = quote(COLL, safe="")
    enc_near = quote(NEAR_MISS, safe="")
    print(f"exact name: {COLL!r}")
    print(f"near-miss : {NEAR_MISS!r}")

    # ---- Arrange: attempt to create the unicode-named collection ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=enc),
                              json=CREATE_BODY, timeout=30)
    print(f"setup create (unicode name): status={st}")
    print(f"setup raw: {raw[:300]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on setup (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure in setup, no defect conclusion")
        return

    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - create with a unicode "
              f"name returned server error {st}: {raw[:300]}")
        return

    if not (200 <= st <= 299):
        # Leg B (G9 consistency): create rejected the name -> describe must NOT 200 it.
        print(f"create rejected the unicode name with {st} (leg B: face-consistency check)")
        st2, _, raw2 = safe_request("GET", PATH_GET.format(collection_name=enc), timeout=30)
        print(f"describe on the create-rejected name -> status={st2}")
        print(f"raw: {raw2[:300]}")
        if st2 == -1:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"transport failure on describe probe (healthz status={hs}: {hraw[:200]})")
            print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
            return
        if 500 <= st2 <= 599:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - describe on a "
                  f"create-rejected unicode name returned {st2}")
            return
        if 200 <= st2 <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - create face "
                  f"rejected '{COLL}' ({st}) but describe face returns {st2} with config "
                  f"({raw2[:300]}); the two faces disagree on the same name (G9)")
            return
        print(f"OK: create-rejected name stays rejected on the describe face ({st2})")
        print("VERDICT: NO_DEFECT")
        return

    # Leg A: create accepted -> describe must 200 the exact name...
    st, body, raw = safe_request("GET", PATH_GET.format(collection_name=enc), timeout=30)
    print(f"describe on exact unicode name -> status={st}")
    print(f"raw: {raw[:500]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on describe probe (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - describe on the existing "
              f"unicode-named collection returned {st}")
        return
    if st == 404:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation / Type1_IllegalRejection) - "
              f"create accepted '{COLL}' but describe 404s the identical encoded name "
              f"(write/read face divergence, e.g. encoding or normalization mismatch)")
        return
    if not (200 <= st <= 299) or not isinstance(body, dict) or not isinstance(body.get("result"), dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - expected 200 with a "
              f"result object for the existing unicode-named collection, got status={st} "
              f"raw={raw[:300]}")
        return
    if not isinstance(body["result"].get("config"), dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - describe result lacks "
              f"the config object for the unicode-named collection: {raw[:300]}")
        return
    print("OK: exact unicode name -> 200 with config")

    # ...and 404 the near-miss (no fuzzy matching: one different emoji = a
    # different, never-created collection)
    st, _, raw = safe_request("GET", PATH_GET.format(collection_name=enc_near), timeout=30)
    print(f"describe on near-miss name -> status={st}")
    print(f"raw: {raw[:300]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on near-miss probe (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - describe on a near-miss "
              f"unicode name returned {st}")
        return
    if 200 <= st <= 299:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - describe on the "
              f"never-created near-miss '{NEAR_MISS}' returned HTTP {st} (fuzzy/normalized "
              f"matching serving another collection's config: {raw[:300]})")
        return
    if st != 404:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - near-miss name should "
              f"404 exactly, got {st}: {raw[:300]}")
        return

    print("OK: unicode round-trip holds (exact=200+config, near-miss=404)")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
