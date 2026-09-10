#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_optimizations_003
# strategy: strategy1_boundary_lifecycle_flip
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the 404 face must also hold after the
#            existence boundary is crossed back by DELETE, not only for never-created names)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value / lifecycle flip x qdrant_behavioral_collections_optimizations_001
(G6 mutation: DELETE is the strongest existence-killing mutation for this readout face — it
removes the {name} resource itself, so the documented "missing collection: HTTP 404" branch
must engage immediately after the delete completes): create a b1opt3d_* collection ->
GET optimizations answers 200 (live readout) -> DELETE the collection (2xx) -> GET
optimizations on the SAME name must flip to HTTP 404. A 2xx after a confirmed delete is a
zombie optimizer-status readout (the face keeps serving a retired resource); the only
collections touched are created and deleted by this script.
Oracle: sequence create(PUT 2xx) -> GET optimizations 200 with result object -> DELETE 2xx ->
GET optimizations HTTP 404 exactly; pre-delete 404/422 on the live collection =
Type1_IllegalRejection, 5xx anywhere = Type3_RuntimeFailure, post-delete 2xx = Type4_
StateLogicViolation (stale readout survives delete), post-delete non-404 non-5xx =
Type4_StateLogicViolation; transport failures re-checked with a /healthz probe -> SCRIPT_ERROR
Constraint: qdrant_behavioral_collections_optimizations_001 (bare id) — "returns 200 with
optimizer status per shard; 404 for a missing collection" (evidence_tier: explicit; level:
endpoint; expected_behavior: "existing collection: HTTP 200 with per-shard optimizer status;
missing collection: HTTP 404"). After a confirmed DELETE the collection IS missing, so the
404 branch is the boundary closure of the same promise.

[coverage: strategy1 x qdrant_behavioral_collections_optimizations_001; unit assertions::qdrant_behavioral_collections_optimizations_001]
Shape anchor (D3b + R14 standing lesson): 200-leg envelope is judged minimally (result
object present per response_shape "result": "object"); error/404 message structure is an
implementation detail and never gated (threat-model by-design list).

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  collections+optimizations -> GET    /collections/{collection_name}/optimizations
  collections+create        -> PUT    /collections/{collection_name}
  collections+delete        -> DELETE /collections/{collection_name}
  healthz                   -> GET    /healthz
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
PATH_OPTIMIZATIONS = "/collections/{collection_name}/optimizations"   # collections+optimizations
PATH_CREATE = "/collections/{collection_name}"                        # collections+create
PATH_DELETE = "/collections/{collection_name}"                        # collections+delete


def safe_request(method, endpoint, json=None, timeout=10, data=None, params=None):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md),
    extended per R14/R15 standing lessons to forward raw bodies (data=) and query params
    (params=) exactly. Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, data=data, params=params,
            headers=headers, timeout=timeout
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


COLL = "b1opt3d_" + uuid.uuid4().hex[:10]   # unique-prefix discipline: only this script's resource


def cleanup():
    """Teardown: best-effort delete of ONLY the collection this script created."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")), timeout=30)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    # ---- Act 1: create the collection ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
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

    # ---- Act 2: live readout must answer 200 with the result envelope ----
    st, body, raw = safe_request("GET",
                                 PATH_OPTIMIZATIONS.format(collection_name=quote(COLL, safe="")),
                                 timeout=30)
    print(f"pre-delete GET optimizations on {COLL} -> status={st}")
    print(f"raw: {raw[:500]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure pre-delete (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - live readout returned server "
              f"error {st} before delete")
        return
    if not (200 <= st <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) - pre-delete optimizations on "
              f"the live collection {COLL} returned {st} (assertion: 200 with per-shard status)")
        return
    if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - pre-delete 200 response "
              f"lacks the result object envelope: {raw[:300]}")
        return

    # ---- Act 3: DELETE (the mutation) then re-probe the same name ----
    st, _, raw = safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")),
                              timeout=60)
    print(f"delete {COLL}: status={st}")
    print(f"delete raw: {raw[:300]}")
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure on delete (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure on delete, no defect conclusion")
        return
    if st not in (200, 204):
        print(f"VERDICT: SCRIPT_ERROR - DELETE of {COLL} did not confirm removal "
              f"(status {st}): {raw[:300]}")
        return

    st, body, raw = safe_request("GET",
                                 PATH_OPTIMIZATIONS.format(collection_name=quote(COLL, safe="")),
                                 timeout=30)
    print(f"post-delete GET optimizations on {COLL} -> status={st}")
    print(f"raw: {raw[:500]}")

    # ---- Assert: the documented 404 branch must engage after DELETE ----
    if st == -1:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"transport failure post-delete (healthz status={hs}: {hraw[:200]})")
        print("VERDICT: SCRIPT_ERROR - transport failure, no defect conclusion")
        return
    if st == 404:
        print(f"OK: post-delete name -> 404 (absence face honored after DELETE)")
        print("VERDICT: NO_DEFECT")
        return
    if 500 <= st <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - optimizations on the deleted "
              f"collection returned server error {st} instead of the documented 404")
        return
    if 200 <= st <= 299:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - optimizations on the "
              f"deleted collection {COLL} still returns {st} with a result envelope; the "
              f"documented 'missing collection: HTTP 404' branch did not engage after a "
              f"confirmed DELETE (zombie readout)")
        return
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - expected HTTP 404 exactly "
          f"after delete, got {st}: {raw[:300]}")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
