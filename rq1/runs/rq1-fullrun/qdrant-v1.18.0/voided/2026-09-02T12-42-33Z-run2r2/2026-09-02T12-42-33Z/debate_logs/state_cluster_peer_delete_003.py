#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_peer_delete_003
# strategy: upsert_idempotence
# endpoint: cluster+peer+delete
# constraint_ids: qdrant_behavioral_cluster_peer_delete_001, qdrant_state_cluster_peer_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 3 (idempotence analog — disposition consistency of repeated
  DELETEs) on DELETE /cluster/peer/{peer_id} (URL template read verbatim from
  raw_knowledge api_endpoints[].url, registered into rt.PATHS). For an
  idempotent destructive carrier the SAME parameter must keep a stable
  disposition (G9): repeating a refused removal must not flip to acceptance,
  and repeating any removal must not flap across rejection families. Leg A:
  the same nonexistent peer id removed twice -> both 4xx and identical
  family; any 2xx = Type1 (invalid-id promise), a 4xx-then-5xx flap =
  state-dependent instability of an idempotent carrier (Type4; the 5xx leg
  itself Type3 only after /healthz liveness). Leg B: self peer_id (derived
  from GET /cluster) removed twice without force -> consistent 4xx pair
  expected; 2xx anywhere = Type1 (guard bypass without force, per
  qdrant_state_cluster_peer_delete_001). Leg C: same ghost id with
  force="false" vs force="true" -> force must not flip an invalid id to
  success (force bypasses consensus safety, not existence validation);
  divergent dispositions across the force faces of one id = G9 signal.
  [chunk_cluster+peer+delete coverage: upsert_idempotence x
   qdrant_behavioral_cluster_peer_delete_001 (repeated-removal 4xx face) +
   qdrant_state_cluster_peer_delete_001 (repeated safety-check face)]
Oracle: repeated DELETE of the same invalid peer id -> both responses 4xx
  with a consistent disposition family (any 2xx = Type1_IllegalSuccess;
  4xx-then-5xx flap = Type4_StateLogicViolation with the 5xx leg Type3 only
  after /healthz liveness); repeated self-removal without force -> both 4xx;
  force=true vs force=false on one ghost id -> neither may return 2xx
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


def family(status):
    """Disposition family for consistency comparison: 2xx / 4xx / 5xx / 0."""
    if 200 <= status < 300:
        return "2xx"
    if 400 <= status < 500:
        return "4xx"
    if 500 <= status <= 599:
        return "5xx"
    return "0/other"


def judge_pair(tag, pid_desc, s1, raw1, s2, raw2, constraint_note, DEFECTS):
    """Judge two repeated dispositions of one carrier (G9 consistent-disposition)."""
    print(f"[{tag} repeat-2] status={s2} raw={raw2[:300]}")
    for idx, (si, ri) in enumerate(((s1, raw1), (s2, raw2)), start=1):
        if 200 <= si < 300:
            DEFECTS.append(
                f"({tag}#{idx}) DELETE {pid_desc} returned {si} (2xx) — "
                f"{constraint_note} — Type1_IllegalSuccess — raw={ri[:200]}"
            )
        elif 500 <= si <= 599:
            if not alive():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"({tag}#{idx}) DELETE {pid_desc} returned {si} (5xx; graceful 4xx "
                f"expected, service alive per /healthz) — Type3_RuntimeFailure — "
                f"raw={ri[:200]}"
            )
        elif si == 0:
            if not alive():
                return "SCRIPT_ERROR"
            print(f"ENV_ISSUE: transport failure on ({tag}#{idx}); liveness ok")
    f1, f2 = family(s1), family(s2)
    if f1 in ("0/other",) or f2 in ("0/other",):
        print(f"OBSERVATION ({tag}): disposition family {f1}/{f2} outside promise "
              f"set — recorded, not judged")
        return "OK"
    if "5xx" in (f1, f2):
        # a 5xx leg was already judged Type3 above — do not double-count the
        # same event as a family-flap Type4
        return "OK"
    if f1 != f2:
        DEFECTS.append(
            f"({tag}) same parameter deleted twice flapped disposition family "
            f"{f1} -> {f2} — an idempotent destructive carrier must keep a stable "
            f"disposition (G9 inconsistent disposition) — "
            f"Type4_StateLogicViolation — raws={raw1[:100]} | {raw2[:100]}"
        )
    return "OK"


def main():
    DEFECTS = []
    GHOST_A = 987654321000789  # nonexistent peer — repeated-removal carrier
    GHOST_B = 987654321000790  # force-face comparison carrier
    NOTE_INVALID = ("assertion qdrant_behavioral_cluster_peer_delete_001 "
                    "promises 4xx on an invalid peer id")
    NOTE_SELF = ("constraint qdrant_state_cluster_peer_delete_001 documents "
                 "force=true as the only safety-check bypass, none was passed")

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

        # ---- leg A: same invalid peer id, deleted twice ----
        sa1, rawa1 = safe_request("DELETE", "cluster_peer_delete",
                                  path_params={"peer_id": GHOST_A})
        print(f"[A repeat-1] status={sa1} raw={rawa1[:300]}")
        sa2, rawa2 = safe_request("DELETE", "cluster_peer_delete",
                                  path_params={"peer_id": GHOST_A})
        r = judge_pair("A", f"invalid peer {GHOST_A}", sa1, rawa1, sa2, rawa2,
                       NOTE_INVALID, DEFECTS)
        if r == "SCRIPT_ERROR":
            return "SCRIPT_ERROR"
        low = (str(rawa1) + str(rawa2)).lower()
        if "distributed" in low:
            print("OBSERVATION (mask): 4xx reasons look like the standalone "
                  "distributed-mode gate — invalid-id face masked; only the "
                  "consistency of the refusals is judged here")

        # ---- leg B: self peer id without force, deleted twice ----
        if self0 is None:
            print("OBSERVATION (B): self peer_id not derivable — leg skipped")
        else:
            sb1, rawb1 = safe_request("DELETE", "cluster_peer_delete",
                                      path_params={"peer_id": self0})
            print(f"[B repeat-1] status={sb1} raw={rawb1[:300]}")
            sb2, rawb2 = safe_request("DELETE", "cluster_peer_delete",
                                      path_params={"peer_id": self0})
            r = judge_pair("B", f"self peer {self0} (no force)", sb1, rawb1,
                           sb2, rawb2, NOTE_SELF, DEFECTS)
            if r == "SCRIPT_ERROR":
                return "SCRIPT_ERROR"

        # ---- leg C: one ghost id across the force=false/true faces ----
        # force values passed as lowercase strings (requests would stringify
        # Python True as "True" and the server bool parser would reject that
        # — an artifact that would mask the disposition under test).
        sc1, rawc1 = safe_request("DELETE", "cluster_peer_delete",
                                  path_params={"peer_id": GHOST_B},
                                  query_params={"force": "false"})
        print(f"[C force=false] status={sc1} raw={rawc1[:300]}")
        sc2, rawc2 = safe_request("DELETE", "cluster_peer_delete",
                                  path_params={"peer_id": GHOST_B},
                                  query_params={"force": "true"})
        print(f"[C force=true] status={sc2} raw={rawc2[:300]}")
        for tag, si, ri in (("C/force=false", sc1, rawc1),
                            ("C/force=true", sc2, rawc2)):
            if 200 <= si < 300:
                DEFECTS.append(
                    f"({tag}) DELETE invalid peer {GHOST_B} returned {si} (2xx) — "
                    f"force bypasses consensus safety only, not peer-existence "
                    f"validation; the 4xx-on-invalid-peer-id promise has no force "
                    f"exception — Type1_IllegalSuccess — raw={ri[:200]}"
                )
            elif 500 <= si <= 599:
                if not alive():
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"({tag}) DELETE invalid peer returned {si} (5xx; 4xx promised, "
                    f"service alive per /healthz) — Type3_RuntimeFailure — "
                    f"raw={ri[:200]}"
                )
            elif si == 0:
                if not alive():
                    return "SCRIPT_ERROR"
                print(f"ENV_ISSUE: transport failure on ({tag}); liveness ok")
        fc1, fc2 = family(sc1), family(sc2)
        if fc1 in ("0/other",) or fc2 in ("0/other",):
            print(f"OBSERVATION (C): disposition family {fc1}/{fc2} outside "
                  f"promise set — recorded, not judged")
        elif "5xx" in (fc1, fc2):
            pass  # 5xx face already judged Type3 above — no double-count
        elif fc1 != fc2:
            DEFECTS.append(
                f"(C) one invalid peer id flipped disposition family across the "
                f"force faces ({fc1} -> {fc2}) — force must not change the "
                f"existence-validation outcome of one id (G9 inconsistent "
                f"disposition across parameter faces) — "
                f"Type4_StateLogicViolation — raws={rawc1[:100]} | {rawc2[:100]}"
            )

        # ---- final membership consistency (repeated refusals must not mutate) ----
        s1, peers1, _self1, raw1 = cluster_snapshot()
        print(f"[final GET /cluster] status={s1} "
              f"peers={sorted(peers1) if peers1 is not None else None} raw={raw1[:200]}")
        if s1 == 0:
            if not alive():
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on final snapshot; liveness ok")
        elif 500 <= s1 <= 599:
            if not alive():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(final) GET /cluster after the repeat battery returned {s1} "
                f"(200 expected; service alive per /healthz) — "
                f"Type3_RuntimeFailure — raw={raw1[:200]}"
            )
        elif s1 == 200 and peers0 is not None and peers1 is not None \
                and peers1 != peers0:
            DEFECTS.append(
                f"(final) peers set changed across refused repeated removals: "
                f"before={sorted(peers0)} after={sorted(peers1)} — "
                f"Type4_StateLogicViolation"
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
