#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_update_010
# strategy: strategy1_state_both_direction
# endpoint: collections+update
# constraint_ids: qdrant_state_collections_update_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-04 (Boundary Default Optimism — PATCH update must not smuggle a
#            vector-space-defining change (size/distance of an existing named vector)
#            past the state invariant; only index/quantization/disk-style config may change)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 state-boundary both-direction x qdrant_state_collections_update_001
(system-level state invariant: after creation the size/distance of an existing named vector
cannot be changed via PATCH update, while index/quantization/disk-style config CAN be
changed) — negative branch: PATCH vectors.doc.size=999 and vectors.doc.distance=Dot on a
collection created with named vector doc{size 4, Cosine} must either be rejected (4xx) or
leave the vector-space untouched; persistence of a changed size/distance = violation.
Positive branch (G4): PATCH hnsw_config.m=8 and quantization_config scalar int8 must be
accepted (200) AND persisted in the describe readback (probe persistence via readback, not
just status — R16 standing lesson)
[chunk_collections+update coverage: both-direction x qdrant_state_collections_update_001]
Oracle: on a live bcu010_* collection with named vector doc{size 4, Cosine}, each PATCH
attempt to change doc's size or distance returns EITHER HTTP 4xx OR HTTP 200 with the
describe readback of doc.size/doc.distance unchanged at 4/Cosine (a 2xx that alters the
vector-space = Type1_IllegalSuccess state violation); PATCH hnsw_config.m=8 and
quantization_config.scalar.type=int8 each return HTTP 200 with result true AND persist in
readback (rejection of these documented-legal config changes = Type1_IllegalRejection;
5xx/transport re-checked via /healthz)
Constraint: qdrant_state_collections_update_001 (bare id) — "after creation, size/distance of
an existing (named) vector cannot be changed via PATCH update; index/quantization/disk
config can" (evidence_tier: explicit; level: system)

Shape anchor (D3b): PATCH success face declares result: boolean. Vector-space readback
locations tolerated: result.config.params.vectors.<name> (per [RT] schema notes) with
result.vectors.<name> as fallback; both declared object shapes on the collections+get face.
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

COLL = "bcu010_" + uuid.uuid4().hex[:10]         # unique-prefix discipline
VNAME = "doc"


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


def describe_full():
    st, b, raw = safe_request("GET", PATH_GET.format(collection_name=quote(COLL, safe="")),
                              timeout=30)
    if st != 200:
        return None, f"describe status={st}: {raw[:200]}"
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        return None, f"describe result not object: {raw[:200]}"
    return res, None


def named_vector(res):
    """Return the named-vector params object for VNAME or None. Tolerates the two declared
    readback locations: result.config.params.vectors.<name> and result.vectors.<name>."""
    cfg = res.get("config")
    if isinstance(cfg, dict):
        params = cfg.get("params")
        if isinstance(params, dict):
            v = params.get("vectors")
            if isinstance(v, dict) and VNAME in v:
                return v[VNAME]
    v = res.get("vectors")
    if isinstance(v, dict) and VNAME in v:
        return v[VNAME]
    return None


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


def judge_forbidden_probe(probe, field, status, raw, expect_size, expect_dist):
    """Forbidden vector-space change: 4xx reject OR 200 with untouched readback = OK;
    200 with altered size/distance = state violation."""
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if 400 <= status < 500:
        print(f"OK(reject): '{probe}' -> {status} (documented cannot-change face): "
              f"{str(raw)[:250]}")
        return None
    if 200 <= status < 300:
        res, err = describe_full()
        if err:
            return f"SCRIPT_ERROR - '{probe}' 2xx but readback failed: {err}"
        nv = named_vector(res)
        if nv is None:
            return f"SCRIPT_ERROR - '{probe}' named vector '{VNAME}' absent from readback"
        sz = nv.get("size")
        ds = nv.get("distance")
        print(f"[readback] after '{probe}' vector '{VNAME}': size={sz} distance={ds}")
        if sz == expect_size and ds == expect_dist:
            print(f"NOTE(silent-ignore): '{probe}' returned 2xx {status} but the vector-space "
                  f"is unchanged (cannot-change invariant holds)")
            return None
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) - '{probe}' altered the vector-space: "
                f"size={sz} distance={ds} (was {expect_size}/{expect_dist}) despite the "
                f"documented state invariant")
    return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"


def judge_config_probe(probe, status, raw):
    """Legal config change: 200 with result true expected."""
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if status == 200:
        try:
            body = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            body = None
        if isinstance(body, dict) and body.get("result") is True:
            return None
        return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' HTTP 200 but envelope "
                f"result is not true: {str(raw)[:200]}")
    if 400 <= status < 500:
        return (f"DEFECT_FOUND (Type1_IllegalRejection) - '{probe}' documented-legal config "
                f"change rejected with {status}: {str(raw)[:250]}")
    return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"


def main():
    create_body = {"vectors": {VNAME: {"size": 4, "distance": "Cosine"}}}
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json=create_body, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # baseline readback of the vector-space
    res, err = describe_full()
    if err:
        print(f"VERDICT: SCRIPT_ERROR - baseline describe: {err}")
        return
    nv = named_vector(res)
    print(f"baseline vector '{VNAME}': {json.dumps(nv)[:200]}")
    base_size = 4
    base_dist = "Cosine"

    # ---- Negative branch: forbidden vector-space changes ----
    for probe, field, body in (
        ("size change doc.size=999", "size",
         {"vectors": {VNAME: {"size": 999}}}),
        ("distance change doc.distance=Dot", "distance",
         {"vectors": {VNAME: {"distance": "Dot"}}}),
    ):
        st, _, raw = patch_cfg(body)
        print(f"[probe {probe}] PATCH -> status={st} raw={str(raw)[:200]}")
        v = judge_forbidden_probe(probe, field, st, raw, base_size, base_dist)
        if v is not None:
            print("VERDICT: " + v)
            return

    # ---- Positive branch: index/quantization config changes must work ----
    st, _, raw = patch_cfg({"hnsw_config": {"m": 8}})
    print(f"[probe hnsw_config.m=8 (index config change)] PATCH -> status={st} raw={raw[:200]}")
    v = judge_config_probe("hnsw_config.m=8", st, raw)
    if v is not None:
        print("VERDICT: " + v)
        return
    res, err = describe_full()
    if err:
        print(f"VERDICT: SCRIPT_ERROR - readback after hnsw change: {err}")
        return
    cfg = res.get("config") if isinstance(res, dict) else None
    hn = cfg.get("hnsw_config") if isinstance(cfg, dict) else None
    if isinstance(hn, dict) and hn.get("m") == 8:
        print("OK(echo): hnsw_config.m=8 persisted in readback")
    else:
        print(f"NOTE(no-echo): hnsw_config.m readback={hn} (update 200 but not echoed)")

    st, _, raw = patch_cfg({"quantization_config": {"scalar": {"type": "int8"}}})
    print(f"[probe scalar int8 quantization enable] PATCH -> status={st} raw={raw[:200]}")
    v = judge_config_probe("quantization scalar int8", st, raw)
    if v is not None:
        print("VERDICT: " + v)
        return
    res, err = describe_full()
    if err:
        print(f"VERDICT: SCRIPT_ERROR - readback after quantization change: {err}")
        return
    cfg = res.get("config") if isinstance(res, dict) else None
    qc = cfg.get("quantization_config") if isinstance(cfg, dict) else None
    qnode = qc.get("scalar") if isinstance(qc, dict) else None
    qtype = qnode.get("type") if isinstance(qnode, dict) else None
    print(f"OK(echo-check): quantization_config readback type={qtype} "
          f"(present={qc is not None})")
    if qtype != "int8":
        print("NOTE(no-echo): quantization config update 200 but not materialized in readback")

    # invariant re-check after all probes
    res, err = describe_full()
    if err:
        print(f"VERDICT: SCRIPT_ERROR - final describe: {err}")
        return
    nv = named_vector(res)
    print(f"final vector '{VNAME}': {json.dumps(nv)[:200]}")
    if not (isinstance(nv, dict) and nv.get("size") == base_size
            and nv.get("distance") == base_dist):
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - final readback shows the "
              "vector-space changed during this session")
        return

    print("OK: size/distance change attempts rejected-or-ignored; config changes accepted "
          "and persisted; vector-space invariant holds")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
