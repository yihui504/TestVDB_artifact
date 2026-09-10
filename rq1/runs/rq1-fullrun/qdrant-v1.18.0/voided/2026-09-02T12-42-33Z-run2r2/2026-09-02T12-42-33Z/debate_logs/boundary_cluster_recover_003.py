#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-input / character-boundary attack on cluster+recover
  (POST /cluster/recover) x qdrant_behavioral_cluster_recover_001. The endpoint
  documents NO body parameters, so raw malformed bodies must be drained/rejected
  without ever reaching a parser panic. Raw bytes are sent via data= (bypassing
  client-side json= serialization — v2.5 lesson) across the generic dimensions:
    truncated JSON (b'{"peer_id": 1') | trailing comma (b'{"peer_id": 1,}')
    | single quotes (b"{'peer_id': 1}") | illegal escape (b'"\\q"')
    | comment injection (b'// recover\\n{}') | NUL inside a JSON string
    | escaped UTF-16 lone surrogate (b'{"note": "\\\\ud800"}') | bare NUL body
    | UTF-8 BOM prefix | RTL + zero-width characters
  [chunk_cluster+recover coverage: strategy7 malformed-input x
   qdrant_behavioral_cluster_recover_001 — input-stream malformation face]
Oracle: every malformed raw body -> clean 4xx or 2xx gate envelope, service
  stays alive (/healthz=200 after the batch and on any transport failure,
  3 attempts); any 5xx, or response text containing parser-panic markers
  (panic/serde/internal error/utf/decode), = Type3_RuntimeFailure; 2xx is NOT
  a defect here (no body contract: accepting-and-draining is legal) — only the
  crash face is falsifiable; transport failure with healthy /healthz =
  SCRIPT_ERROR.
Constraint: qdrant_behavioral_cluster_recover_001
Blindspot: BS-01 Parameter Type Coercion Trust (body assumed never parsed
  because undocumented; NUL/surrogate bytes may still reach a serde path and
  panic the worker)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/recover-current-peer
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4/R5 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+recover", method="POST",
  url="/cluster/recover" — derived at runtime from raw_knowledge.json (parent
  walk). Generality red line honored: what is tested is input-stream
  malformation + character encoding, DB-neutral by construction. Deployment
  reachability probe FIRST (R6 lesson): GET /cluster; on this standalone
  deployment the distributed gate is expected to answer — a body-dependent 5xx
  would prove the raw bytes reached a fragile parser path BEFORE the gate.
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

PANIC_MARKERS = ("panic", "serde", "internal error", "internal_error", "utf", "decode")


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
            f"after {attempts} attempts (service down)")


def judge_probe(label, status, raw):
    """Declare-first adjudication for one malformed-body probe.
    Returns verdict string or None (legal/no-crash class observed)."""
    if status <= 0:
        v = healthz_ladder(label)
        if v is not None:
            return v
        return "SCRIPT_ERROR — transport failure with healthy /healthz (no defect conclusion)"
    low = str(raw).lower()
    marker_hit = [m for m in PANIC_MARKERS if m in low]
    if 500 <= status <= 599:
        v = healthz_ladder(label)
        if v is not None:
            return v
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — malformed body '{label}' got {status} "
                f"with /healthz alive; body: {str(raw)[:200]}")
    if 200 <= status < 300 and marker_hit:
        # 2xx is legal for an undocumented body, but a parser-marker leaking in a 2xx
        # body is a crash-adjacent anomaly worth surfacing for the judge.
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — malformed body '{label}' accepted 2xx "
                f"with parser markers {marker_hit} in body: {str(raw)[:200]}")
    if 200 <= status < 300 or 400 <= status < 500:
        return None  # clean rejection or legal accept-and-drain
    return f"SCRIPT_ERROR — uninterpreted status {status} for malformed body '{label}'"


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: bcr3-{tag}")

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

    # Act + Assert: malformed raw-body matrix (data= -> raw bytes, client serde bypassed).
    probes = [
        ("truncated JSON", b'{"peer_id": 1'),
        ("trailing comma", b'{"peer_id": 1,}'),
        ("single quotes", b"{'peer_id': 1}"),
        ("illegal escape", b'"\\q"'),
        ("comment injection", b'// recover\n{}'),
        ("NUL inside JSON string", b'{"note": "x\x00y"}'),
        ("escaped lone surrogate", b'{"note": "\\ud800"}'),
        ("bare NUL body", b"\x00"),
        ("UTF-8 BOM prefix", b"\xef\xbb\xbf{}"),
        ("RTL + zero-width chars", '{"note": "rev‮‌​"}'.encode("utf-8")),
    ]
    verdict = None
    for label, payload in probes:
        s, _, raw = safe_request("POST", RECOVER_URL, data=payload, timeout=60)
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

    print("OK: every malformed raw body handled without 5xx/panic; /healthz alive after batch")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
