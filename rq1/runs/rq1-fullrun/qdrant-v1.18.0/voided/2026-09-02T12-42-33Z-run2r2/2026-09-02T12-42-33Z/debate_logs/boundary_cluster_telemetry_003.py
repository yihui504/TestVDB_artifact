#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 resource-limit attack + strategy7 malformed-input attack on
  the timeout query parameter of cluster+telemetry (GET /cluster/telemetry) x
  qdrant_range_cluster_telemetry_001 (evidence_tier explicit). The
  constraint's assertion, quoted verbatim:
    "timeout default 60, minimum 1"
  Difference from boundary_cluster_telemetry_001 (strategy1 = contract
  boundary): here the target is the IMPLEMENTATION layer — spec-legal but
  extreme integers and malformed byte streams whose only defect signal is a
  crash (500/panic/OOM/hang), per the strategy6 assertion logic (200 or 4xx
  are both conforming; a crash is the defect). Legs:
    resource: 1000000, 2147483647 (i32 max), 18446744073709551615 (u64 max,
      spec-legal integer — schema has minimum 1 and NO maximum),
    overflow: 18446744073709551616 (u64 max + 1 — expected clean 4xx parse
      rejection, never a panic),
    malformed (strategy7): "9" * 4000 (overlong digit stream), "a\\x00b"
      (NUL byte percent-encoded into the query value), Arabic-Indic digits
      (non-ASCII numerals) — each expected clean 4xx; 2xx = Type1 pending
      judge-doc verification per strategy7; 5xx/panic = Type3.
[chunk_cluster+telemetry coverage: strategy6 resource-limit + strategy7
 malformed-input x qdrant_range_cluster_telemetry_001(timeout); strategy1
 contract boundary covered by boundary_cluster_telemetry_001]
Oracle: every leg returns 2xx or 4xx WITHOUT crash markers — 5xx (with
  /healthz rechecked alive) = DEFECT_FOUND (Type3_RuntimeFailure); any body
  containing panic/oom/out of memory/internal error leakage = DEFECT_FOUND
  (Type3_RuntimeFailure); /healthz unreachable after 3 attempts = DEFECT
  (Type3 service down); a malformed-stream leg answered 2xx = DEFECT_FOUND
  (Type1_IllegalSuccess, pending judge-doc verification per strategy7);
  transport failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_range_cluster_telemetry_001
Blindspot: BS-04 Boundary Default Optimism (u64 parse path trusted for
  extreme/overflow input; allocator or parser panic is the crash class)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-telemetry
doc_version: 1.18.x (versioned v-1-18-x api-reference)
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


CLUSTER_TELEMETRY_URL = derive_url("cluster+telemetry")
if not CLUSTER_TELEMETRY_URL:
    print("VERDICT: SCRIPT_ERROR — url not derivable from raw_knowledge api_endpoints[].url (cluster+telemetry)")
    sys.exit(2)
print(f"[url-derived] cluster+telemetry -> {CLUSTER_TELEMETRY_URL}")

U64_MAX = 18446744073709551615
CRASH_MARKERS = ("panic", "out of memory", "oom", "capacity overflow", "internal error",
                 "stack overflow", "abort")


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
    """G8 liveness re-check: /healthz gets 3 attempts 2s apart before any Type3
    conclusion (transport-branch probe; standing lesson)."""
    for i in range(attempts):
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    # NOTE: returns a BARE Type3 message (no DEFECT_FOUND prefix — the caller's
    # verdict wrapper adds it exactly once).
    return (f"Type3_RuntimeFailure(service-down) — '{label}': /healthz unreachable "
            f"after {attempts} attempts")


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: bct3-{tag}")
    print("[constraint quote] timeout default 60, minimum 1 — strategy6/7 target the "
          "implementation layer: crash is the defect, 200-or-4xx both conform")

    legs = [
        ("resource", "timeout=1000000", {"timeout": 1000000}),
        ("resource", "timeout=2147483647 (i32 max)", {"timeout": 2147483647}),
        ("resource", "timeout=18446744073709551615 (u64 max, spec-legal: no maximum)", {"timeout": U64_MAX}),
        ("overflow", "timeout=18446744073709551616 (u64 max+1, parse overflow)", {"timeout": U64_MAX + 1}),
        ("malformed", "timeout='9'*4000 (overlong digit stream)", {"timeout": "9" * 4000}),
        ("malformed", "timeout='a\\x00b' (NUL byte in query value)", {"timeout": "a\x00b"}),
        ("malformed", "timeout=Arabic-Indic digits (non-ASCII numerals)", {"timeout": "١٢٣"}),
    ]

    findings = []  # (rank, message); 0 = Type3 crash, 1 = Type1 pending-judge, 2 = script-error
    for kind, label, params in legs:
        s, b, r = safe_request("GET", CLUSTER_TELEMETRY_URL, params=params, timeout=20)
        print(f"[{kind} {label}] status={s} raw={str(r)[:280]}")
        if s <= 0:
            v = healthz_ladder(label)
            if v:
                findings.append((0, v))
                break
            findings.append((2, f"SCRIPT-ERROR-transport: '{label}' transport failure with healthy /healthz"))
            break
        low = str(r).lower()
        crashed = any(m in low for m in CRASH_MARKERS)
        if 500 <= s <= 599 or crashed:
            v = healthz_ladder(label)
            why = (f"body crash marker present ({[m for m in CRASH_MARKERS if m in low]})" if crashed else f"status {s}")
            findings.append((0, v if v else f"Type3_RuntimeFailure: '{label}' -> {why} with /healthz alive; "
                                           f"body: {str(r)[:200]}"))
            continue
        if 200 <= s <= 299:
            if kind == "malformed":
                findings.append((1, f"Type1_IllegalSuccess (pending judge-doc verification per strategy7): "
                                    f"malformed stream '{label}' ACCEPTED with {s}; raw: {str(r)[:200]}"))
            else:
                print(f"[conform-record] '{label}' accepted with {s} (spec-legal extreme — "
                      f"acceptance is NOT a defect in the resource-limit class)")
        elif 400 <= s <= 499:
            print(f"[conform] '{label}' cleanly rejected with {s}")
        else:
            findings.append((2, f"SCRIPT-ERROR-status: '{label}' uninterpreted status {s}"))

    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 2:
            print(f"VERDICT: SCRIPT_ERROR — {msg}")
        else:
            print(f"VERDICT: DEFECT_FOUND ({msg})")
        return
    print("OK: no crash, no panic, no hang on any extreme/overflow/malformed timeout probe")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
