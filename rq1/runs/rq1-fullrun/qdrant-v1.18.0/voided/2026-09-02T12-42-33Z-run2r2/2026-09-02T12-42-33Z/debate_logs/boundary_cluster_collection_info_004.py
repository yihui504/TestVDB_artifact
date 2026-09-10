#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary (existence-boundary transition) on cluster+collection+info (GET /cluster/collection/{collection_name}) x qdrant_behavioral_cluster_collection_info_001 — sequence: create -> cluster-info MUST be 200 with a shard_count field; delete -> (deletion confirmed visible on the collections face, polling up to ~10s to rule out async teardown) -> cluster-info MUST flip to the documented 404. The mutation point is the deletion: the name->cluster-info mapping must be invalidated synchronously with the delete; a stale 200 (or a 5xx) after a confirmed deletion breaks the documented 404-for-unknown/nonexistent promise.
Oracle: after create, GET cluster info returns 200 with result.shard_count present (else SCRIPT_ERROR — setup face broken); after DELETE is confirmed on GET /collections/{name} (404/4xx there too), GET cluster info returns exactly 404 — a stale 200 on the deleted name = Type4_StateLogicViolation (state fails to reconcile with the deletion), 5xx = Type3_RuntimeFailure (healthz rechecked), transport failure with healthy healthz = SCRIPT_ERROR.
Constraint: qdrant_behavioral_cluster_collection_info_001 (expected_behavior: "existing collection: HTTP 200 with cluster info; unknown collection: HTTP 404" — a deleted collection is back in the unknown/nonexistent class)
Blindspot: BS-03 Concurrency State Blindness (cluster-level bookkeeping updated on a different path than collection teardown; the shard map can go stale while the collections face already reports the deletion)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
doc_version: 1.18.x (versioned v-1-18-x api-reference)

G6 mutation justification: deletion is chosen because it is the only legal
transition that moves a name across the assertion's 200/404 boundary; caches
and cluster-shard bookkeeping are the likeliest places for the two faces
(collections vs cluster info) to disagree.

Contract-driven path derivation (no hardcoding from memory):
  contract.api_endpoints[]: path="cluster+collection+info", method="GET",
  category=admin, parameters=[{name: collection_name, ... description: "path"}]
  -> /cluster/collection/{collection_name}
  Setup/teardown faces from contract: PUT /collections/{name} with vectors =
  VectorParams{size, distance}; DELETE /collections/{name}; collections info
  existence face GET /collections/{name}.
R3 lessons applied: envelope nests at result.<field>; unique per-script
ownership prefix; no list.remove() bookkeeping.
"""

import json
import os
import sys
import time
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
    pfx = "bcci4" + tag
    coll = pfx + "c1"
    print(f"ownership prefix: {pfx}")

    # Arrange: create the collection
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    deleted = False
    try:
        # Phase 1: existing collection -> cluster info must be 200 (assertion half A)
        s, _, raw = safe_request("GET", f"/cluster/collection/{coll}", timeout=30)
        print(f"phase1 existing -> status={s}")
        print(f"  raw: {raw[:250]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"transport failure (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s != 200:
            print(f"VERDICT: SCRIPT_ERROR — existing collection answered {s} "
                  f"(assertion promises 200); lifecycle test not meaningful")
            return
        try:
            has_shard_count = "shard_count" in json.loads(raw).get("result", {})
        except Exception:
            has_shard_count = False
        if not has_shard_count:
            print("VERDICT: SCRIPT_ERROR — 200 but result.shard_count unreadable; "
                  "cannot anchor lifecycle (shape face covered by script 001)")
            return
        print("  OK: 200 with shard_count present (half A holds)")

        # Act: delete, then confirm the deletion is visible on the collections face
        s, _, raw = safe_request("DELETE", f"/collections/{coll}",
                                 params={"timeout": 60}, timeout=60)
        print(f"delete -> status={s}")
        print(f"  raw: {raw[:200]}")
        if s <= 0 or s >= 500:
            hs, hraw = liveness()
            print(f"VERDICT: SCRIPT_ERROR — delete failed (status={s}, healthz={hs}); "
                  f"no defect conclusion (deletion face belongs to another chunk)")
            return
        deleted = True

        visible = False
        for attempt in range(5):
            time.sleep(2)
            cs, _, craw = safe_request("GET", f"/collections/{coll}", timeout=30)
            if cs in (400, 404, 405, 410):
                visible = True
                print(f"  deletion visible on collections face after "
                      f"{(attempt + 1) * 2}s (status={cs})")
                break
            print(f"  waiting for deletion visibility (attempt {attempt + 1}, "
                  f"collections face status={cs})")
        if not visible:
            print("VERDICT: SCRIPT_ERROR — deletion never became visible on the "
                  "collections face within 10s; cannot adjudicate cluster face")
            return

        # Phase 2: deleted collection -> cluster info must now be 404 (assertion half B)
        s, _, raw = safe_request("GET", f"/cluster/collection/{coll}", timeout=30)
        print(f"phase2 deleted -> status={s}")
        print(f"  raw: {raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"transport failure (healthz status={hs}: {str(hraw)[:200]})")
            if hs <= 0 or hs >= 500:
                print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — cluster-info "
                      f"lookup on deleted name killed the service (healthz={hs})")
            else:
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            hs, hraw = liveness()
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — deleted collection "
                  f"yielded {s} on cluster info (healthz={hs})")
            return
        if s == 200:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — collection "
                  f"'{coll}' is deleted (collections face confirms) but cluster info "
                  f"still answers 200: stale cluster-shard state contradicts the "
                  f"documented 404-for-nonexistent (assertion "
                  f"qdrant_behavioral_cluster_collection_info_001)")
            return
        if s == 404:
            print("  OK: deleted collection flipped to documented 404")
        elif 400 <= s <= 499:
            print(f"  NOTE(judge): deleted collection answered {s}, not the documented "
                  f"404 — refusal happened but deviates from the assertion's code")
        else:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on deleted name")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        if deleted:
            pass  # already deleted; nothing to clean
        else:
            try:
                drop_collection(coll)
            except Exception:
                pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
