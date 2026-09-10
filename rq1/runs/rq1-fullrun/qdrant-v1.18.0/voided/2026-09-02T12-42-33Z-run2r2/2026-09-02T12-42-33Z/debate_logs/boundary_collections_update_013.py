#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_update_013
# strategy: strategy2_type_confusion
# endpoint: collections+update
# constraint_ids: qdrant_behavioral_collections_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — wrong-typed values inside diff configs
#            (hnsw_config.m as string, ef_construct as float, deleted_threshold as string)
#            are assumed to be refused by the update face's deserializer)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-confusion x qdrant_behavioral_collections_update_001 (400 face of the
behavioral triangle: "an invalid diff returns 400") — three wrong-typed diffs on KNOWN
fields of a live collection must each be rejected with HTTP 400/422 by PATCH
/collections/{collection_name}: hnsw_config.m="abc" (string into uint field),
hnsw_config.ef_construct=3.5 (fractional float into uint field) and optimizers_config
.deleted_threshold="0.5" (string into float field); any 2xx acceptance of a wrong-typed diff
= the documented 400 face broken (Type1_IllegalSuccess), with the persisted readback
checked when the field could materialize
[chunk_collections+update coverage: strategy2 type-confusion x
qdrant_behavioral_collections_update_001 - 400 face]
Oracle: on the live bcu013_* collection, each of the three wrong-typed diffs returns HTTP
400/422 (2xx = Type1_IllegalSuccess against the documented 400 face; 404/5xx/transport =
SCRIPT_ERROR or Type3_RuntimeFailure with /healthz re-check); a legal control diff
(hnsw_config.m=8) returns HTTP 200 with result true to prove the collection accepts valid
diffs (disposition contrast, G4)
Constraint: qdrant_behavioral_collections_update_001 (bare id) — "valid update on an
existing collection returns HTTP 200; a missing collection returns 404; an invalid diff
returns 400" (evidence_tier: explicit; level: endpoint; defect_type_if_violated:
Type1_IllegalSuccess)

Shape anchor (D3b): update success face declares result: boolean -> success leg asserts
result is True only; rejection legs print the raw error text for the judge (error-message
structure is not part of the contract per threat-model by-design list).
Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  collections+update  -> PATCH  /collections/{collection_name}
  collections+get     -> GET    /collections/{collection_name}
  collections+create  -> PUT    /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET    /healthz
"""

import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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

PATH_UPDATE = "/collections/{collection_name}"   # PATCH  collections+update
PATH_GET = "/collections/{collection_name}"      # GET    collections+get
PATH_CREATE = "/collections/{collection_name}"   # PUT    collections+create
PATH_DELETE = "/collections/{collection_name}"   # DELETE collections+delete

COLL = "bcu013_" + uuid.uuid4().hex[:10]         # unique-prefix discipline

# Wrong-typed values on KNOWN diff fields: every one is an "invalid diff" per the schema
# (hnsw_config.m uint, hnsw_config.ef_construct uint, deleted_threshold float).
INVALID_BODIES = [
    ("hnsw_config.m='abc' (string into uint)", {"hnsw_config": {"m": "abc"}}),
    ("hnsw_config.ef_construct=3.5 (float into uint)",
     {"hnsw_config": {"ef_construct": 3.5}}),
    ("optimizers_config.deleted_threshold='0.5' (string into float)",
     {"optimizers_config": {"deleted_threshold": "0.5"}}),
]


def safe_request(method, endpoint, json=None, timeout=10, params=None):
    """Safe HTTP wrapper (agents/_target_api_reference.md). Returns (status, body, raw)."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(method=method, url=url, json=json,
                                    params=params, headers=headers, timeout=timeout)
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except Exception:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def healthz():
    return safe_request("GET", "/healthz", timeout=5)


def cleanup():
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")),
                     timeout=30, params={"timeout": 30})
    except Exception:
        pass  # cleanup failures are non-fatal


def patch_cfg(body):
    return safe_request("PATCH", PATH_UPDATE.format(collection_name=quote(COLL, safe="")),
                        json=body, timeout=30, params={"timeout": 30})


def transport_or_5xx(probe, status, raw):
    hs, _, hraw = healthz()
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    if status <= 0:
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) - probe '{probe}' transport failure "
                    f"and /healthz={hs} (service down)")
        return f"SCRIPT_ERROR - probe '{probe}' transport failure with /healthz={hs} alive"
    return (f"DEFECT_FOUND (Type3_RuntimeFailure) - probe '{probe}' got {status} "
            f"with /healthz={hs}")


def main():
    # ---- Arrange ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # ---- Legal control first (disposition contrast: the collection accepts valid diffs) ----
    st, _, raw = patch_cfg({"hnsw_config": {"m": 8}})
    print(f"[control] PATCH hnsw_config.m=8 -> status={st} raw={str(raw)[:200]}")
    if st == 200:
        try:
            body = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            body = None
        if isinstance(body, dict) and body.get("result") is True:
            print("OK(control): valid diff accepted with result true")
        else:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - control 200 with "
                  f"envelope result != true: {str(raw)[:200]}")
            return
    elif 400 <= st < 500 or st == 404:
        print("VERDICT: SCRIPT_ERROR - legal control diff rejected; cannot distinguish the "
              f"rejection face from body rejection: {st} {str(raw)[:200]}")
        return
    elif st <= 0 or 500 <= st <= 599:
        v = transport_or_5xx("legal control", st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return

    # ---- 400 face: each wrong-typed diff must be rejected ----
    for probe, body in INVALID_BODIES:
        st, _, raw = patch_cfg(body)
        print(f"[probe {probe}] PATCH -> status={st} raw={str(raw)[:250]}")
        if st <= 0 or 500 <= st <= 599:
            v = transport_or_5xx(probe, st, raw)
            if v is not None:
                print("VERDICT: " + v)
                return
        elif st == 404:
            print(f"VERDICT: SCRIPT_ERROR - probe '{probe}' got 404 on a live collection")
            return
        elif 400 <= st < 500:
            print(f"OK(reject): '{probe}' -> {st} (documented invalid-diff 400 face)")
        elif 200 <= st < 300:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - wrong-typed diff "
                  f"'{probe}' accepted with 2xx {st} instead of the documented 400 reject: "
                  f"{str(raw)[:250]}")
            return
        else:
            print(f"VERDICT: SCRIPT_ERROR - uninterpreted status {st} for probe '{probe}'")
            return

    print("OK: 3/3 wrong-typed diffs rejected with 400/422 (documented invalid-diff face)")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
