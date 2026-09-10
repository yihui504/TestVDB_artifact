#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary attack on the DOCUMENTED RESPONSE GRID of
  telemetry (GET /telemetry) x qdrant_type_telemetry_001 (evidence_tier
  explicit). The constraint's assertion, quoted verbatim:
    "response contains id, app, collections, cluster, requests, memory,
     hardware, search_pool, quota sections"
  R8-lesson cross-check performed BEFORE writing this oracle: the versioned
  v-1-18-x OpenAPI (local shard) declares result = TelemetryData with exactly
  these 9 properties — the constraint grid EXISTS in the published spec (no
  R8-style phantom grid). Required-list nuance baked into the claim tiers:
  the published schema marks ONLY {id, collections} required; the other 7
  sections are properties of TelemetryData but not schema-required. Claim
  tiers (declare-first):
    tier-1 (double-anchored: constraint text + schema required + contract
      response_shape): id present as string; collections present as object
      (with number_of_collections integer — required by CollectionsTelemetry
      schema and typed in contract response_shape);
    tier-2 (constraint-text-anchored, judge-annotated): each of the other 7
      sections present — absence violates the constraint assertion verbatim;
      NOTE(judge): published schema marks them optional (skip_serializing
      possibility), so a tier-2 hit may adjudicate by-design.
  Envelope (published Service_telemetry_Response_200 + contract
  response_shape): status:string, time:number, result:object — hard-claimed.
[coverage: /telemetry endpoint of this round per dispatch NOTE ('/telemetry
 IS in the contract and IS attackable — attack it normally'; it sits in the
 doc_coverage exclude prefixes for ACCOUNTING only); strategy2
 response-grid x qdrant_type_telemetry_001; strategy1 param domain of the
 same endpoint is covered by boundary_telemetry_002]
Oracle: documented GET /telemetry -> exactly 200 with envelope
  status:string + time:number + result:object; result.id present as string
  and result.collections present as object with number_of_collections
  integer -> violation = DEFECT_FOUND (Type4_StateLogicViolation,
  double-anchored); any of the 7 remaining documented sections absent =
  DEFECT_FOUND (Type4_StateLogicViolation vs the constraint's verbatim
  'response contains ... sections', judge-annotated that the published
  schema marks them optional); non-200 = DEFECT (Type4 disposition; 5xx
  rechecked via /healthz -> Type3 if it stands or service-down Type3);
  transport failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_type_telemetry_001
Blindspot: BS-01 Parameter Type Coercion Trust mirrored to the response
  side (serde serialization trusted to always emit the documented sections;
  a skip_serializing_if default that drops a documented section silently is
  the same optimism on the emit path)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/telemetry
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


TELEMETRY_URL = derive_url("telemetry")
if not TELEMETRY_URL:
    print("VERDICT: SCRIPT_ERROR — url not derivable from raw_knowledge api_endpoints[].url (telemetry)")
    sys.exit(2)
print(f"[url-derived] telemetry -> {TELEMETRY_URL}")

# The 9 documented sections, verbatim from the constraint assertion.
ALL_SECTIONS = ("id", "app", "collections", "cluster", "requests",
                "memory", "hardware", "search_pool", "quota")
TIER2_SECTIONS = ("app", "cluster", "requests", "memory", "hardware", "search_pool", "quota")


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
    print(f"ownership tag: btl1-{tag}")
    print("[constraint quote] response contains id, app, collections, cluster, requests, "
          "memory, hardware, search_pool, quota sections")
    print("[R8-lesson cross-check] published TelemetryData schema properties == the 9 "
          "constraint sections (grid EXISTS in spec); required list = [id, collections] "
          "-> claim tiers declared accordingly")

    s, b, r = safe_request("GET", TELEMETRY_URL, timeout=15)
    print(f"[documented GET {TELEMETRY_URL}] status={s} raw={str(r)[:400]}")

    if s <= 0:
        v = healthz_ladder("documented GET /telemetry")
        if v:
            print(f"VERDICT: DEFECT_FOUND ({v})")
        else:
            print("VERDICT: SCRIPT_ERROR — transport failure with healthy /healthz (no defect conclusion)")
        return
    if 500 <= s <= 599:
        v = healthz_ladder("documented GET /telemetry")
        print(f"VERDICT: DEFECT_FOUND ({v})" if v else
              f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — documented GET /telemetry got "
              f"{s} with /healthz alive; body: {str(r)[:200]}")
        return

    try:
        node = json.loads(r) if isinstance(r, str) else (b if isinstance(b, dict) else {})
    except Exception:
        node = {}

    envelope_bad = []
    if not isinstance(node.get("status"), str):
        envelope_bad.append(f"envelope status not a string (got {node.get('status')!r})")
    if not (isinstance(node.get("time"), (int, float)) and not isinstance(node.get("time"), bool)):
        envelope_bad.append(f"envelope time not a number (got {node.get('time')!r})")
    result = node.get("result")
    if not isinstance(result, dict):
        envelope_bad.append(f"envelope result not an object (got {type(result).__name__})")
    if envelope_bad:
        if not (200 <= s <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type4 disposition conflict) — documented GET /telemetry "
                  f"returned {s} on the 200-only face; body: {str(r)[:200]}")
            return
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — envelope broken: "
              f"{'; '.join(envelope_bad)}; raw: {str(r)[:250]}")
        return
    if not (200 <= s <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type4 disposition conflict) — documented GET /telemetry "
              f"returned {s} on the 200-only face; body: {str(r)[:200]}")
        return

    tier1_bad = []
    if not isinstance(result.get("id"), str):
        tier1_bad.append(f"result.id not a string (got {result.get('id')!r}:{type(result.get('id')).__name__}) "
                         f"[constraint text + schema required + response_shape result.id:string]")
    coll = result.get("collections")
    if not isinstance(coll, dict):
        tier1_bad.append(f"result.collections not an object (got {type(coll).__name__}) "
                         f"[constraint text + schema required]")
    else:
        noc = coll.get("number_of_collections")
        if not (isinstance(noc, int) and not isinstance(noc, bool)):
            tier1_bad.append(f"result.collections.number_of_collections not an integer (got {noc!r}) "
                             f"[CollectionsTelemetry required + response_shape integer]")
    print(f"[grid verdicts] tier1 (double-anchored) violations={tier1_bad or 'none'}")

    tier2_missing = [sec for sec in TIER2_SECTIONS if sec not in result]
    print(f"[grid verdicts] tier2 (constraint-text-anchored) missing sections={tier2_missing or 'none'}")
    extras = sorted(set(result.keys()) - set(ALL_SECTIONS))
    print(f"[grid mirror] undocumented extra sections in result: {extras or 'none'}")

    if tier1_bad:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 payload of telemetry violates "
              f"the explicit type constraint qdrant_type_telemetry_001 (assertion: 'response contains "
              f"id, app, collections, cluster, requests, memory, hardware, search_pool, quota "
              f"sections') on the double-anchored tier: {'; '.join(tier1_bad)}; measured "
              f"result keys={sorted(result.keys())}; raw head={str(r)[:200]}")
        return
    if tier2_missing:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 payload of telemetry violates "
              f"the explicit type constraint qdrant_type_telemetry_001: documented sections missing: "
              f"{tier2_missing}; measured result keys={sorted(result.keys())}; raw head={str(r)[:200]}. "
              f"NOTE(judge): the published v-1-18-x TelemetryData schema marks these 7 sections as "
              f"properties-but-not-required (only id+collections are required) — a skip_serializing_if "
              f"style omission may adjudicate by-design; recorded per R8 source-doubt discipline, "
              f"not silently absorbed")
        return

    print("OK: 200 + envelope + all 9 documented sections present with tier-1 types conforming")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
