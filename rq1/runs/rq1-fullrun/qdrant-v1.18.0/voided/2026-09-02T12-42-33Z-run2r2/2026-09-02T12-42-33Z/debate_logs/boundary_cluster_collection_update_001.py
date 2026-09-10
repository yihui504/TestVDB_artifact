#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary — existence boundary on the PATH PARAMETER collection_name of
  cluster+collection+update (POST /collections/{collection_name}/cluster) x
  qdrant_behavioral_cluster_collection_update_001. Both-direction pairing (G4): (a) negative
  probes = three guaranteed-never-created collection names, each carrying a syntactically
  valid operation body, must return the documented 404-for-missing-collection (the
  R1-confirmed 200-on-unknown defect family probed on the cluster-update face); (b) positive
  control = the SAME operation body on an EXISTING collection, recorded as the disposition
  contrast for the same body (2xx/4xx there proves the 404s below are caused by the name,
  not by body rejection).
  [chunk_cluster+collection+update coverage: strategy1 existence-boundary x
   qdrant_behavioral_cluster_collection_update_001 — 404 face + same-body control]
Oracle: unknown collection name -> POST cluster op returns exactly HTTP 404; 2xx =
  Type1_IllegalSuccess (operation accepted on a nonexistent collection); 4xx other than 404
  = Type2_PoorDiagnostics (rejected but on the wrong documented face); 5xx =
  Type3_RuntimeFailure with /healthz rechecked before the verdict; transport failure with
  healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_behavioral_cluster_collection_update_001
Blindspot: BS-04 Boundary Default Optimism (cluster dispatcher assumed to check existence)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+collection+update", method="POST",
  url="/collections/{collection_name}/cluster" -> the REST route used below verbatim.
  Operation body shape: parameter `operation` is a oneOf whose variant names are the
  documented enum (move_shard|replicate_shard|...|create_sharding_key|...) carried as the
  single top-level body key. Setup face (collections+create): PUT /collections/{name}
  with required body vectors = VectorParams{size, distance} (R3/R4 runtime-verified).
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


def safe_request(method, endpoint, json=None, params=None, data=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md).
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, params=params,
            data=data, headers=headers, timeout=timeout,
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


def drop_collection(name):
    try:
        safe_request("DELETE", f"/collections/{name}", params={"timeout": 60}, timeout=60)
    except Exception:
        pass  # cleanup failures are non-fatal


# Declare-first oracle: the documented face for a missing collection is exactly 404.
EXPECT_STATUS = (404,)

# Syntactically valid operation body (variant name from the contract parameter enum);
# used for BOTH the unknown-name probes and the existing-collection control so the only
# varying factor is the collection name.
OP_BODY = {"create_sharding_key": {"shard_id": 4321}}


def judge_probe(label, status, raw):
    """Declare-first adjudication ladder for one probe. Returns verdict string or None."""
    if status <= 0:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' transport "
                    f"failure and /healthz={hs} (service down)")
        return "SCRIPT_ERROR — transport failure with healthy /healthz (no defect conclusion)"
    if 500 <= status <= 599:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' got {status} "
                    f"and /healthz={hs} (service down)")
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' got {status} "
                f"with /healthz={hs} alive")
    if status in EXPECT_STATUS:
        return None  # matches the documented 404 face
    if 200 <= status < 300:
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) — probe '{label}' on a never-created "
                f"collection: expected 404, got 2xx {status}; body: {str(raw)[:200]}")
    if 400 <= status < 500:
        return (f"DEFECT_FOUND (Type2_PoorDiagnostics) — probe '{label}': expected 404 "
                f"(missing collection), got {status} (rejected on the wrong documented "
                f"face); body: {str(raw)[:200]}")
    return f"SCRIPT_ERROR — uninterpreted status {status} for probe '{label}'"


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bccu1" + tag
    coll = pfx + "c"
    print(f"ownership prefix: {pfx}")

    # Arrange: create one collection (contract-required body: vectors VectorParams)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # Positive-direction control: SAME body on the EXISTING collection.
        # (Disposition contrast only; the strict 200-face adjudication lives in 007.)
        s, _, raw = safe_request("POST", f"/collections/{coll}/cluster",
                                 json=OP_BODY, timeout=30)
        print(f"[control existing] POST cluster op -> status={s} raw={str(raw)[:200]}")
        if s == 200:
            print("OK(control): existing collection -> 200 accepted (assertion 200 face holds)")
        elif 400 <= s < 500:
            print(f"NOTE(control): existing collection -> {s} (body variant may be refused "
                  f"on this deployment; recorded for judge — the 404 probes below stay "
                  f"valid because their outcome depends only on the name)")
        elif 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
            print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — control probe got {s} "
                  f"with /healthz={hs}")
            return

        # Act + Assert: never-created collection names must yield exactly 404.
        verdict = None
        for name in (pfx + "ghost1", pfx + "ghost2", pfx + "ghost3"):
            s, _, raw = safe_request("POST", f"/collections/{name}/cluster",
                                     json=OP_BODY, timeout=30)
            print(f"[probe unknown '{name}'] -> status={s} raw={str(raw)[:200]}")
            v = judge_probe(f"unknown-collection:{name}", s, raw)
            if v is not None and verdict is None:
                verdict = v

        if verdict is not None:
            print("VERDICT: " + verdict)
            return

        print("OK: 3/3 never-created names -> exactly 404 (documented missing-collection face)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
