#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_peer_delete_005
# strategy: count_consistency
# endpoint: cluster+peer+delete
# constraint_ids: qdrant_behavioral_cluster_peer_delete_001, qdrant_state_cluster_peer_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 (CRUD-then-COUNT consistency, membership analog) positive
  face on DELETE /cluster/peer/{peer_id} (URL template read verbatim from
  raw_knowledge api_endpoints[].url, registered into rt.PATHS). The "count"
  face of this endpoint is the peers set read from GET /cluster. G4 pairing:
  Face 1 (exercisable on any deployment): a refused ghost removal must leave
  the membership count unchanged, checked across repeated snapshots (a
  refusal mutating membership = Type4); 5xx on any face = Type3 only after
  /healthz liveness. Face 2 (the assertion's positive promise, "valid peer
  removal returns HTTP 200"): a valid NON-SELF peer id is derived at runtime
  from GET /cluster (peers minus self — never hardcoded). If one exists
  (clustered deployment): remove it -> expect 200 with the boolean envelope
  (response_shape result:boolean), then GET /cluster must show peers count
  exactly baseline-1 (count consistency), and re-removing the same id must
  4xx (now invalid). If NO non-self peer exists (standalone deployment —
  the R5-established mode of this target): the positive 200 face cannot be
  exercised — per the R5 lesson the script exits honestly with SCRIPT_ERROR
  and no conclusion on that face (unless Face 1 already produced a defect,
  which is independent of the unreachable face).
  [chunk_cluster+peer+delete coverage: count_consistency x
   qdrant_behavioral_cluster_peer_delete_001 (valid-removal 200 face probe
   + peers-count consistency) + qdrant_state_cluster_peer_delete_001
   (membership-count stability under refused removal)]
Oracle: refused ghost removal -> GET /cluster 200 with peers count identical
  across snapshots (drift = Type4_StateLogicViolation; 5xx = Type3 only
  after /healthz liveness); if a non-self peer exists: its removal -> 200
  with result:boolean envelope and peers count decremented by exactly 1,
  re-removal -> 4xx; if no non-self peer exists (standalone): honest
  SCRIPT_ERROR exit, no conclusion on the 200 face
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


def alive():
    hs, hraw = safe_request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


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


def removal_result_boolean(raw):
    """200 envelope per response_shape: result is boolean -> True/False/None."""
    try:
        b = json.loads(raw) if raw else {}
        node = b.get("result") if isinstance(b, dict) else None
        if isinstance(node, bool):
            return node
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


def main():
    DEFECTS = []
    GHOST = 987654321000999

    try:
        # ---- reachability probe (R5: probe first) ----
        s0, peers0, self0, raw0 = cluster_snapshot()
        print(f"[probe GET /cluster] status={s0} self_peer_id={self0} "
              f"peers={sorted(peers0) if peers0 is not None else None} raw={raw0[:200]}")
        if s0 == 0:
            if not alive():
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on GET /cluster probe — cluster face unreachable")
            return "SCRIPT_ERROR"
        if s0 != 200:
            if not alive():
                return "SCRIPT_ERROR"
            print(f"ENV_ISSUE: GET /cluster returned {s0} — cluster face not exercisable")
            return "SCRIPT_ERROR"
        if peers0 is None:
            print("ENV_ISSUE: peers set not parseable from GET /cluster — "
                  "membership-count face not exercisable")
            return "SCRIPT_ERROR"
        base_n = len(peers0)

        # ---- face 1: refused removal must not change the membership count ----
        sg, rawg = safe_request("DELETE", "cluster_peer_delete",
                                path_params={"peer_id": GHOST})
        print(f"[face1 ghost {GHOST}] status={sg} raw={rawg[:300]}")
        if 200 <= sg < 300:
            DEFECTS.append(
                f"(face1) DELETE nonexistent peer {GHOST} returned {sg} (2xx) — "
                f"assertion promises 4xx on invalid peer id — "
                f"Type1_IllegalSuccess — raw={rawg[:200]}"
            )
        elif 500 <= sg <= 599:
            if not alive():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(face1) DELETE ghost returned {sg} (5xx; 4xx promised, service "
                f"alive per /healthz) — Type3_RuntimeFailure — raw={rawg[:200]}"
            )
        elif sg == 0:
            if not alive():
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on face1 removal; liveness ok")
        if sg != 0 and 400 <= sg <= 499 and "distributed" in str(rawg).lower():
            print("OBSERVATION (mask): refusal reason looks like the standalone "
                  "distributed-mode gate — recorded")

        for probe_idx in (1, 2):
            sp, peersp, _sp, rawp = cluster_snapshot()
            print(f"[face1 snapshot#{probe_idx}] status={sp} n_peers="
                  f"{len(peersp) if peersp is not None else None} raw={rawp[:150]}")
            if sp == 0:
                if not alive():
                    return "SCRIPT_ERROR"
                print("ENV_ISSUE: transport failure on snapshot; liveness ok")
                continue
            if 500 <= sp <= 599:
                if not alive():
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(face1) GET /cluster after refused removal returned {sp} "
                    f"(200 expected; service alive per /healthz) — "
                    f"Type3_RuntimeFailure — raw={rawp[:200]}"
                )
                continue
            if sp == 200 and peersp is not None and len(peersp) != base_n:
                DEFECTS.append(
                    f"(face1) membership count changed across a REFUSED removal: "
                    f"{base_n} -> {len(peersp)} (peers={sorted(peersp)}) — "
                    f"Type4_StateLogicViolation"
                )

        # ---- face 2: valid non-self removal (positive 200 promise) ----
        if self0 is None:
            others = []
            print("OBSERVATION: self peer_id underivable — a non-self victim "
                  "cannot be safely distinguished from self; face2 not attempted")
        else:
            others = sorted(peers0 - {str(self0)})
        if not others:
            print("FACE2_UNREACHABLE: no non-self peer in GET /cluster "
                  f"(peers={sorted(peers0)}, self={self0}) — standalone "
                  "deployment; the assertion's valid-removal-200 face cannot "
                  "be exercised on this deployment (R5 lesson: honest exit, "
                  "no conclusion on that face)")
            if DEFECTS:
                for d in DEFECTS:
                    print(f"DEFECT: {d}")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"

        victim = int(others[0])
        print(f"[face2] valid non-self peer derived at runtime: {victim} "
              f"(from peers minus self; nothing hardcoded)")
        sv, rawv = safe_request("DELETE", "cluster_peer_delete",
                                path_params={"peer_id": victim})
        print(f"[face2 removal {victim}] status={sv} raw={rawv[:300]}")
        if sv == 0:
            if not alive():
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on face2 removal")
            if DEFECTS:
                for d in DEFECTS:
                    print(f"DEFECT: {d}")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if 500 <= sv <= 599:
            if not alive():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(face2) valid non-self peer removal returned {sv} (5xx; 200 "
                f"promised, service alive per /healthz) — "
                f"Type3_RuntimeFailure — raw={rawv[:200]}"
            )
        elif not (200 <= sv < 300):
            DEFECTS.append(
                f"(face2) valid non-self peer {victim} removal returned {sv} — "
                f"assertion promises HTTP 200 for valid peer removal — "
                f"Type1 face violation (legal request wrongly rejected) — "
                f"raw={rawv[:200]}"
            )
        else:
            rb = removal_result_boolean(rawv)
            print(f"[face2 envelope] result(boolean)={rb} "
                  f"(response_shape declares result:boolean)")
            if rb is not True:
                print(f"OBSERVATION: 200 envelope result is not boolean true — "
                      f"recorded (response_shape says result:boolean)")

        # count consistency: exactly baseline-1 after an accepted removal
        time.sleep(1.0)  # allow membership propagation
        s2, peers2, _s2, raw2 = cluster_snapshot()
        print(f"[face2 post-removal GET /cluster] status={s2} n_peers="
              f"{len(peers2) if peers2 is not None else None} "
              f"peers={sorted(peers2) if peers2 is not None else None} raw={raw2[:200]}")
        if s2 == 200 and peers2 is not None:
            if len(peers2) != base_n - 1:
                DEFECTS.append(
                    f"(face2) membership count after accepted removal of {victim}: "
                    f"{len(peers2)} != expected {base_n - 1} — "
                    f"Type4_StateLogicViolation (count drift)"
                )
            if str(victim) in peers2:
                DEFECTS.append(
                    f"(face2) removed peer {victim} still present in peers after "
                    f"an accepted removal — Type4_StateLogicViolation (ghost member)"
                )

        # re-removal of the same id must now 4xx (id no longer valid)
        sr, rawr = safe_request("DELETE", "cluster_peer_delete",
                                path_params={"peer_id": victim})
        print(f"[face2 re-removal {victim}] status={sr} raw={rawr[:300]}")
        if 200 <= sr < 300:
            DEFECTS.append(
                f"(face2) re-removal of already-removed peer {victim} returned "
                f"{sr} (2xx) — the id is now invalid and must 4xx — "
                f"Type1_IllegalSuccess — raw={rawr[:200]}"
            )
        elif 500 <= sr <= 599:
            if not alive():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(face2) re-removal returned {sr} (5xx; 4xx expected, service "
                f"alive per /healthz) — Type3_RuntimeFailure — raw={rawr[:200]}"
            )
        elif sr == 0:
            if not alive():
                return "SCRIPT_ERROR"

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
