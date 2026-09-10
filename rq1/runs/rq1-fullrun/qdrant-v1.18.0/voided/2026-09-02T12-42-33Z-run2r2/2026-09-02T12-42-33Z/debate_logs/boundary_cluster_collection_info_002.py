#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary (existence boundary) on cluster+collection+info (GET /cluster/collection/{collection_name}) x qdrant_behavioral_cluster_collection_info_001 — paired positive/negative: (a) positive control = existing collection must yield 200; (b) negative probes = three guaranteed-never-created collection names must each yield the documented 404. This is the R1-family mirror probe: the confirmed R1 defect family "per-collection listing face returns 200-on-unknown" is tested here on the cluster-info face.
Oracle: existing collection -> 200 (positive control, else the face is broken and the script reports SCRIPT_ERROR); every unknown collection name -> HTTP 404 exactly; 200 (with any body) for an unknown name = Type1_IllegalSuccess (assertion promises 404); 5xx = Type3_RuntimeFailure (healthz rechecked); a 4xx that is not 404 = recorded as NOTE for the judge (deviates from the documented 404 but still refuses); a 404 whose body nevertheless carries a populated result object with cluster-info fields = Type4_StateLogicViolation.
Constraint: qdrant_behavioral_cluster_collection_info_001 (expected_behavior: "existing collection: HTTP 200 with cluster info; unknown collection: HTTP 404")
Blindspot: BS-04 Boundary Default Optimism (the unknown-name 404 path is documented but assumed wired; per-collection faces have historically answered 200 on unknown names — R1 confirmed family)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven path derivation (no hardcoding from memory):
  contract.api_endpoints[]: path="cluster+collection+info", method="GET",
  category=admin, parameters=[{name: collection_name, type: string,
  required: true, description: "path"}]
  -> /cluster/collection/{collection_name}
Setup face (collections+create) from contract: PUT /collections/{name}
with vectors = VectorParams{size, distance}; delete face DELETE /collections/{name}.
R3 lessons applied: envelope nests at result.<field>; unique per-script
ownership prefix; no list.remove() bookkeeping.
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
    Safe HTTP request wrapper with unified error handling.
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


def liveness():
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs, hraw


def drop_collection(name):
    try:
        safe_request("DELETE", f"/collections/{name}", params={"timeout": 60}, timeout=60)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bcci2" + tag
    coll = pfx + "c1"
    print(f"ownership prefix: {pfx}")

    # Arrange: one existing collection as the positive-control anchor
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # Positive control: existing collection must answer 200
        s, _, raw = safe_request("GET", f"/cluster/collection/{coll}", timeout=30)
        print(f"positive control [{coll}] -> status={s}")
        print(f"  raw: {raw[:200]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"transport failure (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s != 200:
            print(f"VERDICT: SCRIPT_ERROR — existing-collection face returned {s} "
                  f"(assertion promises 200); negative probes not meaningful")
            return
        print("  OK: existing collection answered 200 (promise holds on positive side)")

        # Act: three guaranteed-unknown names (never created in any round;
        # ownership prefix makes collisions impossible)
        unknowns = [
            pfx + "_definitely_missing",
            pfx + "no_such_collection",
            pfx + "miss" + "9" * 12,
        ]
        for name in unknowns:
            s, _, raw = safe_request("GET", f"/cluster/collection/{name}", timeout=30)
            print(f"unknown [{name}] -> status={s}")
            print(f"  raw: {raw[:300]}")
            if s <= 0:
                hs, hraw = liveness()
                print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
                if hs <= 0 or hs >= 500:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — unknown-name "
                          f"lookup killed the service (healthz={hs})")
                else:
                    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
                return
            if 500 <= s <= 599:
                hs, hraw = liveness()
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — unknown collection "
                      f"yielded {s} (healthz={hs})")
                return
            if s == 200:
                # does the 200 carry a populated cluster-info result? (either way 200
                # is already the Type1 violation of the documented 404)
                try:
                    r = json.loads(raw).get("result")
                except Exception:
                    r = None
                extra = ""
                if isinstance(r, dict) and ("peer_id" in r or "shard_count" in r):
                    extra = " (and it carries a populated cluster-info result object)"
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — unknown collection "
                      f"'{name}' answered 200 but the assertion documents 404 for "
                      f"unknown collections{extra} [R1 200-on-unknown family mirror]")
                return
            if s == 404:
                # 404 must not smuggle a populated result payload
                try:
                    r = json.loads(raw).get("result")
                except Exception:
                    r = None
                if isinstance(r, dict) and ("peer_id" in r or "shard_count" in r):
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 404 for "
                          f"'{name}' but body carries cluster-info fields: {raw[:200]}")
                    return
                print("  OK: unknown collection refused with documented 404")
            elif 400 <= s <= 499:
                print(f"  NOTE(judge): unknown collection '{name}' answered {s}, not the "
                      f"documented 404 — refusal happened but deviates from the "
                      f"assertion's stated code")
            else:
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} for unknown name")
                return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
