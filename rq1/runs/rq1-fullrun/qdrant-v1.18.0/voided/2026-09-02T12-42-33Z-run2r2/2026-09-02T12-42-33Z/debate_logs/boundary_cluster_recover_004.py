#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 resource-limit / DoS attack on cluster+recover
  (POST /cluster/recover) x qdrant_behavioral_cluster_recover_001. The endpoint
  documents NO body parameters, so no request-size ceiling is documented either;
  the implementation-layer limits are probed with spec-legal-but-extreme bodies:
    1MB valid JSON object | 8MB valid JSON object | 10k-deep nested array
    (recursive-descent deserializer trap) | 8MB raw NUL body
  Strategy 6 distinction from strategy 1: the defect signal is CRASH/OOM/hang
  (Type3), NOT acceptance — accepting-and-draining a huge body (2xx) or a clean
  413/4xx rejection are both legal outcomes on a body-less admin endpoint.
  [chunk_cluster+recover coverage: strategy6 resource-limit x
   qdrant_behavioral_cluster_recover_001 — request-resource ceiling face]
Oracle: every extreme body -> 2xx gate envelope, clean 4xx, or 413 with the
  service staying alive (/healthz=200 after the batch, 3 attempts on any
  failure); any 5xx/OOM-marker (oom, out of memory, panic, capacity overflow,
  killed) in the response, or /healthz down after a probe = Type3_RuntimeFailure;
  client timeout with healthy /healthz = SCRIPT_ERROR honest exit (no defect
  conclusion from a bounded client timeout alone).
Constraint: qdrant_behavioral_cluster_recover_001
Blindspot: BS-07 Resource Exhaustion Blindspot (no documented body => assumed
  no attack surface; an unbounded body reader can still OOM the worker before
  the distributed-mode gate answers)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/recover-current-peer
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4/R5 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+recover", method="POST",
  url="/cluster/recover" — derived at runtime from raw_knowledge.json (parent
  walk). Deployment reachability probe FIRST (R6 lesson): GET /cluster.
  Container isolation note (v2.2): resource tests may crash the container;
  docker-executor restarts/isolates per script — this script only measures and
  adjudicates honestly.
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


RECOVER_URL = derive_url("cluster+recover")
CLUSTER_STATUS_URL = derive_url("cluster+status")
if not RECOVER_URL or not CLUSTER_STATUS_URL:
    print("VERDICT: SCRIPT_ERROR — url(s) not derivable from raw_knowledge api_endpoints[].url")
    sys.exit(2)
print(f"[url-derived] cluster+recover -> {RECOVER_URL}")
print(f"[url-derived] cluster+status -> {CLUSTER_STATUS_URL}")

OOM_MARKERS = ("oom", "out of memory", "panic", "capacity overflow", "killed", "memory allocation")


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
    """G8 liveness re-check with restart grace. Returns a Type3 verdict string
    if the service is down, else None."""
    for i in range(attempts):
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}': /healthz unreachable "
            f"after {attempts} attempts (service down — container crash suspected)")


def judge_probe(label, status, raw):
    """Declare-first adjudication for one resource-extreme probe.
    Strategy 6 semantics: crash = defect; acceptance or clean rejection = fine.
    Returns verdict string or None."""
    if status <= 0:
        v = healthz_ladder(label)
        if v is not None:
            return v
        return ("SCRIPT_ERROR — transport failure/timeout with healthy /healthz "
                "(no defect conclusion from a bounded client timeout alone)")
    if 500 <= status <= 599:
        # G8: liveness re-check BEFORE any Type3 conclusion from a 5xx.
        v = healthz_ladder(label)
        if v is not None:
            return v
        low = str(raw).lower()
        marker_hit = [m for m in OOM_MARKERS if m in low]
        extra = f" with OOM/panic markers {marker_hit}" if marker_hit else ""
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' got {status} "
                f"with /healthz alive{extra}; body: {str(raw)[:200]}")
    low = str(raw).lower()
    marker_hit = [m for m in OOM_MARKERS if m in low]
    if 200 <= status < 300 or 400 <= status < 500:
        if marker_hit:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' landed in a legal "
                    f"status class but leaked OOM/panic markers {marker_hit} in the body: "
                    f"{str(raw)[:200]}")
        return None  # acceptance or clean 4xx/413 rejection: both legal (strategy 6)
    return f"SCRIPT_ERROR — uninterpreted status {status} for probe '{label}'"


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: bcr4-{tag}")

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

    # Act + Assert: resource-extreme body matrix (generous timeouts for large uploads).
    body_1mb = {"pad": "a" * 1_000_000}
    body_8mb = b'{"pad": "' + b"a" * 8_000_000 + b'"}'
    deep_array = b"[" * 10000 + b"]" * 10000
    nul_8mb = b"\x00" * 8_000_000

    probes = [
        ("1MB valid JSON (json=)", dict(json=body_1mb)),
        ("8MB valid JSON (raw)", dict(data=body_8mb)),
        ("10k-deep nested array (raw)", dict(data=deep_array)),
        ("8MB raw NUL body", dict(data=nul_8mb)),
    ]
    verdict = None
    for label, kwargs in probes:
        s, _, raw = safe_request("POST", RECOVER_URL, timeout=180, **kwargs)
        shown = str(raw)[:200] if isinstance(raw, str) else repr(raw)[:200]
        print(f"[probe {label!r}] -> status={s} raw={shown}")
        v = judge_probe(label, s, raw)
        if v is not None and verdict is None:
            verdict = v

    # Final liveness sweep after the whole batch.
    v = healthz_ladder("post-batch liveness")
    if v is not None and verdict is None:
        verdict = v

    if verdict is not None:
        print("VERDICT: " + verdict)
        return

    print("OK: every resource-extreme body handled without 5xx/OOM/hang; /healthz alive after batch")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
