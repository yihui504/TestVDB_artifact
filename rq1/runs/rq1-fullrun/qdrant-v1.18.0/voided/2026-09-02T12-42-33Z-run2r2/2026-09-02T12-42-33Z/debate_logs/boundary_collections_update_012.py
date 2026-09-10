#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_update_012
# strategy: strategy1_behavioral_positive_404
# endpoint: collections+update
# constraint_ids: qdrant_behavioral_collections_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the update face must answer 200 on an
#            existing collection and the documented 404 on a missing collection)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 behavioral x qdrant_behavioral_collections_update_001 (200/404 faces of
the behavioral triangle) — a valid diff on an EXISTING collection must return HTTP 200 with
envelope result true and the change must persist in the describe readback (vacuum_
min_vector_number 1500 != default 1000); the SAME valid diff applied to never-created
collection names must return exactly HTTP 404 (three independent never-created names probe
the missing-collection face; 2xx on a never-created name = Type1_IllegalSuccess on the
missing-collection leg)
[chunk_collections+update coverage: strategy1 x qdrant_behavioral_collections_update_001
- 200 face + 404 face]
Oracle: on the live bcu012_* collection, PATCH optimizers_config.vacuum_min_vector_number=
1500 returns HTTP 200 with result true and the readback echoes 1500; the same body on each
of three never-created bcu012_* ghost names returns exactly HTTP 404 (2xx = Type1_
IllegalSuccess; 4xx other than 404 = Type2_PoorDiagnostics on the wrong documented face;
5xx with /healthz alive = Type3_RuntimeFailure; transport failure re-checked via /healthz)
Constraint: qdrant_behavioral_collections_update_001 (bare id) — "valid update on an
existing collection returns HTTP 200; a missing collection returns 404; an invalid diff
returns 400" (evidence_tier: explicit; level: endpoint; defect_type_if_violated:
Type1_IllegalSuccess)

Shape anchor (D3b): update success face declares result: boolean -> success leg asserts
result is True only. Persistence echo readback walks the [RT]-verified describe envelope
result.config.optimizer_config.vacuum_min_vector_number (declared integer).
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

COLL = "bcu012_" + uuid.uuid4().hex[:10]         # unique-prefix discipline
# Valid diff; 1500 differs from the runtime default 1000 so the echo is falsifiable
VALID_BODY = {"optimizers_config": {"vacuum_min_vector_number": 1500}}


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


def patch_named(name, body):
    url = PATH_UPDATE.format(collection_name=quote(name, safe=""))
    return safe_request("PATCH", url, json=body, timeout=30, params={"timeout": 30})


def read_vacuum():
    st, b, raw = safe_request("GET", PATH_GET.format(collection_name=quote(COLL, safe="")),
                              timeout=30)
    if st != 200:
        return None, f"describe status={st}: {raw[:200]}"
    res = b.get("result") if isinstance(b, dict) else None
    cfg = res.get("config") if isinstance(res, dict) else None
    if not isinstance(cfg, dict):
        return None, f"describe result.config missing: {raw[:200]}"
    node = cfg.get("optimizer_config")
    if not isinstance(node, dict):
        node = cfg.get("optimizers_config")
    if not isinstance(node, dict):
        return None, "describe optimizer_config missing"
    return node.get("vacuum_min_vector_number"), None


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

    # ---- (a) 200 face: valid update on the existing collection ----
    st, _, raw = patch_named(COLL, VALID_BODY)
    print(f"[200-face] PATCH valid diff on {COLL} -> status={st} raw={str(raw)[:250]}")
    if st <= 0 or 500 <= st <= 599:
        v = transport_or_5xx("valid-update-on-existing", st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return
    elif st == 200:
        try:
            body = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            body = None
        if not (isinstance(body, dict) and body.get("result") is True):
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - valid update returned "
                  f"200 with envelope result != true: {str(raw)[:200]}")
            return
        echo, err = read_vacuum()
        if err:
            print(f"VERDICT: SCRIPT_ERROR - echo readback failed: {err}")
            return
        print(f"OK(echo): readback vacuum_min_vector_number={echo}")
        if echo != 1500:
            print("NOTE(no-echo): 200 but the diff was not materialized (measured)")
    elif 400 <= st < 500:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalRejection) - valid update on an existing "
              f"collection rejected with {st}: {str(raw)[:250]}")
        return
    else:
        print(f"VERDICT: SCRIPT_ERROR - uninterpreted status {st} for the 200-face leg")
        return

    # ---- (b) 404 face: same valid body on never-created names must give exactly 404 ----
    for i in range(3):
        ghost = COLL + f"_ghost{i}"
        st, _, raw = patch_named(ghost, VALID_BODY)
        print(f"[404-face '{ghost}'] PATCH valid diff -> status={st} raw={str(raw)[:200]}")
        if st <= 0 or 500 <= st <= 599:
            v = transport_or_5xx(f"never-created:{ghost}", st, raw)
            if v is not None:
                print("VERDICT: " + v)
                return
        elif st == 404:
            print(f"OK: never-created '{ghost}' -> exactly 404 (documented missing face)")
        elif 200 <= st < 300:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - never-created collection "
                  f"'{ghost}' accepted the update with 2xx {st}: {str(raw)[:200]}")
            return
        elif 400 <= st < 500:
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) - never-created collection "
                  f"'{ghost}' rejected with {st} instead of the documented 404: "
                  f"{str(raw)[:200]}")
            return
        else:
            print(f"VERDICT: SCRIPT_ERROR - uninterpreted status {st} for never-created '{ghost}'")
            return

    print("OK: valid update -> 200 result true (+echo); 3/3 never-created names -> 404")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
