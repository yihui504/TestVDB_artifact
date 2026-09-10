#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value attack on the timeout query parameter of
  cluster+telemetry (GET /cluster/telemetry) x qdrant_range_cluster_telemetry_001
  (evidence_tier explicit). The constraint's assertion, quoted verbatim:
    "timeout default 60, minimum 1"
  R8-lesson cross-check performed BEFORE writing the oracle: the versioned
  v-1-18-x OpenAPI (local shard openapi.json, path /cluster/telemetry) declares
  timeout schema {type: integer, minimum: 1, default: 60} — the contract grid
  IS corroborated by the published spec (no R8-style phantom grid). Boundary
  matrix (G4 both directions, one shared deployment):
    positive closure legs: timeout omitted (default-60 form), 1 (min), 2
    (min+1), 60 (documented default value) -> each 2xx with the documented
    envelope {status:string, time:number, result:object} and the
    schema-REQUIRED result.collections object;
    negative legs: timeout 0 (min-1), -1, -100 -> each 4xx (documented
    minimum 1; 2xx = Type1_IllegalSuccess);
    max legs: N/A — no documented maximum exists in either source (annotated,
    not fabricated).
[chunk_cluster+telemetry coverage: strategy1 boundary-matrix x
 qdrant_range_cluster_telemetry_001(timeout); strategy2 response-grid is
 covered by boundary_cluster_telemetry_004; strategy3 (dimension) has no
 applicable target — the endpoint declares no vector parameter]
Oracle: timeout in {omitted,1,2,60} -> 200 with envelope status:string +
  time:number + result:object + result.collections:object (REQUIRED per
  published OpenAPI DistributedTelemetryData); timeout in {0,-1,-100} -> 4xx
  each; any 2xx on a negative leg = DEFECT_FOUND (Type1_IllegalSuccess —
  below-minimum timeout accepted, violating 'timeout default 60, minimum 1');
  5xx on any leg with /healthz alive = DEFECT_FOUND (Type3_RuntimeFailure);
  4xx on a positive leg = DEFECT_FOUND (Type4 disposition conflict —
  documented-legal closure value rejected); envelope violation on a positive
  2xx = DEFECT_FOUND (Type4_StateLogicViolation); transport failure with
  healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_range_cluster_telemetry_001
Blindspot: BS-04 Boundary Default Optimism (docs promise min 1; a serde u64
  default that silently admits 0 is exactly the un-validated boundary this
  blindspot names)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-telemetry
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4/R5 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+telemetry", method="GET",
  url="/cluster/telemetry" — derived at runtime via the parent walk below.
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
    conclusion (transport-branch probe; standing lesson). Returns a Type3
    verdict string if the service is down, else None."""
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


def envelope_violations(node):
    """Declare-first check of the documented response envelope
    ({status:string, time:number, result:object} per published OpenAPI
    Distributed_cluster_telemetry_Response_200 + contract response_shape)."""
    bad = []
    if not isinstance(node.get("status"), str):
        bad.append(f"envelope status not a string (got {node.get('status')!r})")
    if not (isinstance(node.get("time"), (int, float)) and not isinstance(node.get("time"), bool)):
        bad.append(f"envelope time not a number (got {node.get('time')!r})")
    if not isinstance(node.get("result"), dict):
        bad.append(f"envelope result not an object (got {type(node.get('result')).__name__})")
        return bad
    if not isinstance(node["result"].get("collections"), dict):
        bad.append("result.collections not an object (REQUIRED per published OpenAPI "
                   "DistributedTelemetryData)")
    return bad


def parse_body(raw, body):
    try:
        return json.loads(raw) if isinstance(raw, str) else (body if isinstance(body, dict) else {})
    except Exception:
        return {}


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: bct1-{tag}")
    print("[constraint quote] timeout default 60, minimum 1 "
          "(OpenAPI corroboration: {type: integer, minimum: 1, default: 60})")
    print("[matrix note] no documented maximum in any source -> max-closure legs N/A (annotated, not fabricated)")

    # (label, params, expected_class) — expected: '2xx' positive closure, '4xx' negative
    legs = [
        ("timeout omitted (default-60 form)", None, "2xx"),
        ("timeout=1 (min closure)", {"timeout": 1}, "2xx"),
        ("timeout=2 (min+1)", {"timeout": 2}, "2xx"),
        ("timeout=60 (documented default value)", {"timeout": 60}, "2xx"),
        ("timeout=0 (min-1)", {"timeout": 0}, "4xx"),
        ("timeout=-1", {"timeout": -1}, "4xx"),
        ("timeout=-100", {"timeout": -100}, "4xx"),
    ]

    findings = []  # (rank, message); rank 0 = Type1, 1 = Type3, 2 = Type4
    for label, params, expected in legs:
        s, b, r = safe_request("GET", CLUSTER_TELEMETRY_URL, params=params, timeout=15)
        print(f"[{label}] params={params} status={s} raw={str(r)[:300]}")
        if s <= 0:
            v = healthz_ladder(label)
            if v:
                findings.append((1, v))
                break
            findings.append((3, f"SCRIPT-ERROR-transport: '{label}' transport failure with healthy /healthz"))
            break
        if 500 <= s <= 599:
            v = healthz_ladder(label)
            findings.append((1, v if v else f"Type3_RuntimeFailure: '{label}' got {s} with /healthz alive; body: {str(r)[:200]}"))
            continue
        if expected == "4xx":
            if 200 <= s <= 299:
                findings.append((0, f"Type1_IllegalSuccess: '{label}' ACCEPTED with {s} — constraint asserts "
                                    f"'timeout default 60, minimum 1' (below-minimum value must be rejected); "
                                    f"raw: {str(r)[:200]}"))
            elif 400 <= s <= 499:
                print(f"[conform] '{label}' rejected with {s}")
            else:
                findings.append((3, f"SCRIPT-ERROR-status: '{label}' uninterpreted status {s}"))
        else:  # positive closure leg
            if 400 <= s <= 499:
                findings.append((2, f"Type4 disposition conflict: '{label}' (documented-legal closure value) "
                                    f"rejected with {s}; raw: {str(r)[:200]}"))
            elif 200 <= s <= 299:
                node = parse_body(r, b)
                bad = envelope_violations(node)
                if bad:
                    findings.append((2, f"Type4_StateLogicViolation: '{label}' 200 but envelope broken: "
                                        f"{'; '.join(bad)}; raw: {str(r)[:200]}"))
                else:
                    print(f"[conform] '{label}' 200 with documented envelope + result.collections object")
            else:
                findings.append((3, f"SCRIPT-ERROR-status: '{label}' uninterpreted status {s}"))

    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR — {msg}")
        else:
            print(f"VERDICT: DEFECT_FOUND ({msg})")
        return
    print("OK: all positive closure legs 2xx with documented envelope; all below-minimum legs 4xx")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
