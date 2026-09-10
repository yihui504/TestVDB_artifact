#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_telemetry_001
# strategy: behavioral_contract
# endpoint: cluster+telemetry
# constraint_ids: qdrant_behavioral_cluster_telemetry_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-telemetry
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the documented "200 TelemetryData" read face
#   vs the disposition this standalone deployment actually serves; mutating distributed
#   faces refused with 400 "Distributed mode disabled" in R6-R8)
"""
Attack: behavioral_contract x assertions::qdrant_behavioral_cluster_telemetry_001
  (chunk_cluster+telemetry; GET /cluster/telemetry, URL from raw_knowledge
  api_endpoints[cluster+telemetry].url, registered into runtime PATHS per the
  session PATHS-gap convention). The assertion (evidence_tier=explicit) promises
  "HTTP 200 with telemetry payload (id, app, collections, cluster, requests,
  memory, hardware, search_pool, quota)". Two dispositions are falsifiable on
  this deployment:
    (200 branch) the face serves 200 -> the envelope and the shape oracle from
        this endpoint's own response_shape must hold: {time: number,
        status: string, result: object}, result.collections object,
        result.cluster.enabled boolean, result.cluster.number_of_peers
        integer|null, result.cluster.peers object. The shape oracle was
        cross-checked against the endpoint's versioned OpenAPI response_shape
        grid before being written (R8 lesson: never assert a field list that
        exists in no published OpenAPI).
    (4xx branch) the face refuses like its mutating siblings -> the refusal
        must be a clean 4xx (never 5xx), repeatable on an immediate re-read
        (consistent disposition), and COHERENT with the sibling service
        telemetry face: GET /telemetry must still answer 200 and its
        result.cluster.enabled (boolean per that endpoint's response_shape)
        must agree with the refusal story (enabled=false on a deployment whose
        cluster telemetry face is disabled). /telemetry reporting
        cluster.enabled=true while /cluster/telemetry refuses "Distributed
        mode disabled" is a G9 inconsistent disposition across the telemetry
        face family = Type4.
  [chunk_cluster+telemetry coverage: behavioral_contract x
   qdrant_behavioral_cluster_telemetry_001 (documented 200 face + envelope +
   cluster-shape oracle + disabled-branch coherence)]
Oracle: GET /cluster/telemetry answers 200 with envelope status:string,
  time:number, result:object and result.cluster.enabled boolean +
  result.cluster.number_of_peers int|null + result.cluster.peers object +
  result.collections object (any violation = Type4_StateLogicViolation; a 5xx
  with /healthz alive = Type3_RuntimeFailure); on a 4xx refusal branch: clean
  repeatable 4xx, /healthz still 200, GET /telemetry still 200 with
  result.cluster.enabled=false, else Type4_StateLogicViolation (assertion
  qdrant_behavioral_cluster_telemetry_001).

Rationale (G4/G7): the promise splits into the status class and the payload
shape; both halves are spec-derived (assertion text + this endpoint's
OpenAPI response_shape) and each observed (status, raw) pair is compared
against the declared expectation explicitly, with the disabled branch judged
on coherence instead of being silently skipped.
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
CLUSTER_TELEMETRY_KEY = "cluster_telemetry"
if CLUSTER_TELEMETRY_KEY not in rt.PATHS:
    rt.PATHS[CLUSTER_TELEMETRY_KEY] = "/cluster/telemetry"
TELEMETRY_KEY = "telemetry"
if TELEMETRY_KEY not in rt.PATHS:
    rt.PATHS[TELEMETRY_KEY] = "/telemetry"
print(f"[path derivation] cluster_telemetry = {rt.PATHS[CLUSTER_TELEMETRY_KEY]} "
      f"(raw_knowledge api_endpoints[cluster+telemetry].url)")
print(f"[path derivation] telemetry = {rt.PATHS[TELEMETRY_KEY]} "
      f"(raw_knowledge api_endpoints[telemetry].url)")


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


def result_node(raw):
    b = jload(raw)
    r = b.get("result") if isinstance(b, dict) else None
    return r


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


def check_envelope(st, raw, tag):
    """200 envelope per this endpoint's response_shape: {time: number,
    status: string, result: object}. Returns result node or defects."""
    b = jload(raw)
    if not isinstance(b, dict):
        defect("Type4_StateLogicViolation",
               f"[{tag}] 200 body is not a JSON object: raw={str(raw)[:200]}; the documented "
               f"200 TelemetryData face requires the qdrant envelope object")
    env_status = b.get("status")
    if not isinstance(env_status, str):
        defect("Type4_StateLogicViolation",
               f"[{tag}] envelope field 'status' missing or not a string (got {env_status!r}); "
               f"response_shape declares status:string; raw={str(raw)[:250]}")
    env_time = b.get("time")
    if env_time is not None and not (isinstance(env_time, (int, float))
                                     and not isinstance(env_time, bool)):
        defect("Type4_StateLogicViolation",
               f"[{tag}] envelope field 'time' present but not numeric (got {env_time!r}); "
               f"response_shape declares time:number; raw={str(raw)[:250]}")
    res = b.get("result")
    if not isinstance(res, dict):
        defect("Type4_StateLogicViolation",
               f"[{tag}] envelope field 'result' missing or not an object (got {type(res).__name__}); "
               f"response_shape declares result:object; raw={str(raw)[:250]}")
    return res


def check_cluster_shape(res, tag):
    """cluster section shape per this endpoint's response_shape grid."""
    cluster = res.get("cluster")
    if not isinstance(cluster, dict):
        defect("Type4_StateLogicViolation",
               f"[{tag}] result.cluster missing or not an object (got {cluster!r}); assertion "
               f"qdrant_behavioral_cluster_telemetry_001 promises a cluster telemetry payload; "
               f"response_shape declares result.cluster with enabled/number_of_peers/peers; "
               f"result keys={sorted(res.keys())}")
    enabled = cluster.get("enabled")
    if not isinstance(enabled, bool):
        defect("Type4_StateLogicViolation",
               f"[{tag}] result.cluster.enabled is not a boolean (got {enabled!r}); "
               f"response_shape declares result.cluster.enabled:boolean")
    npeers = cluster.get("number_of_peers")
    if npeers is not None and not (isinstance(npeers, int) and not isinstance(npeers, bool)):
        defect("Type4_StateLogicViolation",
               f"[{tag}] result.cluster.number_of_peers is not integer|null (got {npeers!r}); "
               f"response_shape declares result.cluster.number_of_peers:[integer, null]")
    peers = cluster.get("peers")
    if peers is not None and not isinstance(peers, dict):
        defect("Type4_StateLogicViolation",
               f"[{tag}] result.cluster.peers is not an object (got {peers!r}); "
               f"response_shape declares result.cluster.peers:object")
    colls = res.get("collections")
    if not isinstance(colls, dict):
        defect("Type4_StateLogicViolation",
               f"[{tag}] result.collections missing or not an object (got {colls!r}); "
               f"response_shape declares result.collections:object; "
               f"result keys={sorted(res.keys())}")
    return enabled


def main():
    hs, hraw = safe_request("GET", "healthz")
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")

    # ---- control read of the documented face ----
    st, raw = safe_request("GET", CLUSTER_TELEMETRY_KEY, timeout=35)
    print(f"[control GET /cluster/telemetry] status={st} raw={str(raw)[:400]}")
    if st == 0:
        liveness("transport")
        script_error("transport failure on GET /cluster/telemetry; no defect conclusion")
    if 500 <= st <= 599:
        if liveness("5xx") != 200:
            script_error(f"GET /cluster/telemetry 5xx ({st}) and /healthz not 200; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"GET /cluster/telemetry raised server error {st} while /healthz is alive; assertion "
               f"qdrant_behavioral_cluster_telemetry_001 expects a documented 200 read (or a clean "
               f"deployment refusal), never a crash; raw={str(raw)[:200]}")

    if 200 <= st < 300:
        # ---- 200 branch: the documented face is served -> shape oracle ----
        res = check_envelope(st, raw, "control")
        enabled = check_cluster_shape(res, "control")
        st2, raw2 = safe_request("GET", CLUSTER_TELEMETRY_KEY, timeout=35)
        print(f"[repeat GET /cluster/telemetry] status={st2} raw={str(raw2)[:400]}")
        if st2 != st:
            defect("Type4_StateLogicViolation",
                   f"the documented 200 face flipped status {st} -> {st2} between two adjacent "
                   f"reads on an idle deployment; raw={str(raw2)[:250]}")
        res2 = check_envelope(st2, raw2, "repeat")
        check_cluster_shape(res2, "repeat")
        # cross-face coherence: the service telemetry face must agree on cluster.enabled
        tst, traw = safe_request("GET", TELEMETRY_KEY, timeout=35)
        print(f"[sibling GET /telemetry] status={tst} raw={str(traw)[:200]}")
        if tst == 200:
            tres = result_node(traw)
            tcluster = tres.get("cluster") if isinstance(tres, dict) else None
            tenabled = tcluster.get("enabled") if isinstance(tcluster, dict) else None
            if isinstance(tenabled, bool) and tenabled != enabled:
                defect("Type4_StateLogicViolation",
                       f"G9 inconsistent disposition across the telemetry face family: "
                       f"/cluster/telemetry reports result.cluster.enabled={enabled} while "
                       f"/telemetry reports result.cluster.enabled={tenabled} on the same "
                       f"deployment; both faces describe the same underlying cluster state")
        print(f"[summary] documented 200 face served; envelope + cluster shape oracle hold "
              f"(cluster.enabled={enabled}); repeat read stable")
        print("VERDICT: NO_DEFECT")
        return

    if 400 <= st < 500:
        # ---- disabled-family refusal branch (R6-R8 precedent): judge coherence ----
        print("[disposition] cluster telemetry face refused with 4xx like the mutating "
              "distributed faces (R6-R8 family); judging the refusal class + coherence")
        st2, raw2 = safe_request("GET", CLUSTER_TELEMETRY_KEY, timeout=35)
        print(f"[repeat GET /cluster/telemetry] status={st2} raw={str(raw2)[:300]}")
        if not (400 <= st2 < 500):
            defect("Type4_StateLogicViolation",
                   f"inconsistent disposition on the refused cluster telemetry face: {st} -> {st2} "
                   f"between two adjacent no-param reads; a disabled face must refuse uniformly")
        hs2 = liveness("post-refusal")
        if hs2 != 200:
            defect("Type3_RuntimeFailure",
                   f"/healthz returned {hs2} after a refused GET /cluster/telemetry ({st}); a "
                   f"read refusal must leave the service alive")
        tst, traw = safe_request("GET", TELEMETRY_KEY, timeout=35)
        print(f"[sibling GET /telemetry] status={tst} raw={str(traw)[:300]}")
        if tst != 200:
            defect("Type4_StateLogicViolation",
                   f"the sibling service telemetry face GET /telemetry answers {tst} while "
                   f"/cluster/telemetry refuses {st}; the telemetry face family must degrade "
                   f"coherently (the service-level face is not distributed-mode-dependent); "
                   f"raw={str(traw)[:250]}")
        tres = result_node(traw)
        tcluster = tres.get("cluster") if isinstance(tres, dict) else None
        tenabled = tcluster.get("enabled") if isinstance(tcluster, dict) else None
        print(f"[coherence] /telemetry result.cluster.enabled={tenabled!r}")
        if isinstance(tenabled, bool) and tenabled is True:
            defect("Type4_StateLogicViolation",
                   f"G9 incoherent refusal: /cluster/telemetry refuses {st} "
                   f"(distributed-mode family) while /telemetry reports "
                   f"result.cluster.enabled=true - a deployment with clustering enabled must "
                   f"serve the cluster telemetry read; raw={str(raw)[:200]}")
        print("[summary] refused 4xx cleanly and repeatably; /healthz alive; /telemetry 200 "
              "with cluster.enabled agreeing with the disabled face (deployment-conditional "
              "disposition per R6-R8 family; no shape claim to judge)")
        print("VERDICT: NO_DEFECT")
        return

    script_error(f"unexpected GET /cluster/telemetry status {st}; no defect conclusion")


if __name__ == "__main__":
    main()
