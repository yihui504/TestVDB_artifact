#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_get_001
# strategy: strategy1_behavioral_positive
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 behavioral-positive x qdrant_behavioral_collections_get_001 (G4 positive branch + response-shape closure + config round-trip fidelity: existing collection -> HTTP 200 with FULL resolved config params/hnsw_config/optimizer_config/wal_config(+quantization_config key), result.status in {green,yellow,red}, points_count/indexed_vectors_count integer-or-null, segments_count integer, and explicitly-set non-default values echoed back by the describe face)
Oracle: after PUT-create of a b1cget_* collection with vectors size=4 distance=Cosine, on_disk_payload=false, hnsw_config m=32 ef_construct=256, optimizer_config indexing_threshold=50000, wal_config wal_capacity_mb=64 wal_segments_ahead=2, GET describe returns HTTP 200 where result is a dict, result.status is one of green|yellow|red, result.points_count and result.indexed_vectors_count are int-or-None, result.segments_count is int, result.config.params/.hnsw_config/.optimizer_config/.wal_config are dicts, quantization_config key present, and each explicitly-set value is echoed exactly (fidelity); a 404 = Type1_IllegalRejection, other non-200 4xx = Type4_StateLogicViolation, 5xx = Type3_RuntimeFailure, missing/mistyped shape members or a fidelity mismatch = Type4_StateLogicViolation

Constraint (bare id): qdrant_behavioral_collections_get_001
  description: "returns 200 with full config (params, hnsw_config,
  optimizer_config, wal_config, quantization_config), status
  (green|yellow|red), points_count, indexed_vectors_counts"
  evidence_tier: explicit; level: endpoint; defect_type_if_violated:
  Type1_IllegalSuccess (the 200-for-missing face is covered by sibling script
  _002; this script attacks the positive face: full-config completeness and
  fidelity of the resolved config).

Shape anchor (D3b rule 2 - spec-derived response_shape wins over paraphrase):
  contract api_endpoints['collections+get'].response_shape declares
  result: object; result.status: string; result.points_count and
  result.indexed_vectors_count: [integer, null]; result.segments_count:
  integer; result.config: object with params/hnsw_config/optimizer_config/
  wal_config sub-objects and typed leaves (hnsw_config.m: integer,
  optimizer_config.indexing_threshold: [integer,null], wal_config any with
  wal_capacity_mb: integer, params.on_disk_payload: [boolean,null]).
  R5 exists-shape lesson applied: adjudication keys off the declared envelope
  result.<field>, never a bare top-level value.

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
COLL = f"b1cget_pos_{TS}"

# Explicitly NON-default config so the describe face must echo resolved
# values, not merely defaults (default m=16/ef_construct=100/
# indexing_threshold=20000/wal_capacity_mb=32; on_disk_payload runtime
# default true in v1.18.0 standalone per contract param description).
CREATE_BODY = {
    "vectors": {"size": 4, "distance": "Cosine"},
    "on_disk_payload": False,
    "hnsw_config": {"m": 32, "ef_construct": 256},
    "optimizer_config": {"indexing_threshold": 50000},
    "wal_config": {"wal_capacity_mb": 64, "wal_segments_ahead": 2},
}


def cleanup():
    """Teardown: best-effort delete of the collection WE created; failure is non-fatal."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")), timeout=15)
    except Exception:
        pass


def main():
    # ---- Arrange: create the collection with explicit non-default config ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json=CREATE_BODY, timeout=30)
    print(f"setup create {COLL}: status={st}")
    print(f"setup raw: {raw[:300]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on setup (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure in setup, no defect conclusion")
        return
    if st not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR - setup failed creating {COLL}: {st} {raw[:300]}")
        return

    # ---- Act: describe the just-created collection ----
    st, body, raw = safe_request("GET", PATH_GET.format(collection_name=quote(COLL, safe="")), timeout=30)
    print(f"GET describe on {COLL} -> status={st}")
    print(f"raw: {raw[:900]}")

    # ---- Assert (declare expectation first, then compare) ----
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on describe probe (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - describe on an existing "
              f"collection returned server error {st}")
        return
    if st == 404:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) - describe on the existing "
              f"collection {COLL} returned 404; assertion requires HTTP 200 with full config")
        return
    if not (200 <= st <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - expected HTTP 200 for "
              f"an existing collection, got {st}")
        return

    # 200 branch: shape closure per contract response_shape
    if not isinstance(body, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - response body is not a "
              f"JSON object: {raw[:300]}")
        return
    result = body.get("result")
    if not isinstance(result, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result is not an object: "
              f"got {type(result).__name__}: {raw[:300]}")
        return

    # result.status: green|yellow|red (assertion description)
    rstatus = result.get("status")
    if rstatus not in ("green", "yellow", "red"):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.status must be one "
              f"of green|yellow|red, got {rstatus!r}: {raw[:300]}")
        return

    # typed nullable counters (response_shape: [integer, null])
    for k in ("points_count", "indexed_vectors_count"):
        v = result.get(k, "<missing>")
        if v == "<missing>":
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.{k} missing "
                  f"from describe response: {raw[:300]}")
            return
        if v is not None and not isinstance(v, int):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.{k} must be "
                  f"integer-or-null, got {type(v).__name__}={v!r}: {raw[:300]}")
            return
    seg = result.get("segments_count", "<missing>")
    if seg == "<missing>" or not isinstance(seg, int):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.segments_count "
              f"must be an integer, got {seg!r}: {raw[:300]}")
        return

    # full config: four sub-objects must be dicts; quantization_config key present
    config = result.get("config")
    if not isinstance(config, dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - result.config is not an "
              f"object: {raw[:300]}")
        return
    for sub in ("params", "hnsw_config", "optimizer_config", "wal_config"):
        if not isinstance(config.get(sub), dict):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - assertion requires "
                  f"full config but result.config.{sub} is not an object: {raw[:300]}")
            return
    if "quantization_config" not in config:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - assertion lists "
              f"quantization_config among returned config blocks but the key is absent: "
              f"{raw[:300]}")
        return

    # ---- fidelity: explicitly-set non-default values must be echoed exactly ----
    params = config["params"]
    vec_ser = json.dumps(params.get("vectors"))
    if not ("4" in vec_ser and "Cosine" in vec_ser):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - created vectors "
              f"size=4/Cosine but describe reports {vec_ser[:200]}")
        return
    fidelity_checks = [
        ("params.on_disk_payload", params.get("on_disk_payload", "<missing>"), False),
        ("hnsw_config.m", config["hnsw_config"].get("m", "<missing>"), 32),
        ("hnsw_config.ef_construct", config["hnsw_config"].get("ef_construct", "<missing>"), 256),
        ("optimizer_config.indexing_threshold",
         config["optimizer_config"].get("indexing_threshold", "<missing>"), 50000),
        ("wal_config.wal_capacity_mb", config["wal_config"].get("wal_capacity_mb", "<missing>"), 64),
        ("wal_config.wal_segments_ahead", config["wal_config"].get("wal_segments_ahead", "<missing>"), 2),
    ]
    for label, got, want in fidelity_checks:
        if got != want:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - config fidelity "
                  f"violation on {label}: created with {want!r} but describe reports {got!r} "
                  f"(describe must return the RESOLVED config, not stale/other values)")
            return

    print("OK: existing collection -> 200 with full resolved config; all six explicitly-set "
          "non-default values echoed; status/counter shape conforms")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
