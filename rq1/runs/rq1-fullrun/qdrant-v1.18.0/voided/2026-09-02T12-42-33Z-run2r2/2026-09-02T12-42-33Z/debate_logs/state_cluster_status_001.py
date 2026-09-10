#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_status_001
# strategy: count_consistency
# endpoint: cluster+status
# constraint_ids: qdrant_type_cluster_status_001, qdrant_behavioral_cluster_status_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-status
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 (state-transition consistency matrix) on the global cluster
  face GET /cluster, with Strategy 2's post-DELETE phase folded as the final
  matrix phase (global face: no per-name 404 disposition exists). The
  behavioral assertion promises HTTP 200 with ClusterStatus "even on a
  single-node deployment"; the type constraint fixes the promised shape
  (peer_id uint64, raft_state enum, commit_index uint64, peers map). Sequence:
  (P0) documented no-body control probe (R7 lesson: decisive baseline
  evidence) -> type-side shape check + baseline view fingerprint (key set +
  cluster-mode value); then each mutation is verifiably landed via count
  controls before probing the cluster face again: (P1) create collection,
  (P2) upsert 8 points wait=true (count control = 8), (P3) create payload
  index, (P4) delete 4 points wait=true (count control = 4), (P5) drop
  collection + quiescence control (describe = 404) -> final probe. Judged at
  every phase: GET /cluster must stay 200 with a parseable result object
  whose key set and cluster-mode value are IDENTICAL to baseline (a
  data-plane mutation flipping the cluster view = Type4); 5xx = Type3 after
  /healthz liveness; transport failure = inline /healthz probe. Sequential
  matrix -> single occurrence is decisive (the >=2 damping applies only to
  race-window scripts 002/003).
  [chunk_cluster+status coverage: count_consistency(state-transition matrix,
   strategy 1 + post-delete phase, strategy 2) x qdrant_behavioral_cluster_status_001
   (+ shape clause of qdrant_type_cluster_status_001 on the positive side)]
Oracle: every phase probe returns 200 with result a JSON object whose key set
  and "status" value equal the baseline fingerprint; baseline and final
  probes contain all four documented ClusterStatus fields with peer_id
  int>=0, raft_state in {Leader, Follower, Candidate, PreCandidate,
  Terminated}, commit_index int>=0, peers dict (missing/mistyped =
  Type4_StateLogicViolation); any 5xx = Type3_RuntimeFailure only after
  /healthz 200; count controls 8 then 4 must hold (drift = Type4)
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

RAFT_STATES = ("Leader", "Follower", "Candidate", "PreCandidate", "Terminated")
REQUIRED_FIELDS = ("peer_id", "raft_state", "commit_index", "peers")


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """Forwarding wrapper (R7 standing lesson: timeout/path_params/body/
    query_params forwarded exactly; all HTTP exits go through here)."""
    return rt.request(method, path_key, body=body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def alive():
    """Liveness re-check via the lightweight documented health endpoint."""
    hs, hraw = rt.request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_view(raw):
    """Return (result_dict, None) on a parseable 200 body else (None, detail)."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return None, f"unparseable body ({e})"
    if not isinstance(b, dict):
        return None, "top-level body not an object"
    node = b.get("result")
    if not isinstance(node, dict):
        return None, "result envelope not an object"
    return node, None


def type_defects(node, where):
    """Type-side check of the four documented ClusterStatus fields."""
    out = []
    missing = [f for f in REQUIRED_FIELDS if f not in node]
    if missing:
        out.append(f"({where}) documented ClusterStatus fields missing: {missing}")
    pid = node.get("peer_id")
    if "peer_id" in node and (not isinstance(pid, int) or isinstance(pid, bool) or pid < 0):
        out.append(f"({where}) peer_id not uint64-compatible: {pid!r}")
    rs = node.get("raft_state")
    if "raft_state" in node and (not isinstance(rs, str) or rs not in RAFT_STATES):
        out.append(f"({where}) raft_state not in enum {RAFT_STATES}: {rs!r}")
    ci = node.get("commit_index")
    if "commit_index" in node and (not isinstance(ci, int) or isinstance(ci, bool) or ci < 0):
        out.append(f"({where}) commit_index not uint64-compatible: {ci!r}")
    if "peers" in node and not isinstance(node.get("peers"), dict):
        out.append(f"({where}) peers not a map: {type(node.get('peers')).__name__}")
    return out


def exact_count(name):
    """Control read: exact point count or None on transport/parse failure."""
    s, raw = safe_request("POST", "count", body={"exact": True},
                          path_params={"name": name})
    if s != 200:
        return None
    node, err = parse_view(raw)
    if node is None or not isinstance(node.get("count"), int):
        return None
    return node["count"]


def probe(where, base_keys, base_mode, defects):
    """One cluster-face probe. Returns False only on fatal (dead service)."""
    s, raw = safe_request("GET", "cluster_status")
    print(f"[{where}] status={s} raw={raw[:300]}")
    if s == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[{where} transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            return False
        print(f"ENV_ISSUE: transport failure at {where}; liveness re-checked via /healthz")
        return True
    if 500 <= s <= 599:
        if alive():
            defects.append(
                f"({where}) GET cluster status returned {s} (200 promised by "
                f"behavioral assertion, service alive per /healthz) — "
                f"Type3_RuntimeFailure — raw={raw[:200]}"
            )
            return True
        return False
    if s != 200:
        print(f"OBSERVATION ({where}): returned {s} — unexpected disposition, "
              f"not in promise set; recorded, not judged")
        return True
    node, err = parse_view(raw)
    if node is None:
        defects.append(
            f"({where}) 200 but {err} — promised ClusterStatus object — "
            f"Type4_StateLogicViolation — raw={raw[:200]}"
        )
        return True
    if base_keys is not None and frozenset(node.keys()) != base_keys:
        defects.append(
            f"({where}) cluster-view key set changed across a data-plane "
            f"transition (baseline {sorted(base_keys)} -> {sorted(node.keys())}) "
            f"— incoherent cluster view — Type4_StateLogicViolation"
        )
    if base_mode is not None and node.get("status") != base_mode:
        defects.append(
            f"({where}) cluster-mode value flipped from {base_mode!r} to "
            f"{node.get('status')!r} due to a data-plane mutation (no "
            f"deployment change) — Type4_StateLogicViolation"
        )
    return True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scst1_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    try:
        # ---- P0: documented no-body control probe (baseline fingerprint) ----
        s, raw = safe_request("GET", "cluster_status")
        print(f"[P0 control probe: documented no-body GET] status={s} raw={raw[:300]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[P0 transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
            return "SCRIPT_ERROR"
        if s != 200:
            print(f"SETUP_ERROR: baseline cluster status = {s}")
            return "SCRIPT_ERROR"
        node, err = parse_view(raw)
        if node is None:
            DEFECTS.append(
                f"(P0) baseline 200 but {err} — promised ClusterStatus object — "
                f"Type4_StateLogicViolation — raw={raw[:200]}"
            )
            base_keys, base_mode = None, None
        else:
            base_keys = frozenset(node.keys())
            base_mode = node.get("status")
            print(f"[P0 fingerprint] keys={sorted(base_keys)} mode={base_mode!r}")
            for d in type_defects(node, "P0"):
                DEFECTS.append(d + " — Type4_StateLogicViolation")

        # ---- P1: create collection ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"
        if not probe("P1 after create", base_keys, base_mode, DEFECTS):
            return "SCRIPT_ERROR"

        # ---- P2: upsert 8 points (wait=true) + count control = 8 ----
        pts = [{"id": i, "vector": [0.1 * (i + 1), 0.2, 0.3, 0.4],
               "payload": {"city": "tokyo"}} for i in range(8)]
        s, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[P2 seed upsert wait=true] status={s} raw={raw[:200]}")
        if s not in (200, 201):
            print(f"SETUP_ERROR: seed upsert = {s}")
            return "SCRIPT_ERROR"
        cnt = exact_count(C)
        print(f"[P2 count control] exact={cnt} expected=8")
        if cnt is not None and cnt != 8:
            DEFECTS.append(
                f"(P2) count control drift after wait=true upsert: expected 8, "
                f"got {cnt} — Type4_StateLogicViolation"
            )
        if not probe("P2 after upsert", base_keys, base_mode, DEFECTS):
            return "SCRIPT_ERROR"

        # ---- P3: create payload index (config-plane mutation) ----
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": "city", "field_schema": "keyword"},
                              path_params={"name": C})
        print(f"[P3 create index] status={s} raw={raw[:200]}")
        if s not in (200, 201):
            print(f"ENV_ISSUE: index create = {s} (phase mutation not landed; "
                  f"following probe still valid)")
        if not probe("P3 after index create", base_keys, base_mode, DEFECTS):
            return "SCRIPT_ERROR"

        # ---- P4: delete 4 points (wait=true) + count control = 4 ----
        s, raw = safe_request("POST", "delete_points", body={"points": [0, 1, 2, 3]},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[P4 delete wait=true] status={s} raw={raw[:200]}")
        if s not in (200, 201):
            print(f"SETUP_ERROR: delete = {s}")
            return "SCRIPT_ERROR"
        cnt = exact_count(C)
        print(f"[P4 count control] exact={cnt} expected=4")
        if cnt is not None and cnt != 4:
            DEFECTS.append(
                f"(P4) count control drift after wait=true delete: expected 4, "
                f"got {cnt} — Type4_StateLogicViolation"
            )
        if not probe("P4 after delete", base_keys, base_mode, DEFECTS):
            return "SCRIPT_ERROR"

        # ---- P5: drop + quiescence control + post-delete probe (strategy 2) ----
        ds, draw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[P5 drop] status={ds} raw={draw[:200]}")
        if ds not in (200, 404):
            print(f"SETUP_ERROR: drop returned {ds}")
            return "SCRIPT_ERROR"
        gone = False
        for _ in range(10):
            try:
                cs, craw = safe_request("GET", "describe_collection",
                                        path_params={"name": C})
            except Exception:
                cs = -1
            if cs == 404:
                gone = True
                break
            time.sleep(0.4)
        print(f"[P5 quiescence] describe({C}) -> 404? {gone}")
        if not gone:
            print("ENV_ISSUE: drop not observable via describe within retries — "
                  "post-delete phase judged on best effort")
        if not probe("P5 post-delete", base_keys, base_mode, DEFECTS):
            return "SCRIPT_ERROR"
        # final type-side re-check: the shape promise must hold at the end too
        s, raw = safe_request("GET", "cluster_status")
        print(f"[P5 final type-check] status={s} raw={raw[:300]}")
        if s == 200:
            node, perr = parse_view(raw)
            if node is not None:
                for d in type_defects(node, "P5"):
                    DEFECTS.append(d + " — Type4_StateLogicViolation")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        _v = main()
    except Exception as _e:  # never exit without the strict VERDICT line
        print(f"FATAL: {_e}")
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
