#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 response-shape attack (G4 both directions) on
  cluster+telemetry (GET /cluster/telemetry) x the positive payload face of
  qdrant_behavioral_cluster_telemetry_001 (evidence_tier explicit), whose
  expected_behavior, quoted verbatim:
    "HTTP 200 with telemetry payload (id, app, collections, cluster, requests,
     memory, hardware, search_pool, quota)"
  R8-lesson cross-check performed BEFORE writing this oracle (the exact
  discipline R8 learned the hard way): the versioned v-1-18-x OpenAPI (local
  shard) declares the 200 response of /cluster/telemetry as
  {usage(oneOf Usage|any), time:number, status:string,
   result: DistributedTelemetryData} with DistributedTelemetryData =
  {collections*: object (REQUIRED), cluster: oneOf(DistributedClusterTelemetry
  {enabled*:boolean, number_of_peers:int|null, peers*:object} | ANY)}.
  Consequences baked into the oracle (no phantom grid):
  - the 7 extra sections of the behavioral parenthetical (id, app, requests,
    memory, hardware, search_pool, quota) are the SERVICE /telemetry
    TelemetryData list; per D3b "spec-derived field wins", they are NOT
    claimed here — their measured absence is recorded as a
    description-vs-spec divergence for the judge, not a defect claim;
  - result.cluster is OPTIONAL and its inner shape has a legal any-variant
    (R8 oneOf-variant lesson): presence/shape of cluster/enabled/peers is
    measured and recorded, never claimed;
  - hard claims only on the doubly-corroborated grid: 200 disposition +
    envelope {status:string, time:number, result:object} + result.collections
    present as object (REQUIRED in the published spec AND named in the
    behavioral promise).
  Legs: the documented no-param call, and the documented details_level=0
  call form — the payload promise must hold on both.
[chunk_cluster+telemetry coverage: strategy2 response-grid x
 qdrant_behavioral_cluster_telemetry_001 positive face; the same unit's
 200-disposition face is exercised here, its parameter domain in
 boundary_cluster_telemetry_005]
Oracle: documented GET /cluster/telemetry (no params and with
  details_level=0) -> exactly 200 with envelope status:string + time:number +
  result:object + result.collections:object — non-200 = DEFECT_FOUND (Type4
  disposition conflict; 5xx rechecked via /healthz then Type3 if it stands or
  service-down Type3), missing/mistyped result.collections = DEFECT_FOUND
  (Type4_StateLogicViolation vs published-spec REQUIRED field + behavioral
  promise), envelope violation = DEFECT_FOUND (Type4); the 7 service-only
  sections and the cluster-section inner shape are recorded as judge notes
  and NEVER claimed; transport failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_behavioral_cluster_telemetry_001
Blindspot: BS-04 Boundary Default Optimism (a deployment-mode default that
  silently shrinks the 200 payload below the published REQUIRED grid)
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

# Sections of the behavioral parenthetical that belong to the SERVICE
# /telemetry TelemetryData schema, not to the published
# DistributedTelemetryData of this endpoint (R8-lesson cross-check).
SERVICE_ONLY_SECTIONS = ("id", "app", "requests", "memory", "hardware", "search_pool", "quota")


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


def parse_body(raw, body):
    try:
        return json.loads(raw) if isinstance(raw, str) else (body if isinstance(body, dict) else {})
    except Exception:
        return {}


def adjudicate_leg(label, s, b, r):
    """Declare-first adjudication of one documented call form.
    Returns a (rank, message) finding or None when conforming;
    rank 0 = Type3, 1 = Type4, 2 = script-error."""
    if s <= 0:
        v = healthz_ladder(label)
        return (0, v) if v else (2, f"SCRIPT-ERROR-transport: '{label}' transport failure with healthy /healthz")
    if 500 <= s <= 599:
        v = healthz_ladder(label)
        return (0, v if v else f"Type3_RuntimeFailure: '{label}' got {s} with /healthz alive; body: {str(r)[:200]}")
    if not (200 <= s <= 299):
        if 400 <= s <= 499:
            return (1, f"Type4 disposition conflict: '{label}' returned {s} on the documented "
                      f"200-only face of cluster+telemetry; body: {str(r)[:200]}")
        return (2, f"SCRIPT-ERROR-status: '{label}' uninterpreted status {s}")

    node = parse_body(r, b)
    bad = []
    if not isinstance(node.get("status"), str):
        bad.append(f"status not a string (got {node.get('status')!r})")
    if not (isinstance(node.get("time"), (int, float)) and not isinstance(node.get("time"), bool)):
        bad.append(f"time not a number (got {node.get('time')!r})")
    result = node.get("result")
    if not isinstance(result, dict):
        bad.append(f"result not an object (got {type(result).__name__})")
        return (1, f"Type4_StateLogicViolation: '{label}' 200 but envelope broken: {'; '.join(bad)}; raw: {str(r)[:250]}")
    if not isinstance(result.get("collections"), dict):
        bad.append("result.collections not an object (REQUIRED per published OpenAPI "
                   "DistributedTelemetryData + named in the behavioral promise)")
    if bad:
        return (1, f"Type4_StateLogicViolation: '{label}' 200 but documented grid broken: "
                   f"{'; '.join(bad)}; raw: {str(r)[:250]}")

    # Judge-note material only (R8 oneOf-variant lesson — never claimed):
    cluster = result.get("cluster")
    if isinstance(cluster, dict):
        print(f"[judge-note] result.cluster present: enabled={cluster.get('enabled')!r} "
              f"(variant-typed boolean), peers={type(cluster.get('peers')).__name__} "
              f"(variant-typed object), number_of_peers={cluster.get('number_of_peers')!r} "
              f"— inner shape has a legal any-variant, recorded not claimed")
    else:
        print(f"[judge-note] result.cluster absent/non-dict ({cluster!r}) — OPTIONAL per "
              f"published spec (required list = [collections]); recorded not claimed")
    present_service_sections = [k for k in SERVICE_ONLY_SECTIONS if k in result]
    if present_service_sections:
        print(f"[judge-note] service-only sections unexpectedly present on this face: "
              f"{present_service_sections} (recorded)")
    else:
        print("[judge-note] the behavioral parenthetical's 7 service-only sections "
              f"{list(SERVICE_ONLY_SECTIONS)} are absent — matches the published "
              f"DistributedTelemetryData grid; description-vs-spec divergence of the "
              f"parenthetical itself is recorded for the judge (doc_consistency channel), "
              f"NOT claimed as a defect (spec-derived field wins per D3b)")
    usage = node.get("usage")
    print(f"[judge-note] envelope usage present={('usage' in node)} type={type(usage).__name__} "
          f"(oneOf Usage|any — recorded not claimed)")
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: bct4-{tag}")
    print("[expected_behavior quote] HTTP 200 with telemetry payload (id, app, collections, "
          "cluster, requests, memory, hardware, search_pool, quota)")
    print("[R8-lesson cross-check] published v-1-18-x OpenAPI 200 schema = envelope "
          "{usage,time,status,result} with result: DistributedTelemetryData "
          "{collections*:object, cluster:optional oneOf(...|any)} — hard claims only on "
          "the doubly-corroborated grid")

    findings = []
    legs = [
        ("documented no-param call", None),
        ("documented details_level=0 call form", {"details_level": 0}),
    ]
    for label, params in legs:
        s, b, r = safe_request("GET", CLUSTER_TELEMETRY_URL, params=params, timeout=15)
        print(f"[{label}] params={params} status={s} raw={str(r)[:350]}")
        f = adjudicate_leg(label, s, b, r)
        if f:
            findings.append(f)
        else:
            print(f"[conform] '{label}' 200 + envelope + result.collections object")

    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 2:
            print(f"VERDICT: SCRIPT_ERROR — {msg}")
        else:
            print(f"VERDICT: DEFECT_FOUND ({msg})")
        return
    print("OK: both documented call forms return 200 with the published-grid payload")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
