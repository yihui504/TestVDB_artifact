#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_peer_delete_005
# strategy: behavioral_contract
# endpoint: cluster+peer+delete
# constraint_ids: qdrant_state_cluster_peer_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency/State Blindness - a REFUSED destructive operation must
#   leave zero trace: cluster status, local peer id and collections all unchanged)
"""
Attack: behavioral_contract (general-principles both-direction, G4) x
  constraints::qdrant_state_cluster_peer_delete_001 (chunk_cluster+peer+delete; DELETE
  /cluster/peer/{peer_id}, URL from raw_knowledge api_endpoints[cluster+peer+delete].url).
  The constraint asserts "peer removal is destructive by design: force=true bypasses
  safety checks, and removal of a peer holding the only replica can lose data; a 200
  does not guarantee consensus survival". Both directions on a single-node deployment:
  positive face (the safety check exists): removing the ONLY peer - discovered live via
  GET /collections/{c}/cluster result.peer_id - WITHOUT force is exactly the
  consensus-breaking "last peer" case the safety check guards, and must be refused (4xx);
  negative faces: (a) force=true on a ghost peer must STILL be 4xx - force bypasses the
  consensus safety check, not peer existence, so a 200 would claim removal of a
  non-existent peer; (b) reconciliation: after every refused attempt the deployment
  must be fully reconciled (/healthz alive, GET /cluster same state envelope with the
  volatile 'time' field excluded, the witness collection still describable, its cluster
  peer_id unchanged) - any drift means a refused destructive op mutated state (Type4).
  Deployment guard (G8 + R5 lesson): the real-peer probe is issued ONLY after a ghost
  probe has been refused 4xx (evidence the dispatcher gates removals); the fully
  destructive face (force=true against the real last peer) is NOT exercisable on this
  shared deployment and is annotated SKIPPED below - it needs a disposable cluster.
  [chunk_cluster+peer+delete coverage: behavioral_contract x
   qdrant_state_cluster_peer_delete_001 (safety-check refusal + force-on-ghost +
   refused-op reconciliation)]
Oracle: ghost removal (no force) -> 4xx (guard), then only-peer removal without force
  -> 4xx (safety check), ghost removal with force=true -> still 4xx (existence is not
  bypassed by force); any 2xx on these legs = Type1_IllegalSuccess (destructive op
  armed/executed where the contract's safety semantics forbid it), 5xx with /healthz
  alive = Type3; after all legs /healthz=200, GET /cluster=200, describe
  collection=200, collection cluster peer_id == pre-battery peer_id - any drift =
  Type4_StateLogicViolation

Rationale (G6): the only-peer id is the strongest possible breaker of the safety-check
promise - it is the single input for which "may break raft consensus" is not a
hypothetical but the certain outcome; a ghost id with force=true is the strongest
breaker of the force-semantics boundary (existence vs safety). Timing/duplication
mutants are covered by semantic_cluster_peer_delete_004; this script owns the
existence/safety hinge.
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

# ---- runtime PATHS gap: register the contract-derived URL (same as 001) ----
REMOVE_PEER_KEY = "remove_peer"
if REMOVE_PEER_KEY not in rt.PATHS:
    rt.PATHS[REMOVE_PEER_KEY] = "/cluster/peer/{peer_id}"
print(f"[path derivation] remove_peer = {rt.PATHS[REMOVE_PEER_KEY]} (raw_knowledge api_endpoints[cluster+peer+delete].url)")

GHOST_PEER = 987654321987654321
TS = str(int(time.time()))
COL = f"scpd5_{TS}_col"


def safe_request(method, path_key, path_params=None, body=None, query_params=None,
                 timeout=30):
    """All HTTP through the runtime; kept in this exact call form so the inline
    liveness probes (GET healthz) stay visible to static checks. timeout is
    forwarded to rt.request (per-request transport timeout)."""
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
    return r if isinstance(r, dict) else None


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


def refuse_or_die(status, raw, ctx):
    """Declared expectation: 4xx refusal on this destructive leg. Exits on
    2xx/5xx/0; returns True on a clean 4xx refusal."""
    print(f"[{ctx}] status={status} raw={str(raw)[:300]}")
    if status == 0:
        liveness("transport")
        script_error(f"transport failure on {ctx} (status=0); no defect conclusion")
    if 500 <= status <= 599:
        hs = liveness("5xx")
        if hs != 200:
            script_error(f"5xx on {ctx} and /healthz not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"{ctx} raised server error {status} while /healthz is alive; constraint "
               f"qdrant_state_cluster_peer_delete_001 expects a guarded refusal, not a crash; "
               f"raw={str(raw)[:200]}")
    if 200 <= status < 300:
        defect("Type1_IllegalSuccess",
               f"{ctx} returned {status} success - constraint qdrant_state_cluster_peer_delete_001: "
               f"peer removal is destructive by design and force bypasses safety checks; success on "
               f"this leg means the safety/existence gate failed to guard a single-node deployment "
               f"(state may now be damaged - stopping immediately); raw={str(raw)[:200]}")
    if 400 <= status < 500:
        return True
    script_error(f"unexpected status {status} on {ctx}; no defect conclusion")


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    hs, _ = safe_request("GET", "healthz")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")
    print(f"[pre-probe] /healthz status={hs}")

    try:
        # ---- witness collection + live peer discovery ----
        ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
        if not ok:
            script_error(f"setup failed creating {COL}: {err}")
        st, raw = safe_request("GET", "collection_cluster", path_params={"name": COL}, timeout=15)
        print(f"[witness cluster info] status={st} raw={str(raw)[:300]}")
        if st != 200:
            script_error(f"witness cluster info unavailable ({st}); cannot discover the local peer id")
        res = result_node(raw) or {}
        local_peer = res.get("peer_id")
        if not isinstance(local_peer, int):
            script_error(f"local peer id not derivable from collection cluster info "
                         f"(result.peer_id={local_peer!r}); the self-removal face cannot be exercised "
                         f"honestly (R5 lesson)")
        print(f"[discovery] local (only) peer id = {local_peer}")

        st, raw = safe_request("GET", "cluster_status", timeout=15)
        print(f"[baseline GET /cluster] status={st} raw={str(raw)[:300]}")
        bb = jload(raw)
        baseline_cluster_state = {
            "result": bb.get("result") if isinstance(bb, dict) else None,
            "status": bb.get("status") if isinstance(bb, dict) else None,
        }

        # ---- guard: ghost refusal must be 4xx before touching the real peer ----
        st, raw = safe_request("DELETE", REMOVE_PEER_KEY,
                               path_params={"peer_id": GHOST_PEER}, timeout=15)
        guard_ok = refuse_or_die(st, raw, "guard: ghost removal (no force) must be refused 4xx")

        # ---- negative face (a): force=true on ghost must STILL be refused ----
        st, raw = safe_request("DELETE", REMOVE_PEER_KEY,
                               path_params={"peer_id": GHOST_PEER},
                               query_params={"force": "true"}, timeout=15)
        refuse_or_die(st, raw, "force=true on ghost peer (existence is not bypassed by force)")

        # ---- positive face: safety check must refuse removing the ONLY peer ----
        if guard_ok:
            st, raw = safe_request("DELETE", REMOVE_PEER_KEY,
                                   path_params={"peer_id": local_peer}, timeout=15)
            refuse_or_die(st, raw, "only-peer removal WITHOUT force (consensus-breaking case)")

        print("SKIPPED: force=true against the real last peer (the fully destructive face) - "
              "by-design per threat_model the removal is destructive; exercising it would "
              "destroy the shared single-node deployment for all subsequent rounds; needs a "
              "disposable cluster, so no conclusion is drawn on that face")

        # ---- negative face (b): reconciliation after refused destructive ops ----
        hs = liveness("reconcile")
        if hs != 200:
            defect("Type3_RuntimeFailure",
                   f"/healthz returned {hs} after refused peer-removal attempts - a REFUSED "
                   f"destructive op must not take the deployment down")
        st, raw = safe_request("GET", "cluster_status", timeout=15)
        print(f"[reconcile GET /cluster] status={st} raw={str(raw)[:300]}")
        if st != 200:
            defect("Type4_StateLogicViolation",
                   f"GET /cluster answered {st} after refused peer removals (baseline was 200 with "
                   f"{json.dumps(baseline_cluster_state)[:120]}) - refused destructive ops must not mutate cluster state")
        nb = jload(raw)
        now_cluster_state = {
            "result": nb.get("result") if isinstance(nb, dict) else None,
            "status": nb.get("status") if isinstance(nb, dict) else None,
        }
        if now_cluster_state != baseline_cluster_state:
            print(f"OBSERVATION (reconcile): GET /cluster state changed across refused removals: "
                  f"baseline={json.dumps(baseline_cluster_state)[:200]} now={json.dumps(now_cluster_state)[:200]}")
            defect("Type4_StateLogicViolation",
                   "cluster status state (result+status envelope, volatile 'time' field excluded) "
                   "changed after only REFUSED peer-removal attempts - constraint "
                   "qdrant_state_cluster_peer_delete_001's destructive semantics leaked state "
                   "through the refusal path")
        st, raw = safe_request("GET", "describe_collection", path_params={"name": COL}, timeout=15)
        print(f"[reconcile describe] status={st} raw={str(raw)[:200]}")
        if st != 200:
            defect("Type4_StateLogicViolation",
                   f"witness collection {COL} no longer describable ({st}) after refused peer "
                   f"removals - data-plane damage from a refused control-plane op")
        st, raw = safe_request("GET", "collection_cluster", path_params={"name": COL}, timeout=15)
        print(f"[reconcile cluster info] status={st} raw={str(raw)[:300]}")
        res2 = result_node(raw) or {}
        if st != 200 or res2.get("peer_id") != local_peer:
            defect("Type4_StateLogicViolation",
                   f"collection cluster peer_id changed across refused removals: {local_peer} -> "
                   f"{res2.get('peer_id')!r} (status {st}) - refused destructive ops must not "
                   f"re-shard or re-assign peers")
        print("[summary] guard 4xx / force-on-ghost 4xx / only-peer-no-force 4xx / full reconciliation clean")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
