#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_update_011
# strategy: doc_consistency_two_side
# endpoint: collections+update
# constraint_ids: qdrant_doccons_indexing_threshold_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — two schema faces document DIFFERENT
#            defaults for the same underlying field; the runtime is trusted to resolve one)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: doc-consistency two-side measurement x qdrant_doccons_indexing_threshold_001 — the
versioned v-1-18-x OpenAPI documents indexing_threshold "Default value is 10,000" on the
OptimizersConfig (create/readback) face but "Default value is 20,000" on the
OptimizersConfigDiff (update) face. Both sides are constructed separately: (a) spec side =
create a collection WITHOUT indexing_threshold and read the resolved default back via
describe; (b) prose side = PATCH optimizers_config.indexing_threshold with explicit null and
observe whether the update face re-materializes any default, then PATCH an explicit 50000
and verify echo fidelity. The runtime follows a single underlying default; whichever
documented side it contradicts is recorded (doc-stale side); a third resolved value
contradicts BOTH sides
[chunk_collections+update coverage: doc-consistency two-side x
qdrant_doccons_indexing_threshold_001]
Oracle: fresh bcu011_* collection created without indexing_threshold -> describe readback of
optimizer_config.indexing_threshold resolves to an integer that equals 10000 (create-side
spec holds; diff-side 20000 prose contradicted = recorded doc-stale) OR 20000 (diff-side
holds; create-side contradicted); a PATCH with explicit null returns HTTP 200 with result
true and leaves the readback value unchanged (200 changing it = drift); a PATCH with explicit
50000 returns HTTP 200 and the readback echoes 50000; any resolved default that is neither
10000 nor 20000 = Type4_StateLogicViolation (both documented sides contradicted); 5xx with
/healthz alive = Type3_RuntimeFailure
Constraint: qdrant_doccons_indexing_threshold_001 (bare id) — "doc-internal conflict: spec
says default ten thousand (OptimizersConfig, create/readback) vs twenty thousand
(OptimizersConfigDiff, update diff); either side may be violated" (evidence_tier: explicit;
level: system)

Shape anchor (D3b): update success face declares result: boolean. Readback key
result.config.optimizer_config.indexing_threshold is declared [integer,null] in the
collections+get response_shape (plural key variant tolerated). Doc-conflict zones are
measured-only: the verdict records which documented side the implementation follows.
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

COLL = "bcu011_" + uuid.uuid4().hex[:10]         # unique-prefix discipline
KEY = "indexing_threshold"
SPEC_DEFAULT = 10000      # OptimizersConfig (create/readback face) documented default
DIFF_DEFAULT = 20000      # OptimizersConfigDiff (update face) documented default


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


def read_threshold():
    """Describe and read the stored indexing_threshold. Returns (value, err)."""
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
    if KEY not in node:
        return None, f"describe optimizer_config.{KEY} absent"
    return node[KEY], None


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
    # ---- Arrange: create WITHOUT indexing_threshold (only vectors) ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # ---- (a) spec side: which documented default does the runtime materialize? ----
    v0, err = read_threshold()
    if err:
        print(f"VERDICT: SCRIPT_ERROR - create-face default readback failed: {err}")
        return
    print(f"[spec side] create without {KEY} -> readback resolves {KEY}={v0}")
    side_verdict = None
    if v0 == SPEC_DEFAULT:
        side_verdict = (
            "DEFECT_FOUND (Type2_PoorDiagnostics - doc-stale) - create/readback face "
            f"materializes the documented 10000; the OptimizersConfigDiff (update) prose "
            f"'Default value is 20,000' is contradicted by the single resolved default "
            f"(measured {KEY}={v0})")
    elif v0 == DIFF_DEFAULT:
        side_verdict = (
            "DEFECT_FOUND (Type2_PoorDiagnostics - doc-stale) - runtime materializes 20000; "
            "the OptimizersConfig (create/readback) prose 'Default value is 10,000' is "
            f"contradicted (measured {KEY}={v0})")
    else:
        side_verdict = (
            "DEFECT_FOUND (Type4_StateLogicViolation) - runtime default contradicts BOTH "
            f"documented sides: {KEY}={v0} (spec says 10000, diff prose says 20000)")
    print("[record] " + side_verdict)

    # ---- (b) prose side: update-face default materialization via explicit null ----
    st, _, raw = patch_cfg({"optimizers_config": {KEY: None}})
    print(f"[prose side] PATCH optimizers_config.{KEY}=null -> status={st} raw={str(raw)[:200]}")
    if st <= 0 or 500 <= st <= 599:
        v = transport_or_5xx("explicit-null patch", st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return
    elif st == 200:
        try:
            body = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            body = None
        if not (isinstance(body, dict) and body.get("result") is True):
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - explicit-null PATCH "
                  f"returned 200 with envelope result != true: {str(raw)[:200]}")
            return
        v1, err1 = read_threshold()
        if err1:
            print(f"VERDICT: SCRIPT_ERROR - readback after null patch failed: {err1}")
            return
        print(f"[prose side] after explicit null readback {KEY}={v1} (was {v0})")
        if v1 != v0:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - explicit null changed "
                  f"the stored value from {v0} to {v1} (diff-null drift across faces)")
            return
        print("NOTE: explicit null left the value unchanged (diff null = no-change); the "
              "update-face documented default 20000 is not re-materialized by PATCH")
    elif 400 <= st < 500:
        print(f"NOTE: explicit-null patch rejected with {st}: {str(raw)[:200]} (measured)")
    else:
        print(f"VERDICT: SCRIPT_ERROR - uninterpreted status {st} for explicit-null patch")
        return

    # ---- explicit set + echo fidelity on the update face ----
    st, _, raw = patch_cfg({"optimizers_config": {KEY: 50000}})
    print(f"[echo] PATCH optimizers_config.{KEY}=50000 -> status={st} raw={str(raw)[:200]}")
    if st <= 0 or 500 <= st <= 599:
        v = transport_or_5xx("explicit 50000 patch", st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return
    elif st == 200:
        v2, err2 = read_threshold()
        if err2:
            print(f"VERDICT: SCRIPT_ERROR - readback after 50000 patch failed: {err2}")
            return
        print(f"[echo] readback after explicit 50000 -> {KEY}={v2}")
        if v2 != 50000:
            print("NOTE(no-echo): explicit update accepted but NOT materialized in readback "
                  f"(measured; update-face persistence signal)")
    elif 400 <= st < 500:
        print(f"VERDICT: SCRIPT_ERROR - explicit legal 50000 rejected with {st}: {str(raw)[:200]}")
        return
    else:
        print(f"VERDICT: SCRIPT_ERROR - uninterpreted status {st} for explicit 50000 patch")
        return

    print("VERDICT: " + side_verdict)


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
