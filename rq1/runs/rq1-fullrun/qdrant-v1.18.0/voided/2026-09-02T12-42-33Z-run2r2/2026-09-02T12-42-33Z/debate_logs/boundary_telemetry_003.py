#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 cross-face disposition-consistency attack (G9: inconsistent
  disposition of the same parameter across interface faces = a defect signal,
  no extra contract endorsement needed) on the timeout query parameter,
  anchored on qdrant_range_cluster_telemetry_001 (evidence_tier explicit),
  whose assertion, quoted verbatim:
    "timeout default 60, minimum 1"
  R8-lesson cross-check performed BEFORE writing the oracle: the versioned
  v-1-18-x OpenAPI declares the timeout query schema IDENTICALLY on both
  faces — /cluster/telemetry {type: integer, minimum: 1, default: 60} and
  /telemetry {type: integer, minimum: 1, default: 60}. Same parameter
  family, same published schema -> the same disposition class is expected
  on both faces for each probe value; an asymmetry (one face rejects, the
  other accepts the identical token) is the G9 defect signal.
  Probes per face: timeout=1 (positive closure), timeout=0 (below minimum),
  timeout=-1, timeout='abc' (type-invalid).
[coverage: /telemetry endpoint of this round per dispatch NOTE; strategy1
 cross-face x qdrant_range_cluster_telemetry_001(timeout) on both
 documented faces; single-face deep matrices already covered by
 boundary_cluster_telemetry_001/002]
Oracle: for EACH probe value, /cluster/telemetry and /telemetry return the
  same disposition class (2xx-or-4xx agreement per value); timeout=1 -> 2xx
  on both (documented minimum closure; a 4xx face = DEFECT Type4 disposition
  conflict); timeout in {0,-1,'abc'} -> 4xx on both — any face answering 2xx
  = DEFECT_FOUND (Type1_IllegalSuccess vs 'timeout default 60, minimum 1'
  on the registered constraint face, corroborated by the identical published
  schema on the other face); same value disposed 2xx on one face and 4xx on
  the other (both otherwise conforming) = DEFECT_FOUND (Type4
  inconsistent-disposition across interface faces, G9); 5xx (with /healthz
  rechecked) = DEFECT Type3; transport failure with healthy /healthz =
  SCRIPT_ERROR.
Constraint: qdrant_range_cluster_telemetry_001
Blindspot: BS-04 Boundary Default Optimism (the same declared minimum
  enforced on one actix handler but defaulted away on its sibling handler)
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


FACES = {
    "cluster+telemetry": derive_url("cluster+telemetry"),
    "telemetry": derive_url("telemetry"),
}
missing = [k for k, v in FACES.items() if not v]
if missing:
    print(f"VERDICT: SCRIPT_ERROR — url not derivable from raw_knowledge api_endpoints[].url ({missing})")
    sys.exit(2)
for k, v in FACES.items():
    print(f"[url-derived] {k} -> {v}")


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


def disposition_class(status):
    if 200 <= status <= 299:
        return "2xx"
    if 400 <= status <= 499:
        return "4xx"
    if 500 <= status <= 599:
        return "5xx"
    return f"other-{status}"


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: btl3-{tag}")
    print("[constraint quote] timeout default 60, minimum 1 — identical published "
          "schema on both faces ({type: integer, minimum: 1, default: 60})")

    probes = [
        ({"timeout": 1}, "2xx", "min-closure positive"),
        ({"timeout": 0}, "4xx", "below minimum"),
        ({"timeout": -1}, "4xx", "negative integer"),
        ({"timeout": "abc"}, "4xx", "type-invalid token"),
    ]

    findings = []  # (rank, message); 0 = Type3, 1 = Type1, 2 = Type4, 3 = script-error

    for params, expected, kind in probes:
        dispositions = {}
        for face, url in FACES.items():
            s, b, r = safe_request("GET", url, params=params, timeout=15)
            label = f"{face} timeout={list(params.values())[0]!r} ({kind})"
            print(f"[{label}] status={s} raw={str(r)[:250]}")
            if s <= 0:
                v = healthz_ladder(label)
                if v:
                    findings.append((0, v))
                    break
                findings.append((3, f"SCRIPT-ERROR-transport: '{label}' with healthy /healthz"))
                break
            if 500 <= s <= 599:
                v = healthz_ladder(label)
                findings.append((0, v if v else f"Type3_RuntimeFailure: '{label}' got {s} with "
                                                f"/healthz alive; body: {str(r)[:200]}"))
                break
            cls = disposition_class(s)
            dispositions[face] = (cls, s, str(r)[:150])
            if cls.startswith("other-"):
                findings.append((3, f"SCRIPT-ERROR-status: '{label}' uninterpreted status {s}"))
                break
        if findings:
            break

        classes = {c for c, _, _ in dispositions.values()}
        if len(classes) > 1:
            detail = " | ".join(f"{f}->{c}({s})" for f, (c, s, _) in dispositions.items())
            findings.append((2, f"Type4 inconsistent-disposition across interface faces (G9): "
                                f"timeout={list(params.values())[0]!r} ({kind}) disposed differently "
                                f"on the two faces sharing the IDENTICAL published schema "
                                f"{{integer, minimum:1, default:60}}: {detail}"))
            continue
        cls = classes.pop()
        if cls != expected:
            if cls == "2xx":
                findings.append((1, f"Type1_IllegalSuccess: timeout="
                                                     f"{list(params.values())[0]!r} ({kind}) ACCEPTED 2xx on BOTH "
                                                     f"faces ({detail_faces(dispositions)}) — violates "
                                                     f"'timeout default 60, minimum 1' "
                                                     f"(qdrant_range_cluster_telemetry_001; identical schema on "
                                                     f"the service face)"))
            else:
                findings.append((2, f"Type4 disposition conflict: timeout="
                                    f"{list(params.values())[0]!r} ({kind}) returned {cls} on both faces "
                                    f"({detail_faces(dispositions)}) — expected {expected} per the "
                                    f"published minimum:1 schema"))
        else:
            print(f"[conform] timeout={list(params.values())[0]!r} ({kind}): {expected} on both faces "
                  f"({detail_faces(dispositions)})")

    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR — {msg}")
        else:
            print(f"VERDICT: DEFECT_FOUND ({msg})")
        return
    print("OK: identical timeout dispositions on both faces; minimum enforced symmetrically")
    print("VERDICT: NO_DEFECT")


def detail_faces(dispositions):
    return " | ".join(f"{f}->{c}({s})" for f, (c, s, _) in dispositions.items())


if __name__ == "__main__":
    main()
