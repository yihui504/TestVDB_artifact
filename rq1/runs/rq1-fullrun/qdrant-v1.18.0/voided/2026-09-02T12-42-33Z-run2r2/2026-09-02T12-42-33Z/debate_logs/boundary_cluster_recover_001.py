#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state-constraint both-direction coverage (G4) on cluster+recover
  (POST /cluster/recover) x qdrant_state_cluster_recover_001. The constraint
  promises recovery "removes the cluster metadata of the current peer and
  restarts it as a single-node cluster FROM LOCAL DATA" (irrecoverable for
  removed peers). Positive direction: exercise the documented call form (the
  contract lists NO body/query/path parameters — only the api-key header) on a
  live deployment holding a pre-seeded collection (5 points) and verify the
  falsifiable remainder of the promise. Negative direction (state guard): a
  REFUSED (4xx deployment gate) recovery must not mutate anything — local
  collection data must survive bit-for-bit; a 200 recovery must equally keep
  local data ("from local data") with the 200 envelope matching the contract
  response_shape (result:boolean, status:string, time:number).
  [chunk_cluster+recover coverage: state-guard both-direction x
   qdrant_state_cluster_recover_001 — destructive-op data-survival face]
Oracle: POST /cluster/recover on a live deployment -> 4xx deployment gate OR
  200 with result:boolean; afterwards /healthz=200, GET /cluster (cluster+status)
  =200, and the seeded collection still exists with exact count 5 — collection
  missing / count!=5 under a refused call = Type4_StateLogicViolation
  (destructive op applied despite refusal), 5xx or /healthz dead after 3 retries
  = Type3_RuntimeFailure, 200 with non-boolean result = response-shape conflict
  vs contract response_shape, transport failure with healthy /healthz =
  SCRIPT_ERROR.
Constraint: qdrant_state_cluster_recover_001
Blindspot: BS-03 Concurrency State Blindness (destructive cluster-op assumed
  to touch ONLY cluster metadata; a gated/refused recover may still corrupt or
  drop local collection state)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/recover-current-peer
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4/R5 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+recover", method="POST",
  url="/cluster/recover" — derived at runtime from raw_knowledge.json via the
  parent walk below (no hardcoded path). Deployment reachability probe FIRST
  (R6 lesson): GET /cluster discovers the cluster mode; on this standalone
  deployment the distributed faces are gated ("status":"disabled" -> 400
  "Distributed mode disabled."), so the assertion's 200-promise face is
  recorded honestly as judge evidence and adjudication judges only the
  falsifiable class that remains (no 5xx, no data loss, service alive).
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

AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")


def derive_url(path_key):
    """R5/R6 standing lesson: URLs come only from raw_knowledge api_endpoints[].url."""
    for _p in Path(__file__).resolve().parents:
        _rk = _p / "raw_knowledge.json"
        if _rk.exists():
            try:
                for _e in json.loads(_rk.read_text(encoding="utf-8")).get("api_endpoints", []):
                    if _e.get("path") == path_key and _e.get("url"):
                        return _e["url"]
            except Exception:
                return None
            return None
    return None


URLS = {
    "cluster+recover": derive_url("cluster+recover"),
    "cluster+status": derive_url("cluster+status"),
    "collections+create": derive_url("collections+create"),
    "points+upsert": derive_url("points+upsert"),
    "points+count": derive_url("points+count"),
}
missing = [k for k, v in URLS.items() if not v]
if missing:
    print(f"VERDICT: SCRIPT_ERROR — url(s) not derivable from raw_knowledge: {missing}")
    sys.exit(2)
for _k, _v in URLS.items():
    print(f"[url-derived] {_k} -> {_v}")
RECOVER_URL = URLS["cluster+recover"]
CLUSTER_STATUS_URL = URLS["cluster+status"]
N_POINTS = 5
DIM = 4


def safe_request(method, endpoint, json=None, params=None, data=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md).
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
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


def healthz_ladder(label, attempts=3, delay=2):
    """G8 liveness re-check WITH restart grace: a successful /cluster/recover may
    legitimately restart the peer, so /healthz gets 3 attempts 2s apart before a
    Type3 conclusion. Returns a verdict string if the service is down, else None."""
    for i in range(attempts):
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"DEFECT_FOUND (Type3_RuntimeFailure) — '{label}': /healthz unreachable "
            f"after {attempts} attempts (service down after recover call)")


def exact_count(name):
    """POST points+count (exact) -> count | None (transport/parse failure)."""
    url = URLS["points+count"].replace("{collection_name}", name)
    s, _, raw = safe_request("POST", url, json={"exact": True}, timeout=30)
    print(f"[count {name}] status={s} raw={str(raw)[:160]}")
    if s != 200:
        return None
    try:
        val = json.loads(raw).get("result")
        if isinstance(val, dict) and isinstance(val.get("count"), int):
            return val["count"]
    except Exception:
        pass
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    coll = f"bcr1{tag}surv"
    print(f"ownership tag: bcr1-{tag} collection={coll}")

    # Arrange 1: deployment reachability probe (R6 lesson: probe before matrices).
    ds, _, draw = safe_request("GET", CLUSTER_STATUS_URL, timeout=15)
    print(f"[discover GET {CLUSTER_STATUS_URL}] status={ds} raw={str(draw)[:200]}")
    if ds <= 0:
        v = healthz_ladder("GET /cluster discovery")
        print("VERDICT: " + (v if v else "SCRIPT_ERROR — discovery transport failure (no defect conclusion)"))
        return
    if 500 <= ds <= 599:
        print(f"VERDICT: SCRIPT_ERROR — discovery got 5xx ({ds}); setup failure, no defect conclusion")
        return
    try:
        _st = json.loads(draw).get("result", {}).get("status", "")
    except Exception:
        _st = ""
    print(f"[discover] cluster status={_st!r}")

    # Arrange 2: seeded local data (the 'local data' the constraint speaks of).
    create_url = URLS["collections+create"].replace("{collection_name}", coll)
    cs, _, craw = safe_request("PUT", create_url,
                               json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    print(f"[create {coll}] status={cs} raw={str(craw)[:160]}")
    if cs not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — setup collection create failed (no defect conclusion)")
        return
    up_url = URLS["points+upsert"].replace("{collection_name}", coll)
    pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM, "payload": {"n": i}}
           for i in range(1, N_POINTS + 1)]
    us, _, uraw = safe_request("PUT", up_url, json={"points": pts}, timeout=60)
    print(f"[upsert {len(pts)} points] status={us} raw={str(uraw)[:160]}")
    if us not in (200, 201):
        try:
            safe_request("DELETE", create_url, params={"timeout": 60}, timeout=60)
        except Exception:
            pass
        print("VERDICT: SCRIPT_ERROR — setup upsert failed (no defect conclusion)")
        return
    before = exact_count(coll)
    if before != N_POINTS:
        try:
            safe_request("DELETE", create_url, params={"timeout": 60}, timeout=60)
        except Exception:
            pass
        print(f"VERDICT: SCRIPT_ERROR — baseline count={before} != {N_POINTS} (no defect conclusion)")
        return

    # Act: the documented call form — no body (contract lists no body parameters).
    print(f"[act] POST {RECOVER_URL} (documented form, empty body)")
    rs, _, rraw = safe_request("POST", RECOVER_URL, json={}, timeout=60)
    print(f"[recover] status={rs} raw={str(rraw)[:300]}")

    # Assert 1: response class (declare-first).
    if rs <= 0:
        v = healthz_ladder("POST /cluster/recover")
        print("VERDICT: " + (v if v else "SCRIPT_ERROR — transport failure with healthy /healthz (no defect conclusion)"))
        _cleanup(coll)
        return
    if 500 <= rs <= 599:
        v = healthz_ladder("POST /cluster/recover")
        print("VERDICT: " + (v if v else f"DEFECT_FOUND (Type3_RuntimeFailure) — POST /cluster/recover got {rs} with /healthz alive; body: {str(rraw)[:200]}"))
        _cleanup(coll)
        return
    if 200 <= rs < 300:
        # response_shape contract: result:boolean, status:string, time:number
        try:
            node = json.loads(rraw)
        except Exception:
            node = {}
        res = node.get("result")
        if not isinstance(res, bool):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation/response-shape conflict) — "
                  f"200 envelope result={res!r} is not boolean per contract response_shape; raw: {str(rraw)[:200]}")
            _cleanup(coll)
            return
        print("[recover] 200 envelope result:boolean confirmed (assertion's 200 face observed)")
    elif 400 <= rs < 500:
        print(f"NOTE: 4xx deployment gate observed ({rs}) — the assertion "
              f"qdrant_behavioral_cluster_recover_001's 200-promise face is gated on this "
              f"deployment (doc-consistency evidence for judge); adjudication continues on "
              f"the falsifiable state class (no data loss, service alive)")
    else:
        print(f"VERDICT: SCRIPT_ERROR — uninterpreted status {rs} (honest exit)")
        _cleanup(coll)
        return

    # Assert 2: state guard — the peer must stay alive and 'from local data' must hold.
    v = healthz_ladder("post-recover liveness")
    if v is not None:
        print("VERDICT: " + v)
        return  # service down: collection checks meaningless
    ps, _, praw = safe_request("GET", CLUSTER_STATUS_URL, timeout=15)
    print(f"[post GET {CLUSTER_STATUS_URL}] status={ps} raw={str(praw)[:160]}")
    if ps <= 0 or 500 <= ps <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — GET /cluster status={ps} "
              f"after recover (cluster plane unusable); raw: {str(praw)[:200]}")
        _cleanup(coll)
        return
    after = exact_count(coll)
    if after != before:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — local data did not "
              f"survive the recover call (count {before} -> {after}, response class {rs}); "
              f"constraint promises single-node restart FROM LOCAL DATA / refused op must not mutate")
        _cleanup(coll)
        return
    print(f"OK: recover status={rs}; /healthz alive; GET /cluster {ps}; "
          f"local data intact (count={after}=={before})")
    _cleanup(coll)
    print("VERDICT: NO_DEFECT")


def _cleanup(coll):
    """Mandatory cleanup spec: teardown wrapped; failure is non-fatal."""
    try:
        url = URLS["collections+create"].replace("{collection_name}", coll)
        safe_request("DELETE", url, params={"timeout": 60}, timeout=60)
    except Exception:
        pass


if __name__ == "__main__":
    main()
