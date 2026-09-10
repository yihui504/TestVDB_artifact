#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-input / character-boundary attack on the required PATH
  PARAMETER peer_id of cluster+peer+delete (DELETE /cluster/peer/{peer_id}) x
  qdrant_behavioral_cluster_peer_delete_001. peer_id is typed integer; the matrix
  attacks the PATH-SEGMENT character layer with pre-encoded values:
    a%00b (NUL byte) | 123%2F456 (encoded slash — segment-split confusion)
    | %2E%2E (dot-dot traversal spelling) | %E4%B8%AD (UTF-8 CJK 'zhong')
    | %FF (invalid UTF-8 byte) | 'a'*2048 (overlong segment).
  [chunk_cluster+peer+delete coverage: strategy7 malformed-input x
   qdrant_behavioral_cluster_peer_delete_001 — peer_id path-character face]
Oracle: every malformed/encoded path value returns 4xx (route-level 404 for
  unparseable segments and validation 400/422 both satisfy the assertion's
  "invalid peer id -> 4xx" face); any 2xx = Type1_IllegalSuccess (a non-numeric or
  encoded path value coerced into a removal success); 5xx / panic / truncated
  response = Type3_RuntimeFailure with /healthz rechecked; connection reset with
  healthy /healthz = SCRIPT_ERROR (anomaly recorded, no defect conclusion);
  transport failure with healthy /healthz = SCRIPT_ERROR; discovery failure =
  SCRIPT_ERROR.
Constraint: qdrant_behavioral_cluster_peer_delete_001
Blindspot: BS-01 Parameter Type Coercion Trust (serde/router assumed to robustly
  reject NUL bytes, encoded slashes and invalid UTF-8 before any handler runs)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4/R5 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+peer+delete", method="DELETE",
  url="/cluster/peer/{peer_id}" -> used verbatim; the encoded probe values are
  appended as the {peer_id} segment (requests re-quote_uri passes valid
  percent-encodings through untouched). Generality red line: this tests the
  input-stream/character layer of a typed path parameter — target-neutral, no
  DB-specific field names involved. Reachability probe FIRST (R5): GET /cluster.
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


def healthz_ladder(label):
    """G8 liveness re-check: Type3 verdict string if the service is down, else None."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    if hs <= 0 or hs >= 500:
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' transport "
                f"failure and /healthz={hs} (service down)")
    return None


def discover_cluster():
    """GET /cluster reachability probe (R5). Returns cluster_status or None (failure)."""
    s, _, raw = safe_request("GET", "/cluster", timeout=15)
    print(f"[discover GET /cluster] status={s} raw={str(raw)[:200]}")
    if s <= 0:
        if healthz_ladder("GET /cluster discovery") is not None:
            return "DOWN"
        return None
    return "probed"


# Declare-first oracle (G7): malformed path characters -> 4xx, never 2xx/5xx.
def judge_probe(label, status, raw):
    """Declare-first adjudication ladder for one probe. Returns verdict string or None."""
    if status <= 0:
        err = str(raw).lower()
        if ("reset" in err or "timed out" in err or "connection" in err):
            v = healthz_ladder(label)
            if v is not None:
                return v
            return (f"SCRIPT_ERROR — probe '{label}' reset the connection while "
                    f"/healthz stayed healthy (anomaly recorded, no defect conclusion)")
        v = healthz_ladder(label)
        if v is not None:
            return v
        return "SCRIPT_ERROR — transport failure with healthy /healthz (no defect conclusion)"
    low = str(raw).lower()
    if 500 <= status <= 599 or any(k in low for k in
                                   ["panic", "internal", "serde", "utf", "decode"]):
        v = healthz_ladder(label)
        if v is not None:
            return v
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' got {status} "
                f"/ parser-error leakage with /healthz alive; body: {str(raw)[:200]}")
    if 400 <= status < 500:
        return None  # satisfies the documented "invalid peer id -> 4xx" face
    if 200 <= status < 300:
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) — probe '{label}': expected 4xx "
                f"(malformed path value), got 2xx {status}; body: {str(raw)[:200]}")
    return f"SCRIPT_ERROR — uninterpreted status {status} for probe '{label}'"


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: bcpd6-{tag}")

    # Arrange: deployment reachability probe (R5 lesson) before the matrix.
    cluster_status = discover_cluster()
    if cluster_status is None:
        print("VERDICT: SCRIPT_ERROR — discovery transport failure (no defect conclusion)")
        return
    if cluster_status == "DOWN":
        print("VERDICT: SCRIPT_ERROR — service down at discovery (no defect conclusion)")
        return

    # Act + Assert: pre-encoded malformed path segments as {peer_id}.
    probes = [
        ("a%00b (NUL byte)", "a%00b"),
        ("123%2F456 (encoded slash)", "123%2F456"),
        ("%2E%2E (dot-dot spelling)", "%2E%2E"),
        ("%E4%B8%AD (UTF-8 CJK)", "%E4%B8%AD"),
        ("%FF (invalid UTF-8 byte)", "%FF"),
        ("'a'*2048 (overlong segment)", "a" * 2048),
    ]
    verdict = None
    for label, value in probes:
        s, _, raw = safe_request("DELETE", f"/cluster/peer/{value}", timeout=30)
        shown = label if "overlong" in label else value
        print(f"[probe {label}] url_segment={shown[:40]} -> status={s} "
              f"raw={str(raw)[:200]}")
        v = judge_probe(label, s, raw)
        if v is not None and verdict is None:
            verdict = v

    if verdict is not None:
        print("VERDICT: " + verdict)
        return

    print("OK: all malformed/encoded path segments -> 4xx; no 2xx/5xx/parser leakage")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
