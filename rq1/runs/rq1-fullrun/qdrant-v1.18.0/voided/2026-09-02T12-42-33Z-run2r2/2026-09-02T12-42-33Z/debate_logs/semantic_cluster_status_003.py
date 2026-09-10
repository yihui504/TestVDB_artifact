#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_status_003
# strategy: metamorphic
# endpoint: cluster+status
# constraint_ids: qdrant_type_cluster_status_001, qdrant_behavioral_cluster_status_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-status
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency/State Blindness - cluster-membership face
#   perturbed by data-plane activity) + BS-05 (Documentation Drift)
"""
Attack: metamorphic x {constraints::qdrant_type_cluster_status_001,
  assertions::qdrant_behavioral_cluster_status_001} (chunk_cluster+status;
  GET /cluster via runtime path_key cluster_status, URL "/cluster" from
  raw_knowledge api_endpoints[cluster+status].url; documented no-body control
  probes bracket every mutation leg, per R7 lesson). Metamorphic relations over
  the read-only status face, anchored on both chunk units: the assertion
  promises a stable "HTTP 200 with ClusterStatus ... valid on single-node
  deployments" face, and the type constraint pins its field semantics
  (peer_id/peers = membership identity, raft_state = role,
  commit_index = the one field that is a documented moving counter).
  MR1 (adjacent-read determinism): two back-to-back control reads must agree
  on the membership view (result minus the moving commit_index counter).
  MR2 (data-plane invariance): create + upsert + exact-count must not change
  the membership view; only commit_index may advance.
  MR3 (post-delete invariance): dropping the witness collection must not
  change the membership view.
  commit_index, when served, must stay uint64-typed and never decrease (it is
  a raft log commit position - moving backwards is a state-logic break under
  any reading).
  [chunk_cluster+status coverage: metamorphic x both chunk units
   (qdrant_type_cluster_status_001 + qdrant_behavioral_cluster_status_001 -
   read determinism / data-plane invariance / post-delete invariance)]
Oracle: across all four reads (baseline x2, post-writes, post-delete) GET
  /cluster keeps answering 200 with identical stable_view(result) (result
  minus commit_index); any change in the membership face (status/peer_id/
  raft_state/peers keys) after data-plane-only operations = Type4
  _StateLogicViolation (no cluster operation was issued - the only documented
  way to change this face); a mid-sequence non-200 flip = Type4; a decreasing
  or non-uint64 commit_index = Type4; 5xx with /healthz alive = Type3.

Rationale (G6 - mutation justified): collection create/upsert/delete is the
  deepest data-plane perturbation available to the semantic lane - it drives
  WAL appends, segment/optimizer activity and storage mutation. The
  cluster-status face documents membership/consensus state whose only
  documented mutation paths are the explicit cluster operations (recover /
  peer-delete / collection-cluster-update - all separate faces, none issued
  here). Data-plane writes are therefore the maximally likely innocent-looking
  sequence to catch an undocumented coupling between storage activity and the
  membership face (BS-03), and the witness collection makes the legs
  deterministic and self-cleaning.
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

UINT64_MAX = 2 ** 64 - 1
TS = str(int(time.time()))
COL = f"scst3_{TS}_col"
POINTS = [
    {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"city": "paris", "rank": 1}},
    {"id": 2, "vector": [0.5, 0.6, 0.7, 0.8], "payload": {"city": "lyon", "rank": 2}},
    {"id": 3, "vector": [0.9, 1.0, 1.1, 1.2], "payload": {"city": "nice", "rank": 3}},
]


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


def stable_view(res):
    """Membership view of the result node: everything except commit_index (the
    one documented moving counter). Serialized canonically for comparison."""
    if not isinstance(res, dict):
        return f"__non_dict__:{str(res)[:200]}"
    return json.dumps({k: v for k, v in res.items() if k != "commit_index"},
                      sort_keys=True)


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def read_face(tag, first=False):
    """One control read of the status face. Returns (result_dict, commit_index).
    first=True: a non-200 face means the 200-promise break is owned by
    semantic_cluster_status_001 (SCRIPT_ERROR here). first=False: a mid-sequence
    flip away from 200 is itself the MR violation (Type4)."""
    st, raw = safe_request("GET", "cluster_status", timeout=15)
    print(f"[{tag} GET /cluster] status={st} raw={str(raw)[:400]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[{tag} transport branch] inline /healthz probe status={hs} raw={str(hraw)[:80]}")
        script_error(f"transport failure on GET /cluster ({tag}); no defect conclusion")
    if 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[{tag} 5xx branch] inline /healthz probe status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            script_error(f"GET /cluster {st} and /healthz {hs}; deployment unstable")
        if first:
            script_error(f"GET /cluster {st} at baseline; 200-promise owned by "
                         "semantic_cluster_status_001")
        defect("Type3_RuntimeFailure",
               f"GET /cluster flipped to {st} mid-sequence (after data-plane operations) "
               f"while /healthz is alive; raw={str(raw)[:200]}")
    if st != 200:
        if first:
            script_error(f"baseline GET /cluster answered {st}; disposition judgment owned "
                         "by semantic_cluster_status_001")
        defect("Type4_StateLogicViolation",
               f"the documented 200 status face flipped to {st} after data-plane-only "
               f"operations (no cluster operation was issued); raw={str(raw)[:250]}")
    b = jload(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        if first:
            script_error(f"baseline result node missing/not an object (result={res!r}); "
                         "owned by semantic_cluster_status_001")
        defect("Type4_StateLogicViolation",
               f"result node disappeared/malformed mid-sequence: {str(raw)[:250]}")
    return res, res.get("commit_index")


def check_commit(prev, cur, tag):
    """commit_index: uint64-typed, never decreasing (raft log position)."""
    for tag_ci, v in (("prev", prev), ("cur", cur)):
        if v is not None and not (isinstance(v, int) and not isinstance(v, bool)
                                  and 0 <= v <= UINT64_MAX):
            defect("Type4_StateLogicViolation",
                   f"commit_index at {tag}/{tag_ci} violates the asserted uint64 domain "
                   f"(constraint qdrant_type_cluster_status_001): got {v!r}")
    if prev is not None and cur is not None and cur < prev:
        defect("Type4_StateLogicViolation",
               f"commit_index moved backwards across {tag} ({prev} -> {cur}); a raft commit "
               f"position is monotonically non-decreasing - state-logic violation under "
               f"the qdrant_type_cluster_status_001 field semantics")


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    hs, hraw = safe_request("GET", "healthz")
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")

    try:
        # ---- baseline control reads (MR1 adjacent-read determinism) ----
        base_res, base_ci = read_face("baseline-1", first=True)
        base_view = stable_view(base_res)
        adj_res, adj_ci = read_face("baseline-2")
        if stable_view(adj_res) != base_view:
            defect("Type4_StateLogicViolation",
                   "MR1 broken: two adjacent idle reads of the read-only status face "
                   "disagree on the membership view (commit_index excluded):\n"
                   f"  read1={base_view[:300]}\n  read2={stable_view(adj_res)[:300]}")
        check_commit(base_ci, adj_ci, "MR1-adjacent-reads")

        # ---- witness data plane (MR2 mutation legs) ----
        ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
        if not ok:
            script_error(f"setup failed creating {COL}: {err}")
        st, raw = safe_request("PUT", "upsert_points", body={"points": POINTS},
                               path_params={"name": COL},
                               query_params={"wait": "true"}, timeout=20)
        print(f"[witness upsert] status={st} raw={str(raw)[:200]}")
        if st not in (200, 201):
            script_error(f"witness upsert failed ({st}); setup failure - no defect conclusion")
        cst, craw = safe_request("POST", "count", body={"exact": True},
                                 path_params={"name": COL}, timeout=15)
        cb = jload(craw)
        cnt = cb.get("result", {}).get("count") if isinstance(cb, dict) else None
        print(f"[witness count] status={cst} count={cnt}")
        if cst != 200 or cnt != 3:
            script_error(f"witness data plane not established (count={cnt}, status={cst})")

        # ---- MR2: data-plane writes must not perturb the membership face ----
        post_res, post_ci = read_face("post-writes")
        if stable_view(post_res) != base_view:
            defect("Type4_StateLogicViolation",
                   "MR2 broken: create+upsert+count (data-plane only; no cluster "
                   "operation issued) changed the membership view of GET /cluster:\n"
                   f"  baseline={base_view[:300]}\n  post-writes={stable_view(post_res)[:300]}\n"
                   "the only documented way to change this face is an explicit cluster "
                   "operation (separate faces, none called)")
        check_commit(adj_ci, post_ci, "MR2-post-writes")

        # ---- MR3: dropping the witness collection must not perturb the face ----
        dst, draw = safe_request("DELETE", "drop_collection",
                                 path_params={"name": COL}, timeout=20)
        print(f"[witness delete] status={dst} raw={str(draw)[:200]}")
        dropped = dst in (200, 201)
        if not dropped:
            print("[witness delete] non-2xx - MR3 leg skipped (sibling-face anomaly outside "
                  "this chunk; noted, not judged here)")
        if dropped:
            del_res, del_ci = read_face("post-delete")
            if stable_view(del_res) != base_view:
                defect("Type4_StateLogicViolation",
                       "MR3 broken: deleting a collection changed the membership view of "
                       f"GET /cluster:\n  baseline={base_view[:300]}\n  "
                       f"post-delete={stable_view(del_res)[:300]}\n"
                       "collection deletion is a data-plane op; membership must not move")
            check_commit(post_ci, del_ci, "MR3-post-delete")

        print(f"[summary] status face invariant across MR1/MR2"
              f"{'/MR3' if dropped else ''}; stable_view={base_view[:200]}; "
              f"commit_index {base_ci} -> {post_ci}")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
