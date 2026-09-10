#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_telemetry_005
# strategy: metamorphic
# endpoint: telemetry
# constraint_ids: qdrant_type_telemetry_001, qdrant_behavioral_cluster_telemetry_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/telemetry
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - a documented transform (anonymize,
#   verbosity) that silently changes the response STRUCTURE, not just the
#   values) + G9 cross-face consistency (two telemetry faces disagreeing
#   about the same cluster state)
"""
Attack: metamorphic x constraints::qdrant_type_telemetry_001 +
  assertions::qdrant_behavioral_cluster_telemetry_001 (GET /telemetry and
  GET /cluster/telemetry, URLs from raw_knowledge api_endpoints[].url).
  Metamorphic relations on the 9-section TelemetryData shape (the shape
  oracle was cross-checked against the endpoints' OpenAPI response_shape
  grids per the R8 lesson):
    M1 anonymize invariance: GET /telemetry?details_level=10&anonymize=true
       vs ?details_level=10&anonymize=false - identical inputs except the
       flag; anonymization is a VALUE transform (redact identifiers), not a
       STRUCTURE transform, so the set of result sections must be exactly
       identical (and still cover all 9 documented sections). A section
       dropped or added by anonymize = Type4: monitoring dashboards keyed
       on section presence break the moment someone enables anonymization.
    M2 verbosity preservation: details_level=0 vs details_level=10 - more
       verbosity may ADD nested detail (even extra top-level keys), but the
       9 documented top-level sections are asserted by the type constraint
       WITHOUT a level qualifier, so each level must still CONTAIN all 9
       (a documented section missing at either level = Type4; asymmetry
       beyond the 9 is printed informationally and not judged, since
       additive detail at higher verbosity is by-design).
    M3 cross-face agreement: GET /cluster/telemetry vs GET /telemetry both
       expose result.cluster.enabled (boolean in both endpoints'
       response_shape grids); when both faces serve 200 the two booleans
       must agree - they describe the same underlying cluster state
       (disagreement = G9 inconsistent disposition = Type4). If the cluster
       face refuses 4xx (disabled family per R6-R8), the leg is honestly
       skipped.
  [coverage: metamorphic x qdrant_type_telemetry_001 (anonymize/verbosity
   structure invariance) + qdrant_behavioral_cluster_telemetry_001
   (cross-face cluster.enabled agreement)]
Oracle: M1 - the result section sets of anonymize=true and anonymize=false
  at details_level=10 are exactly identical and both contain all 9 sections
  (differing sets = Type4_StateLogicViolation); M2 - details_level=0 and
  details_level=10 both return 200 with all 9 documented sections present
  (a missing documented section at either level = Type4_StateLogicViolation;
  extra additive keys are not judged); M3 - when GET /cluster/telemetry
  answers 200, its result.cluster.enabled equals /telemetry's
  result.cluster.enabled (disagreement = Type4_StateLogicViolation); 5xx on
  any leg with /healthz alive = Type3_RuntimeFailure; 4xx on a plain
  /telemetry leg = Type1_IllegalRejection (constraints
  qdrant_type_telemetry_001, qdrant_behavioral_cluster_telemetry_001).

Rationale (G6/G7): the three relations are pure follow-up checks on the
one documented read surface - each transform (anonymize flag, verbosity
level, sibling telemetry face) is SPECIFIED to change values/granularity
only, so structural divergence on the documented sections is unambiguously
a violation without needing to know the exact values; M1 is the maximal
breaker because anonymize is the transform most likely implemented by a
second serializer that quietly skips fields it cannot redact.
"""

import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p)
            break
if not _sd or not Path(_sd, "runtime", "__init__.py").exists():
    print("VERDICT: SCRIPT_ERROR - runtime scripts dir not found (TESTVDB_SCRIPTS_DIR unset)")
    sys.exit(2)
sys.path.insert(0, _sd)

if not os.environ.get("TESTVDB_TARGET"):
    for _p in Path(__file__).resolve().parents:
        _c = _p / "structured_contract.json"
        if _c.exists():
            try:
                _t = json.loads(_c.read_text(encoding="utf-8")).get("target", "")
                if _t:
                    os.environ["TESTVDB_TARGET"] = str(_t).lower()
            except Exception:
                pass
            break

if os.environ.get("TESTVDB_TARGET", "").lower() != "qdrant":
    print(f"VERDICT: SCRIPT_ERROR - contract target mismatch (expected qdrant, got {os.environ.get('TESTVDB_TARGET')!r})")
    sys.exit(2)

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

if not os.environ.get("TESTVDB_DB_URL"):
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

# ---- runtime PATHS gap: register the contract-derived URLs (raw_knowledge only) ----
TELEMETRY_KEY = "telemetry"
if TELEMETRY_KEY not in rt.PATHS:
    rt.PATHS[TELEMETRY_KEY] = "/telemetry"
CLUSTER_TELEMETRY_KEY = "cluster_telemetry"
if CLUSTER_TELEMETRY_KEY not in rt.PATHS:
    rt.PATHS[CLUSTER_TELEMETRY_KEY] = "/cluster/telemetry"
print(f"[path derivation] telemetry = {rt.PATHS[TELEMETRY_KEY]} "
      f"(raw_knowledge api_endpoints[telemetry].url)")
print(f"[path derivation] cluster_telemetry = {rt.PATHS[CLUSTER_TELEMETRY_KEY]} "
      f"(raw_knowledge api_endpoints[cluster+telemetry].url)")

SECTIONS = ["id", "app", "collections", "cluster", "requests", "memory",
            "hardware", "search_pool", "quota"]


def safe_request(method, path_key, body=None, path_params=None, query_params=None,
                timeout=30):
    """All HTTP through the runtime; forwards method/path_key/body/path_params/
    query_params/timeout exactly (standing lesson). Returns (status, raw_text)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def jload(raw):
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz")
    print(f"[{tag}] /healthz probe status={hs} raw={str(hraw)[:120]}")
    return hs


def read_200(path_key, query_params, tag):
    """Read a face leg; enforce the 200 expectation with typed failures.
    Returns the result node (dict)."""
    st, raw = safe_request("GET", path_key, query_params=query_params, timeout=35)
    print(f"[{tag}] status={st} raw={str(raw)[:300]}")
    if st == 0:
        liveness(f"{tag} transport")
        script_error(f"transport failure on {tag}; no defect conclusion")
    if 500 <= st <= 599:
        if liveness(f"{tag} 5xx") != 200:
            script_error(f"{tag} 5xx ({st}) and /healthz not 200; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"{tag} raised server error {st} while /healthz is alive; the telemetry "
               f"read faces are documented 200 reads, never crashes; raw={str(raw)[:200]}")
    if 400 <= st < 500:
        defect("Type1_IllegalRejection",
               f"{tag} refused with {st}; every leg in this matrix is a documented-legal "
               f"read (anonymize/per_collection booleans, details_level within 0..10, or "
               f"a plain read of a documented 200 face per constraints "
               f"qdrant_type_telemetry_001 / qdrant_behavioral_cluster_telemetry_001); "
               f"raw={str(raw)[:250]}")
    if not (200 <= st < 300):
        script_error(f"unexpected status {st} on {tag}; no defect conclusion")
    b = jload(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        defect("Type4_StateLogicViolation",
               f"{tag} answered 200 but the result node is missing/not an object "
               f"(got {res!r}); the TelemetryData envelope must hold on every leg; "
               f"raw={str(raw)[:250]}")
    return res


def section_set(res, tag):
    keys = set(res.keys())
    missing = [s for s in SECTIONS if s not in keys]
    if missing:
        defect("Type4_StateLogicViolation",
               f"{tag}: result is missing documented TelemetryData section(s) {missing} "
               f"(present={sorted(keys)}); constraint qdrant_type_telemetry_001 asserts "
               f"id, app, collections, cluster, requests, memory, hardware, search_pool, "
               f"quota sections without any verbosity/anonymize qualifier")
    return keys


def cluster_enabled(res, tag):
    cluster = res.get("cluster")
    if not isinstance(cluster, dict):
        defect("Type4_StateLogicViolation",
               f"{tag}: result.cluster missing or not an object (got {cluster!r}); both "
               f"telemetry response_shapes declare a result.cluster node")
    enabled = cluster.get("enabled")
    if not isinstance(enabled, bool):
        defect("Type4_StateLogicViolation",
               f"{tag}: result.cluster.enabled is not a boolean (got {enabled!r}); both "
               f"telemetry response_shapes declare result.cluster.enabled:boolean")
    return enabled


def main():
    hs, hraw = safe_request("GET", "healthz")
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")

    # ---- M1: anonymize is a value transform, not a structure transform ----
    res_anon = read_200(TELEMETRY_KEY, {"details_level": 10, "anonymize": True},
                        "M1 GET /telemetry?details_level=10&anonymize=true")
    keys_anon = section_set(res_anon, "M1 anonymize=true")
    res_plain = read_200(TELEMETRY_KEY, {"details_level": 10, "anonymize": False},
                         "M1 GET /telemetry?details_level=10&anonymize=false")
    keys_plain = section_set(res_plain, "M1 anonymize=false")
    print(f"[M1] section sets: anonymized={sorted(keys_anon)} plain={sorted(keys_plain)}")
    if keys_anon != keys_plain:
        defect("Type4_StateLogicViolation",
               f"M1 anonymize structure drift: the documented anonymize flag redacts "
               f"VALUES but the result section set changed between anonymize=true "
               f"({sorted(keys_anon)}) and anonymize=false ({sorted(keys_plain)}) on "
               f"otherwise identical requests; dashboards keyed on section presence "
               f"break when anonymization is enabled (constraint "
               f"qdrant_type_telemetry_001)")

    # ---- M2: verbosity adds detail but must not drop documented top-level sections ----
    res_l0 = read_200(TELEMETRY_KEY, {"details_level": 0}, "M2 GET /telemetry?details_level=0")
    keys_l0 = section_set(res_l0, "M2 details_level=0")
    asym = keys_l0.symmetric_difference(keys_plain)
    print(f"[M2] details_level=0 sections={sorted(keys_l0)} vs details_level=10 "
          f"sections={sorted(keys_plain)}; additive asymmetry (informational, "
          f"not judged)={sorted(asym)}")
    # the 9-section presence itself is enforced inside section_set on both levels;
    # extra additive keys at higher verbosity are by-design detail, not a violation

    # ---- M3: cross-face agreement on the same cluster state ----
    enabled_service = cluster_enabled(res_plain, "M3 /telemetry (details_level=10)")
    cst, craw = safe_request("GET", CLUSTER_TELEMETRY_KEY, timeout=35)
    print(f"[M3 GET /cluster/telemetry control] status={cst} raw={str(craw)[:300]}")
    if cst == 0:
        liveness("M3 transport")
        script_error("transport failure on GET /cluster/telemetry; no defect conclusion")
    if 500 <= cst <= 599:
        if liveness("M3 5xx") != 200:
            script_error(f"GET /cluster/telemetry 5xx ({cst}) and /healthz not 200")
        defect("Type3_RuntimeFailure",
               f"GET /cluster/telemetry raised server error {cst} while /healthz is "
               f"alive; assertion qdrant_behavioral_cluster_telemetry_001 documents a "
               f"200 read (or a clean deployment refusal), never a crash; "
               f"raw={str(craw)[:200]}")
    if 200 <= cst < 300:
        b = jload(craw)
        cres = b.get("result") if isinstance(b, dict) else None
        if not isinstance(cres, dict):
            defect("Type4_StateLogicViolation",
                   f"GET /cluster/telemetry answered 200 but the result node is "
                   f"missing/not an object; raw={str(craw)[:250]}")
        enabled_cluster = cluster_enabled(cres, "M3 /cluster/telemetry")
        print(f"[M3] cluster.enabled: /cluster/telemetry={enabled_cluster} "
              f"/telemetry={enabled_service}")
        if enabled_cluster != enabled_service:
            defect("Type4_StateLogicViolation",
                   f"M3 cross-face disagreement: /cluster/telemetry reports "
                   f"result.cluster.enabled={enabled_cluster} while /telemetry reports "
                   f"result.cluster.enabled={enabled_service} on the same deployment - "
                   f"both faces describe the same underlying cluster state "
                   f"(G9 inconsistent disposition across the telemetry face family)")
    elif 400 <= cst < 500:
        print(f"[M3] SKIPPED: /cluster/telemetry refuses with {cst} (disabled face "
              f"family per R6-R8); the cross-face comparison leg is honestly skipped - "
              f"the face-level disposition itself is judged by "
              f"semantic_cluster_telemetry_001")
    else:
        script_error(f"unexpected GET /cluster/telemetry status {cst}; no defect conclusion")

    print(f"[summary] M1 anonymize structure-invariant (sections identical); M2 all 9 "
          f"documented sections present at verbosity 0 and 10; M3 cross-face "
          f"cluster.enabled agreement checked (service face reports "
          f"enabled={enabled_service})")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
