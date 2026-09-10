#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_status_002
# strategy: behavioral_contract
# endpoint: cluster+status
# constraint_ids: qdrant_type_cluster_status_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-status
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - asserted response shape vs the shape
#   actually served on the documented "valid on single-node" face) + BS-01
#   (response fields trusted to conform to the asserted types/enum)
"""
Attack: behavioral_contract/response-shape-typing x
  constraints::qdrant_type_cluster_status_001 (chunk_cluster+status; GET
  /cluster via runtime path_key cluster_status, URL "/cluster" from
  raw_knowledge api_endpoints[cluster+status].url; documented no-body control
  probe per R7 lesson). The constraint (type_constraint, endpoint level,
  evidence_tier=explicit) asserts the response fields: "peer_id uint64;
  raft_state IN {Leader, Follower, Candidate, PreCandidate, Terminated};
  commit_index uint64; peers map". raw_knowledge expected_responses for this
  face documents exactly one 200 shape ("ClusterStatus") - no alternative
  shape is documented anywhere in the contract or raw_knowledge (checked:
  expected_responses, schema string, data_types), and the sibling behavioral
  assertion promises this face valid on single-node deployments. R7 lesson:
  this is one of the few reachable cluster faces - shape assertions fully
  exercisable.
  [chunk_cluster+status coverage: response-shape typing x
   qdrant_type_cluster_status_001 (field set + uint64 domain + raft_state
   enum + peers map + zero-match no-alternative-shape leg)]
Oracle: on a 200 GET /cluster, the result node conforms to the asserted
  ClusterStatus field set - each present field among peer_id/commit_index is a
  non-negative int within the uint64 domain (bool excluded), raft_state is a
  string in the 5-value enum, peers is a JSON object (map); an enabled-shape
  result missing any of the four documented fields = Type4; a 200 result
  carrying NONE of the four asserted fields (an undocumented alternative
  shape) = Type4 shape violation of qdrant_type_cluster_status_001.

Rationale (G2/G5/D3b): the type constraint is the binding oracle for the
  response shape; per the spec-grounded oracle discipline the materialized
  spec-derived field list wins over any prose paraphrase. Every observed value
  is compared field-by-field against the asserted type/enum/domain with the
  expected-vs-actual pair printed; the zero-match leg reports the served shape
  verbatim (full raw body + observed keys) so downstream adjudication can
  weigh an undocumented standalone "disabled" variant defense against the
  explicit single-node promise in the sibling assertion.
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
            _sd = str(_p / "scripts")
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

print(f"[path derivation] cluster_status = {rt.PATHS['cluster_status']} "
      f"(raw_knowledge api_endpoints[cluster+status].url)")

# ---- contract-derived response shape oracle (constraint qdrant_type_cluster_status_001) ----
DOC_FIELDS = ("peer_id", "raft_state", "commit_index", "peers")
RAFT_ENUM = {"Leader", "Follower", "Candidate", "PreCandidate", "Terminated"}
UINT64_MAX = 2 ** 64 - 1


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
        return None


def is_uint64(v):
    """uint64 domain: int (not bool), 0 <= v <= 2^64-1."""
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= UINT64_MAX


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def main():
    hs, hraw = safe_request("GET", "healthz")
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable - no defect conclusion")

    # ---- control leg (R7 lesson: documented no-body probe anchors the matrix) ----
    st, raw = safe_request("GET", "cluster_status", timeout=15)
    print(f"[control GET /cluster] status={st} raw={str(raw)[:500]}")

    if st == 0:
        hs2, hraw2 = safe_request("GET", "healthz")
        print(f"[transport branch] inline /healthz probe status={hs2} raw={str(hraw2)[:80]}")
        script_error("transport failure on GET /cluster (status 0); no defect conclusion")
    if 500 <= st <= 599:
        hs2, hraw2 = safe_request("GET", "healthz")
        print(f"[5xx branch] inline /healthz probe status={hs2} raw={str(hraw2)[:80]}")
        script_error(f"GET /cluster {st} with /healthz {hs2}; face unserved - the 200-promise "
                     "break is owned by semantic_cluster_status_001; shape not assessable")
    if st != 200:
        script_error(f"GET /cluster answered {st}; the 200/disposition judgment is owned by "
                     "semantic_cluster_status_001; response shape not assessable here")

    b = jload(raw)
    if not isinstance(b, dict):
        script_error(f"200 body is not a JSON object: raw={str(raw)[:200]}; owned by "
                     "semantic_cluster_status_001")
    res = b.get("result")
    if not isinstance(res, dict):
        script_error(f"no result object in 200 body (result={res!r}); owned by "
                     "semantic_cluster_status_001")

    present = [f for f in DOC_FIELDS if f in res]
    print(f"[shape] asserted fields present in result: {present}; "
          f"all result keys: {sorted(res.keys())}")

    if not present:
        # ---- zero-match leg: served shape matches none of the asserted fields ----
        defect("Type4_StateLogicViolation",
               "GET /cluster answered 200 but the result carries NONE of the fields asserted "
               "by constraint qdrant_type_cluster_status_001 (peer_id uint64 / raft_state "
               "enum {Leader,Follower,Candidate,PreCandidate,Terminated} / commit_index "
               f"uint64 / peers map); observed result keys={sorted(res.keys())}; full "
               f"body={str(raw)[:400]}. raw_knowledge expected_responses documents exactly "
               "one 200 shape for this face ('ClusterStatus' - no alternative shape "
               "anywhere in contract/raw_knowledge) and sibling assertion "
               "qdrant_behavioral_cluster_status_001 promises this face valid on single-node "
               "deployments, so the served shape matches zero asserted fields on exactly "
               "the promised deployment class. (Adjudication note: an undocumented "
               "standalone 'disabled' variant would be the by-design defense; no such "
               "variant exists in any spec source available to this round.)")

    # ---- enabled-shape leg: all four documented fields must be present and typed ----
    missing = [f for f in DOC_FIELDS if f not in res]
    if missing:
        defect("Type4_StateLogicViolation",
               f"result carries the ClusterStatus variant ({present}) but omits documented "
               f"field(s) {missing}; constraint qdrant_type_cluster_status_001 asserts all "
               f"of {list(DOC_FIELDS)}; observed result={json.dumps(res, sort_keys=True)[:400]}")

    if not is_uint64(res["peer_id"]):
        defect("Type4_StateLogicViolation",
               f"peer_id violates the asserted uint64 type/domain: expected non-negative "
               f"integer <= 2^64-1 (bool excluded), got {res['peer_id']!r}; constraint "
               f"qdrant_type_cluster_status_001")

    if not is_uint64(res["commit_index"]):
        defect("Type4_StateLogicViolation",
               f"commit_index violates the asserted uint64 type/domain: expected "
               f"non-negative integer <= 2^64-1 (bool excluded), got "
               f"{res['commit_index']!r}; constraint qdrant_type_cluster_status_001")

    raft = res["raft_state"]
    if not isinstance(raft, str) or raft not in RAFT_ENUM:
        defect("Type4_StateLogicViolation",
               f"raft_state out of the asserted enum: expected one of "
               f"{sorted(RAFT_ENUM)}, got {raft!r}; constraint "
               f"qdrant_type_cluster_status_001")

    peers = res["peers"]
    if not isinstance(peers, dict):
        defect("Type4_StateLogicViolation",
               f"peers violates the asserted 'map' type: expected JSON object, got "
               f"{type(peers).__name__} {peers!r}; constraint "
               f"qdrant_type_cluster_status_001")

    print(f"[summary] result conforms to the asserted ClusterStatus shape: "
          f"peer_id={res['peer_id']} raft_state={raft} "
          f"commit_index={res['commit_index']} peers_keys={sorted(peers.keys())[:10]}")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
