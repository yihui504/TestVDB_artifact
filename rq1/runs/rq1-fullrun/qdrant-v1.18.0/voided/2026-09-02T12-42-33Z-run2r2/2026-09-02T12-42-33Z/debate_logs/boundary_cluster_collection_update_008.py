#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: both-direction NEGATIVE coverage (G4 + G6) of the empty-binding system-level state
  constraint on cluster+collection+update (POST /collections/{collection_name}/cluster):
  "these operations initiate asynchronous transfers — HTTP 200 means the operation was
  ACCEPTED, not completed; progress is observable through the collection cluster info
  endpoint". Two mutation points on the acceptance bookkeeping, each argued for its
  destructive power (G6):
  (1) DUPLICATE-ACCEPTANCE boundary — the same create_sharding_key {shard_id: K} is
      re-issued after K is accepted and observable. Sharding-key uniqueness is keyed by
      the shard id: double-acceptance is the single easiest way to break the acceptance
      ledger (an idempotency-boundary hole — the second request is byte-identical to the
      first accepted one, so any "validate then append" gap in the acceptance path
      re-executes it);
  (2) REMOVAL-OBSERVABILITY boundary — after drop_sharding_key {shard_key, shard_id}
      is 200-
      accepted, the cluster-info instrument (the endpoint the constraint itself names as
      the progress instrument) MUST stop listing K within an async window; a stale K is
      ghost state the promise says cannot exist.
  [chunk_cluster+collection+update coverage: both-direction negative x
   qdrant_state_cluster_collection_update_001 — duplicate acceptance + drop observability]
Oracle: duplicate create_sharding_key K after K is observable -> 4xx rejection (2xx =
  Type4_StateLogicViolation: the acceptance ledger accepted the same sharding key twice);
  drop_sharding_key K -> 200 accepted, then K MUST vanish from the shard inventory within
  ~12s (K still listed = Type4_StateLogicViolation ghost shard after accepted drop; a
  drop 4xx is recorded for the judge as a broken-200-face NOTE and does not by itself
  type a defect); 5xx anywhere = Type3_RuntimeFailure with /healthz rechecked; transport
  failure with healthy /healthz = SCRIPT_ERROR; explicit-shard carrier refused on this
  deployment = SCRIPT_ERROR (duplicate boundary not exercisable without a deterministic
  shard id — honest exit, no defect conclusion).
Constraint: qdrant_state_cluster_collection_update_001
Blindspot: BS-04 Boundary Default Optimism (acceptance ledger assumed idempotent and its
  removals assumed to propagate to the observability endpoint)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4 lesson: the chunk label is NOT a route):
  attack route: raw_knowledge.api_endpoints[] path="cluster+collection+update", method=POST,
  url="/collections/{collection_name}/cluster";
  observability instrument: path="cluster+collection+info", method=GET,
  url="/collections/{collection_name}/cluster".
  D3b preverify fix (request_required_missing): the create_sharding_key AND
  drop_sharding_key branches of POST /collections/{collection_name}/cluster require the
  shard_key field — all sharding-key bodies now carry shard_key (unique prefix name)
  alongside the explicit shard_id; the duplicate probe stays byte-identical to create #1.
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


POLL_SECONDS = 12
POLL_STEP = 0.5


def read_shard_ids(coll):
    """GET the cluster-info instrument; returns (status, raw, set of shard ids)."""
    s, _, raw = safe_request("GET", f"/collections/{coll}/cluster", timeout=20)
    ids = set()
    try:
        node = json.loads(raw).get("result")
        if isinstance(node, dict):
            for key in ("local_shards", "remote_shards"):
                for entry in (node.get(key) or []):
                    if isinstance(entry, dict) and isinstance(entry.get("shard_id"), int):
                        ids.add(entry["shard_id"])
    except Exception:
        pass
    return s, raw, ids


def transport_or_crash(label, status, raw):
    """Shared ladder fragment: returns verdict string for transport/5xx, else None."""
    if status <= 0:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) — {label} transport failure "
                    f"and /healthz={hs} (service down)")
        return f"SCRIPT_ERROR — {label} transport failure with healthy /healthz (no defect conclusion)"
    if 500 <= status <= 599:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) — {label} got {status} and "
                    f"/healthz={hs} (service down)")
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — {label} got {status} with "
                f"/healthz={hs} alive")
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bccu8" + tag
    coll = pfx + "c"
    key_name = pfx + "sk"  # spec-required shard_key field (D3b preverify: sharding-key branches)
    key_shard = 5100 + (int(time.time() * 1000) % 3000)
    print(f"ownership prefix: {pfx}; shard_key={key_name}; target shard K={key_shard}")

    # Arrange: create one collection (contract-required body: vectors VectorParams)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # Step 1: first acceptance (must succeed — this is the ledger's first entry).
        s, _, raw = safe_request("POST", f"/collections/{coll}/cluster",
                                 json={"create_sharding_key": {"shard_key": key_name,
                                                               "shard_id": key_shard}},
                                 timeout=30)
        print(f"[POST create_sharding_key key={key_name} K={key_shard} #1] -> status={s} "
              f"raw={str(raw)[:200]}")
        v = transport_or_crash("POST create_sharding_key #1", s, raw)
        if v is not None:
            print("VERDICT: " + v)
            return
        if not (200 <= s < 300):
            print("VERDICT: SCRIPT_ERROR — explicit-shard create_sharding_key refused on "
                  "this deployment; the duplicate-acceptance boundary needs a "
                  "deterministic shard id, so no defect conclusion is drawn")
            return

        # Step 2: wait until K is observable (precondition for a meaningful duplicate).
        deadline = time.time() + POLL_SECONDS
        observed = False
        ids = set()
        while time.time() < deadline:
            s, raw, ids = read_shard_ids(coll)
            v = transport_or_crash("poll GET cluster info", s, raw)
            if v is not None:
                print("VERDICT: " + v)
                return
            if key_shard in ids:
                observed = True
                break
            time.sleep(POLL_STEP)
        if not observed:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — first "
                  f"create_sharding_key was 200-accepted but K={key_shard} never became "
                  f"observable in the cluster-info instrument within {POLL_SECONDS}s "
                  f"(ids={sorted(ids)}); the 'progress is observable' promise of "
                  f"qdrant_state_cluster_collection_update_001 is violated")
            return
        print(f"OK: K={key_shard} observable in shard inventory {sorted(ids)}")

        # Act 1 + Assert 1: DUPLICATE-ACCEPTANCE boundary (byte-identical re-issue).
        verdict = None
        s, _, raw = safe_request("POST", f"/collections/{coll}/cluster",
                                 json={"create_sharding_key": {"shard_key": key_name,
                                                               "shard_id": key_shard}},
                                 timeout=30)
        print(f"[POST create_sharding_key key={key_name} K={key_shard} #2 (duplicate)] "
              f"-> status={s} "
              f"raw={str(raw)[:200]}")
        v = transport_or_crash("POST create_sharding_key #2 (duplicate)", s, raw)
        if v is not None:
            print("VERDICT: " + v)
            return
        if 200 <= s < 300:
            verdict = ("DEFECT_FOUND (Type4_StateLogicViolation) — duplicate "
                       f"create_sharding_key K={key_shard} ACCEPTED again with {s} after "
                       "K was already accepted and observable; the acceptance ledger "
                       "double-accepted the same sharding key (byte-identical request)")
        elif 400 <= s < 500:
            print("OK: duplicate create_sharding_key rejected with 4xx (ledger holds)")
        else:
            print(f"NOTE(judge): duplicate create_sharding_key returned {s} "
                  f"(uninterpreted — recorded for the judge)")

        # Act 2 + Assert 2: REMOVAL-OBSERVABILITY boundary.
        s, _, raw = safe_request("POST", f"/collections/{coll}/cluster",
                                 json={"drop_sharding_key": {"shard_key": key_name,
                                                             "shard_id": key_shard}},
                                 timeout=30)
        print(f"[POST drop_sharding_key key={key_name} K={key_shard}] -> status={s} "
              f"raw={str(raw)[:200]}")
        v = transport_or_crash("POST drop_sharding_key", s, raw)
        if v is not None:
            print("VERDICT: " + v)
            return
        if 200 <= s < 300:
            deadline = time.time() + POLL_SECONDS
            gone = False
            while time.time() < deadline:
                s, raw, ids = read_shard_ids(coll)
                v = transport_or_crash("post-drop poll GET cluster info", s, raw)
                if v is not None:
                    print("VERDICT: " + v)
                    return
                if key_shard not in ids:
                    gone = True
                    break
                time.sleep(POLL_STEP)
            if not gone:
                verdict = (f"DEFECT_FOUND (Type4_StateLogicViolation) — drop_sharding_key "
                           f"K={key_shard} was 200-accepted but K remains listed in the "
                           f"cluster-info shard inventory after {POLL_SECONDS}s "
                           f"(ids={sorted(ids)}): ghost shard after an accepted removal")
            else:
                print(f"OK: K={key_shard} removed from the shard inventory (observable)")
        elif 400 <= s < 500:
            print(f"NOTE(judge): drop_sharding_key of the just-created valid key K="
                  f"{key_shard} returned {s} — a valid operation refused is a "
                  f"broken-200-face signal for the judge (not typed here; the 200 face "
                  f"belongs to qdrant_behavioral_cluster_collection_update_001)")
        else:
            print(f"NOTE(judge): drop_sharding_key returned {s} (uninterpreted)")

        if verdict is not None:
            print("VERDICT: " + verdict)
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
