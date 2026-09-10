#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_update_003
# strategy: strategy1_boundary_below_min
# endpoint: collections+update
# constraint_ids: qdrant_range_collections_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — full_scan_threshold minimum 10 KB is
#            diff-specific; create-time schema allows >= 0, so the update diff must enforce
#            its own stricter documented floor)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary x qdrant_range_collections_update_001 (parameter family:
hnsw_config.full_scan_threshold, asserted minimum 10 KB on the update diff) — below-minimum
values full_scan_threshold=9 and =0 must be rejected by PATCH /collections/{collection_name};
the at-min value 10 and the mid-range value 10000 must be accepted (G4 positive branch
closes the min boundary; below-min accepted-and-persisted = Type1_IllegalSuccess)
[chunk_collections+update coverage: strategy1 x qdrant_range_collections_update_001]
Oracle: on a live bcu003_* collection, PATCH hnsw_config.full_scan_threshold=9 and =0 each
return HTTP 400/422 (any 2xx = Type1_IllegalSuccess; 5xx with /healthz alive =
Type3_RuntimeFailure); PATCH full_scan_threshold=10 and =10000 each return HTTP 200 with
envelope result true (4xx = Type1_IllegalRejection of a documented-legal value)
Constraint: qdrant_range_collections_update_001 (bare id) — "full_scan_threshold minimum 10
(KB, diff-specific minimum)" (evidence_tier: explicit; level: endpoint)

Shape anchor (D3b): success face declares result: boolean -> only result-is-True assertions
on 200. Persistence readback uses the [RT]-verified describe envelope result.config.hnsw_config
.full_scan_threshold (declared integer in collections+get response_shape).
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

COLL = "bcu003_" + uuid.uuid4().hex[:10]         # unique-prefix discipline
KEY = "full_scan_threshold"


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


def describe_cfg():
    st, b, raw = safe_request("GET", PATH_GET.format(collection_name=quote(COLL, safe="")),
                              timeout=30)
    if st != 200:
        return None, f"describe status={st}: {raw[:200]}"
    res = b.get("result") if isinstance(b, dict) else None
    cfg = res.get("config") if isinstance(res, dict) else None
    if not isinstance(cfg, dict):
        return None, f"describe result.config missing: {raw[:200]}"
    return cfg, None


def hnsw_field(cfg, key):
    node = cfg.get("hnsw_config")
    if not isinstance(node, dict):
        return None, False, "result.config.hnsw_config missing"
    if key in node:
        return node[key], True, None
    return None, False, None


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


def check_envelope(probe, raw):
    try:
        body = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        body = None
    if isinstance(body, dict) and body.get("result") is True:
        return None
    return (f"DEFECT_FOUND (Type4_StateLogicViolation) - '{probe}' HTTP 200 but envelope "
            f"result is not true: {str(raw)[:200]}")


def judge_reject_probe(probe, attack_val, status, raw):
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if status == 404:
        return f"SCRIPT_ERROR - probe '{probe}' got 404 on a live collection: {raw[:200]}"
    if 400 <= status < 500:
        print(f"OK(reject): '{probe}' -> {status}: {str(raw)[:250]}")
        return None
    if 200 <= status < 300:
        cfg, err = describe_cfg()
        if err:
            return f"SCRIPT_ERROR - '{probe}' 2xx accepted but readback failed: {err}"
        val, present, _ = hnsw_field(cfg, KEY)
        if present and val == attack_val:
            return (f"DEFECT_FOUND (Type1_IllegalSuccess) - '{probe}' attack value "
                    f"{KEY}={attack_val} accepted (2xx {status}) AND persisted "
                    f"(readback {KEY}={val})")
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) - '{probe}' below-min {KEY}={attack_val} "
                f"returned 2xx {status} instead of the documented 400 reject "
                f"(readback {KEY}={val}; judged on the rejection face)")
    return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"


def judge_accept_probe(probe, value, status, raw):
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if status == 200:
        return check_envelope(probe, raw)
    if 400 <= status < 500:
        return (f"DEFECT_FOUND (Type1_IllegalRejection) - '{probe}' documented-legal value "
                f"{KEY}={value} rejected with {status}: {str(raw)[:250]}")
    return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"


def main():
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    for probe, val in ((f"{KEY}=9 (min-1)", 9), (f"{KEY}=0 (deep below)", 0)):
        st, _, raw = patch_cfg({"hnsw_config": {KEY: val}})
        print(f"[probe {probe}] PATCH hnsw_config.{KEY}={val} -> status={st}")
        v = judge_reject_probe(probe, val, st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return

    for probe, val in ((f"{KEY}=10 (at-min)", 10), (f"{KEY}=10000 (mid-range)", 10000)):
        st, _, raw = patch_cfg({"hnsw_config": {KEY: val}})
        print(f"[probe {probe}] PATCH hnsw_config.{KEY}={val} -> status={st} raw={raw[:200]}")
        v = judge_accept_probe(probe, val, st, raw)
        if v is not None:
            print("VERDICT: " + v)
            return
        cfg, err = describe_cfg()
        if err:
            print(f"VERDICT: SCRIPT_ERROR - readback after '{probe}': {err}")
            return
        echo, present, _ = hnsw_field(cfg, KEY)
        print(f"OK(echo): after '{probe}' readback hnsw_config.{KEY}={echo} (present={present})")

    print(f"OK: {KEY}=9/0 rejected (400/422), {KEY}=10 and 10000 accepted with result true")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
