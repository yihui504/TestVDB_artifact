#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_peer_delete_001
# strategy: delete_consistency
# endpoint: cluster+peer+delete
# constraint_ids: qdrant_behavioral_cluster_peer_delete_001, qdrant_state_cluster_peer_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 2 (post-DELETE state consistency) on DELETE /cluster/peer/{peer_id}
  (cluster+peer+delete; URL template read verbatim from raw_knowledge
  api_endpoints[].url, registered into rt.PATHS so rt.request stays the single
  HTTP exit). Reachability probe first (R5 lesson): GET /cluster snapshot
  (self peer_id + peers set) — transport/healthz failures exit honestly with
  SCRIPT_ERROR. Leg A exercises the behavioral assertion's negative face:
  a nonexistent (= invalid) peer id must be refused with 4xx; a 2xx there is
  an accepted removal of a peer that does not exist — Type1_IllegalSuccess
  (NOT shielded by the threat model's points-delete idempotency note: that
  by-design entry covers DELETE /collections/{c}/points, while this endpoint
  explicitly promises 4xx on invalid peer id). Leg B re-reads GET /cluster
  after the refused attempt: cluster membership (peers set, self peer_id)
  must be byte-for-byte unchanged and the status face must still answer 200 —
  a refused mutation mutating membership is Type4, a 5xx/transport there is
  Type3 only after /healthz liveness. Standalone "Distributed mode disabled"
  4xx masks are recorded as OBSERVATION (the 4xx still satisfies the promise
  at the status level; no conclusion drawn about peer-id validation itself).
  [chunk_cluster+peer+delete coverage: delete_consistency x
   qdrant_behavioral_cluster_peer_delete_001 (invalid-peer-id 4xx face) +
   qdrant_state_cluster_peer_delete_001 (membership-unchanged-after-refusal
   consistency clause)]
Oracle: DELETE /cluster/peer/<nonexistent id> -> HTTP status in 400..499
  (200/201/204 = Type1_IllegalSuccess per the endpoint's own "4xx invalid
  peer id" promise; 500..599 = Type3_RuntimeFailure only after /healthz
  returns 200); afterwards GET /cluster -> HTTP 200 whose result object
  carries result.peer_id (uint64) equal to the pre-attempt snapshot and
  result.peers (map) whose key set is identical to the pre-attempt snapshot
  (peers key drift = Type4_StateLogicViolation; result.peer_id change =
  Type4; GET /cluster 500..599 while /healthz is 200 = Type3_RuntimeFailure)
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

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
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

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)


def load_peer_delete_template():
    """R5 lesson: derive the URL only from raw_knowledge api_endpoints[].url
    (entry with path == "cluster+peer+delete"). No literal path invented."""
    for _p in Path(__file__).resolve().parents:
        _rk = _p / "raw_knowledge.json"
        if _rk.exists():
            try:
                for _e in json.loads(_rk.read_text(encoding="utf-8")).get("api_endpoints", []):
                    if _e.get("path") == "cluster+peer+delete" and _e.get("url"):
                        return _e["url"]
            except Exception:
                return None
    return None


_PEER_TPL = load_peer_delete_template()
if not _PEER_TPL:
    print("VERDICT: SCRIPT_ERROR - cluster+peer+delete url not derivable from raw_knowledge api_endpoints[].url")
    sys.exit(2)
# register derived template so the path_key lives inside rt.PATHS (whitelist honored,
# rt.request stays the single HTTP exit with runtime auth/base handling)
rt.PATHS["cluster_peer_delete"] = _PEER_TPL
print(f"[url-derived] cluster+peer+delete -> {_PEER_TPL} (raw_knowledge api_endpoints[].url)")


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; inline liveness probes (GET healthz)
    stay in this exact call form for static-check visibility."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def cluster_snapshot():
    """GET /cluster -> (status, peers_frozenset|None, self_peer_id|None, raw).
    Envelope result.<field> per standing lesson; peers may be a map or a list."""
    s, raw = safe_request("GET", "cluster_status")
    if s != 200:
        return s, None, None, raw
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, None, raw
    node = b.get("result") if isinstance(b, dict) else None
    if not isinstance(node, dict):
        return s, None, None, raw
    peers = node.get("peers")
    peers_set = None
    if isinstance(peers, dict):
        peers_set = frozenset(str(k) for k in peers.keys())
    elif isinstance(peers, list):
        ids = []
        for p in peers:
            if isinstance(p, dict) and "peer_id" in p:
                ids.append(str(p["peer_id"]))
            else:
                ids.append(str(p))
        peers_set = frozenset(ids)
    return s, peers_set, node.get("peer_id"), raw


def main():
    DEFECTS = []
    # u64-valid but far outside any lab peer-id space -> nonexistent = invalid peer id face
    GHOST = 987654321000123

    try:
        # ---- reachability probe (R5: probe first, exit honestly if unreachable) ----
        s0, peers0, self0, raw0 = cluster_snapshot()
        print(f"[probe GET /cluster] status={s0} self_peer_id={self0} "
              f"peers={sorted(peers0) if peers0 is not None else None} raw={raw0[:200]}")
        if s0 == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on GET /cluster probe — cluster face unreachable")
            return "SCRIPT_ERROR"
        if s0 != 200:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print(f"ENV_ISSUE: GET /cluster returned {s0} — cluster face not exercisable")
            return "SCRIPT_ERROR"
        if peers0 is None:
            print("OBSERVATION: cluster status 200 but result.peers not parseable "
                  "(envelope drift) — leg B membership comparison limited")

        # ---- leg A: invalid (nonexistent) peer id -> behavioral promise: 4xx ----
        s, raw = safe_request("DELETE", "cluster_peer_delete",
                              path_params={"peer_id": GHOST})
        print(f"[A invalid peer id {GHOST}] status={s} raw={raw[:300]}")
        if 200 <= s < 300:
            DEFECTS.append(
                f"(A) DELETE /cluster/peer/{GHOST} (nonexistent peer) returned {s} "
                f"(2xx) — assertion qdrant_behavioral_cluster_peer_delete_001 "
                f"promises 4xx on an invalid peer id — removal of a peer that does "
                f"not exist accepted into the membership state machine — "
                f"Type1_IllegalSuccess — raw={raw[:200]}"
            )
        elif 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(A) DELETE invalid peer id returned {s} (5xx; 4xx promised, "
                f"service alive per /healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
            )
        elif s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on (A); liveness ok — leg skipped")
        elif 400 <= s <= 499:
            low = str(raw).lower()
            if "distributed" in low:
                print("OBSERVATION (mask): 4xx reason looks like the standalone "
                      "distributed-mode gate rather than peer-id validation itself "
                      "— promise satisfied at status level (4xx), not judged further")
            else:
                print(f"[A] refused with {s} — invalid peer id correctly rejected")
        else:
            print(f"OBSERVATION (A): disposition {s} outside promise set "
                  f"{{2xx,4xx,5xx}} — recorded, not judged")

        # ---- leg B: post-attempt cluster-state consistency (Strategy 2) ----
        s1, peers1, self1, raw1 = cluster_snapshot()
        print(f"[B post-attempt GET /cluster] status={s1} self_peer_id={self1} "
              f"peers={sorted(peers1) if peers1 is not None else None} raw={raw1[:200]}")
        if s1 == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on (B); liveness ok — leg skipped")
        elif 500 <= s1 <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(B) GET /cluster after the refused removal returned {s1} "
                f"(200 expected; service alive per /healthz) — cluster-status face "
                f"degraded by a refused mutation — Type3_RuntimeFailure — "
                f"raw={raw1[:200]}"
            )
        elif s1 == 200:
            if peers0 is not None and peers1 is not None and peers1 != peers0:
                DEFECTS.append(
                    f"(B) peers set changed after a REFUSED removal: "
                    f"before={sorted(peers0)} after={sorted(peers1)} — membership "
                    f"mutated without an accepted operation — "
                    f"Type4_StateLogicViolation"
                )
            if self0 is not None and self1 is not None and self1 != self0:
                DEFECTS.append(
                    f"(B) self peer_id changed after refused removal: "
                    f"{self0} -> {self1} — Type4_StateLogicViolation"
                )

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        pass  # no collection created in this script; nothing to clean up


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
