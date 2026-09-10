#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary attack on the UNDOCUMENTED request body face of
  cluster+recover (POST /cluster/recover) x qdrant_behavioral_cluster_recover_001.
  The contract documents NO body parameters for this endpoint (only the api-key
  header), so the body face must be handled gracefully for EVERY JSON type:
    string body | number body | boolean body | array body | empty object {}
    | plausible-but-wrong-typed cluster fields ({"peer_id": "abc"} string-where-int,
    {"peer_id": null}, {"restart": true, "timeout": "not-a-number"})
    | 50-level nested object
  plus the documented no-body control (json=None). Because no body contract
  exists, accepting-and-ignoring (200 gate envelope) or clean 4xx are BOTH legal;
  the falsifiable defect signals are 5xx/panic (Type3) and inconsistent
  disposition across body forms (G9 — recorded as judge evidence, not auto-defect).
  [chunk_cluster+recover coverage: strategy2 type-confusion x
   qdrant_behavioral_cluster_recover_001 — undocumented body face]
Oracle: every body form -> status in {2xx gate envelope, clean 4xx}; any 5xx =
  Type3_RuntimeFailure (healthz rechecked, 3 attempts, before the verdict);
  transport failure with healthy /healthz = SCRIPT_ERROR; divergent status
  classes across forms = G9 NOTE for judge; no 2xx/4xx/5xx interpretation =
  SCRIPT_ERROR honest exit.
Constraint: qdrant_behavioral_cluster_recover_001
Blindspot: BS-01 Parameter Type Coercion Trust (serde assumed to tolerate any
  body because none is documented; wrong-typed plausible fields may still reach
  cluster-internal deserialization and panic)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/recover-current-peer
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4/R5 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+recover", method="POST",
  url="/cluster/recover" — derived at runtime from raw_knowledge.json (parent
  walk). Deployment reachability probe FIRST (R6 lesson): GET /cluster; on this
  standalone deployment distributed faces are gated ("status":"disabled") — the
  gate is expected to answer every body form identically, which is exactly the
  consistency this script measures (a body-form-dependent 5xx = parser reached
  before the gate = Type3).
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


RECOVER_URL = derive_url("cluster+recover")
CLUSTER_STATUS_URL = derive_url("cluster+status")
if not RECOVER_URL or not CLUSTER_STATUS_URL:
    print("VERDICT: SCRIPT_ERROR — url(s) not derivable from raw_knowledge api_endpoints[].url")
    sys.exit(2)
print(f"[url-derived] cluster+recover -> {RECOVER_URL}")
print(f"[url-derived] cluster+status -> {CLUSTER_STATUS_URL}")


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
    """G8 liveness re-check with restart grace (recover may restart the peer).
    Returns a Type3 verdict string if the service is down, else None."""
    for i in range(attempts):
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            import time
            time.sleep(delay)
    return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}': /healthz unreachable "
            f"after {attempts} attempts (service down)")


def judge_probe(label, status, raw):
    """Declare-first adjudication ladder for one body-form probe.
    Returns verdict string or None (legal class observed)."""
    if status <= 0:
        v = healthz_ladder(label)
        if v is not None:
            return v
        return "SCRIPT_ERROR — transport failure with healthy /healthz (no defect conclusion)"
    if 500 <= status <= 599:
        v = healthz_ladder(label)
        if v is not None:
            return v
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — body form '{label}' got {status} "
                f"with /healthz alive; body: {str(raw)[:200]}")
    if 200 <= status < 300 or 400 <= status < 500:
        return None  # no body contract: 2xx gate envelope and clean 4xx are both legal
    return f"SCRIPT_ERROR — uninterpreted status {status} for body form '{label}'"


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: bcr2-{tag}")

    # Arrange: deployment reachability probe (R6 lesson).
    ds, _, draw = safe_request("GET", CLUSTER_STATUS_URL, timeout=15)
    print(f"[discover GET {CLUSTER_STATUS_URL}] status={ds} raw={str(draw)[:200]}")
    if ds <= 0:
        v = healthz_ladder("GET /cluster discovery")
        print("VERDICT: " + (v if v else "SCRIPT_ERROR — discovery transport failure (no defect conclusion)"))
        return
    if 500 <= ds <= 599:
        print(f"VERDICT: SCRIPT_ERROR — discovery got 5xx ({ds}); setup failure, no defect conclusion")
        return

    # Act + Assert: body-form matrix (documented control first, then every type face).
    deep = {"leaf": True}
    for _ in range(50):
        deep = {"a": deep}
    probes = [
        ("documented no-body control", None),
        ("string body", "recover-please"),
        ("number body", 42),
        ("boolean body", True),
        ("array body", [1, 2, 3]),
        ("empty object", {}),
        ("peer_id string-where-int", {"peer_id": "abc"}),
        ("peer_id null", {"peer_id": None}),
        ("wrong-typed op fields", {"restart": True, "timeout": "not-a-number"}),
        ("50-level nested object", deep),
    ]
    dispositions = {}
    verdict = None
    for label, payload in probes:
        s, _, raw = safe_request("POST", RECOVER_URL, json=payload, timeout=60)
        print(f"[probe {label!r}] -> status={s} raw={str(raw)[:200]}")
        dispositions[label] = s
        v = judge_probe(label, s, raw)
        if v is not None and verdict is None:
            verdict = v

    if verdict is not None:
        print("VERDICT: " + verdict)
        return

    # G9 consistency note (judge evidence, not auto-defect: no body contract exists).
    classes = sorted(set(dispositions.values()))
    print(f"[dispositions] {dispositions}")
    if len(classes) > 1:
        print(f"NOTE(G9): divergent status classes across body forms {classes} — "
              f"inconsistent disposition of the undocumented body face (judge evidence)")

    print("OK: every body form landed in a legal class (2xx gate envelope or clean 4xx); no 5xx")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
