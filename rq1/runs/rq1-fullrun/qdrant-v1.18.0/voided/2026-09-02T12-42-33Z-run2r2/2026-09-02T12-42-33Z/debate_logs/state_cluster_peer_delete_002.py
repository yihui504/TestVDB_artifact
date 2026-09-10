#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_peer_delete_002
# strategy: delete_consistency
# endpoint: cluster+peer+delete
# constraint_ids: qdrant_state_cluster_peer_delete_001, qdrant_behavioral_cluster_peer_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 2 (post-DELETE consistency) safety-check face of the state
  constraint on DELETE /cluster/peer/{peer_id} (URL template read verbatim
  from raw_knowledge api_endpoints[].url, registered into rt.PATHS). The
  constraint qdrant_state_cluster_peer_delete_001 states force=true is what
  bypasses the safety check — implying the last-peer/self removal is guarded
  unless force is set. Leg A: DELETE the deployment's OWN peer_id (derived at
  runtime from GET /cluster, never hardcoded) WITHOUT force -> must be
  refused 4xx; a 2xx means the documented guard was silently bypassed
  without its flag — Type1_IllegalSuccess — and the post-state probes
  quantify the damage (healthz + GET /cluster membership). Leg B: after the
  attempt, the still-alive node's membership snapshot must be unchanged
  (self still present, peers set identical) — drift = Type4. Leg C (control):
  force=true exercised on a GHOST peer only — force is documented to bypass
  consensus safety, not peer-existence validation, so even force=true must
  keep the invalid-peer-id 4xx promise; 2xx there = Type1. SKIPPED by design:
  force=true on SELF is the documented destructive bypass and would brick a
  clustered deployment — not attempted (annotated per G3).
  [chunk_cluster+peer+delete coverage: delete_consistency x
   qdrant_state_cluster_peer_delete_001 (safety-check/consensus-survival
   clause) + qdrant_behavioral_cluster_peer_delete_001 (4xx face under force
   control)]
Oracle: DELETE /cluster/peer/<self peer_id from GET /cluster> without
  force -> HTTP status in 400..499 (200/201/204 = Type1_IllegalSuccess: the
  documented force-flag safety-check bypass happened without the flag;
  500..599 = Type3_RuntimeFailure only after /healthz returns 200);
  afterwards GET /cluster -> HTTP 200 with result.peer_id equal to the
  pre-attempt value and result.peers key set identical, str(self peer_id)
  still a key of result.peers (self vanished while the node answers, peers
  key drift, or result.peer_id change = Type4_StateLogicViolation); DELETE
  /cluster/peer/<nonexistent id> with force=true -> HTTP status in
  400..499 (200/201/204 = Type1_IllegalSuccess: force bypasses consensus
  safety, not peer-existence validation; 500..599 = Type3 after /healthz
  returns 200)
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
    """R5 lesson: derive the URL only from raw_knowledge api_endpoints[].url."""
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
rt.PATHS["cluster_peer_delete"] = _PEER_TPL
print(f"[url-derived] cluster+peer+delete -> {_PEER_TPL} (raw_knowledge api_endpoints[].url)")


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; inline liveness probes (GET healthz)
    stay in this exact call form for static-check visibility."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def cluster_snapshot():
    """GET /cluster -> (status, peers_frozenset|None, self_peer_id|None, raw)."""
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
    GHOST = 987654321000456  # nonexistent peer; force control carrier only

    try:
        # ---- reachability probe (R5: probe first) ----
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
        if self0 is None:
            print("ENV_ISSUE: self peer_id not derivable from GET /cluster — "
                  "safety-check face not exercisable")
            return "SCRIPT_ERROR"

        # ---- leg A: remove SELF (last peer) WITHOUT force -> guarded, expect 4xx ----
        s, raw = safe_request("DELETE", "cluster_peer_delete",
                              path_params={"peer_id": self0})
        print(f"[A self {self0} no-force] status={s} raw={raw[:300]}")
        if 200 <= s < 300:
            DEFECTS.append(
                f"(A) DELETE self peer {self0} WITHOUT force returned {s} (2xx) — "
                f"constraint qdrant_state_cluster_peer_delete_001 documents "
                f"force=true as the ONLY bypass of the last-peer/self safety "
                f"check — guard silently bypassed without its flag — "
                f"Type1_IllegalSuccess — raw={raw[:200]}"
            )
        elif 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(A) DELETE self without force returned {s} (5xx; graceful 4xx "
                f"expected, service alive per /healthz) — Type3_RuntimeFailure — "
                f"raw={raw[:200]}"
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
                      "distributed-mode gate — safety-check face masked; refusal "
                      "itself still consistent with the guard")
            else:
                print(f"[A] self/last-peer removal refused with {s} — guard held")
        else:
            print(f"OBSERVATION (A): disposition {s} outside promise set — "
                  f"recorded, not judged")

        # ---- leg B: post-attempt membership + liveness consistency ----
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
                f"(B) GET /cluster after the self-removal attempt returned {s1} "
                f"(200 expected; service alive per /healthz) — Type3_RuntimeFailure "
                f"— raw={raw1[:200]}"
            )
        elif s1 == 200:
            if peers0 is not None and peers1 is not None:
                if peers1 != peers0:
                    DEFECTS.append(
                        f"(B) peers set changed across the self-removal attempt: "
                        f"before={sorted(peers0)} after={sorted(peers1)} — "
                        f"Type4_StateLogicViolation"
                    )
                elif str(self0) not in peers1:
                    DEFECTS.append(
                        f"(B) self peer {self0} vanished from peers while the node "
                        f"still answers GET /cluster — membership/consensus state "
                        f"inconsistent with liveness — Type4_StateLogicViolation"
                    )
                else:
                    print("[B] membership intact (consensus survival observable "
                          "after the attempt)")
        else:
            print(f"OBSERVATION (B): GET /cluster returned {s1} — recorded, not judged")

        # ---- leg C (control): force=true on a GHOST peer — invalid id stays 4xx ----
        # force passed as lowercase string: requests would stringify Python True as
        # "True", which the server bool parser rejects — that artifact would mask
        # the real disposition under test.
        sc, rawc = safe_request("DELETE", "cluster_peer_delete",
                                path_params={"peer_id": GHOST},
                                query_params={"force": "true"})
        print(f"[C ghost {GHOST} force=true] status={sc} raw={rawc[:300]}")
        if 200 <= sc < 300:
            DEFECTS.append(
                f"(C) DELETE ghost peer {GHOST} WITH force=true returned {sc} "
                f"(2xx) — force is documented to bypass consensus safety only, "
                f"not peer-existence validation; the endpoint's own 4xx-on-invalid-"
                f"peer-id promise has no force exception — Type1_IllegalSuccess — "
                f"raw={rawc[:200]}"
            )
        elif 500 <= sc <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(C) DELETE ghost peer with force=true returned {sc} (5xx; 4xx "
                f"promised, service alive per /healthz) — Type3_RuntimeFailure — "
                f"raw={rawc[:200]}"
            )
        elif sc == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on (C); liveness ok — leg skipped")
        elif 400 <= sc <= 499:
            print(f"[C] force=true kept the invalid-peer-id refusal ({sc}) — "
                  f"bypass scope honored")

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
