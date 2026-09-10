#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_aliases_update_003
# strategy: concurrent
# endpoint: aliases+update
# constraint_ids: qdrant_bc_alias_switch_atomic_001, qdrant_state_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (alias switch mid-window: observable 'no alias' intermediate state)
"""
Attack: concurrent (the behavioral contract's own scenario, race variant):
  collections A (3 points) and B (7 points) carry alias 'live' on A; the
  main thread repeatedly applies the SINGLE-REQUEST atomic switch batch
  [delete_alias live, create_alias live->T] alternating T in {A,B} — this is
  qdrant's atomic alias retarget (the contract scenario's 'rename live from
  A to B'; the name-only rename_alias variant is covered by
  state_aliases_update_004) — while reader threads continuously exact-count
  through the alias name; the count value (3 vs 7) identifies WHICH
  collection the alias resolved to for that read
  x qdrant_bc_alias_switch_atomic_001 (after a 200 the alias resolves to the
    new target; NO intermediate state is observable during the batch)
  x qdrant_state_aliases_update_001 (alias operations of one request are atomic)
  [chunk_aliases+update coverage: concurrent x qdrant_bc_alias_switch_atomic_001;
   concurrent x qdrant_state_aliases_update_001]
Oracle: pre-race control read via 'live' -> 200 with count=3; during the
  switch window EVERY read via 'live' returns 200 with count in {3,7} — a
  404 = observable intermediate 'alias absent' state (Type4_StateLogicViolation),
  a 5xx = Type3_RuntimeFailure, a 200 with count outside {3,7} = phantom
  resolution (Type4); post-race control read -> 200 with the final batch's
  target count; a switch batch itself failing while both collections are
  alive (verified by describe controls) is also a violation (judge_200)
"""

import os
import sys
import json
import time
import threading
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


# ---------------- helpers ----------------
def alive():
    """D3b liveness re-check via the lightweight health endpoint."""
    hs, hraw = rt.request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def exact_count(name):
    """POST count {exact:true} resolved through collection name OR alias.

    Returns (status, count_or_None, raw). count key per contract
    api_endpoints[points+count].response_shape: result.count integer.
    """
    s, raw = rt.request("POST", "count", {"exact": True}, path_params={"name": name})
    if s != 200:
        return s, None, raw
    try:
        b = json.loads(raw) if raw else {}
        cnt = b.get("result", {}).get("count") if isinstance(b, dict) else None
        if not isinstance(cnt, int):
            return s, None, raw
        return s, cnt, raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def seed_points(name, n):
    """Insert n deterministic points with wait=true so exact counts are stable."""
    pts = [{"id": i, "vector": [0.10 + 0.01 * i, 0.2, 0.3, 0.4]} for i in range(n)]
    s, raw = rt.request("PUT", "upsert_points", {"points": pts},
                        path_params={"name": name}, query_params={"wait": "true"})
    print(f"[seed {name} x{n}] status={s} raw={raw[:200]}")
    return s in (200, 201)


def describe_status(name):
    s, raw = rt.request("GET", "describe_collection", path_params={"name": name})
    return s


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sau3_" + TS + "_"
    A = PFX + "colA"
    B = PFX + "colB"
    LIVE = PFX + "live"
    COUNT_A, COUNT_B = 3, 7          # distinct discriminators (both collections dim 4)
    N_SWITCHES = max(4, int(os.environ.get("TESTVDB_ALIAS_SWITCHES", "12")))
    try:
        n_readers = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))
    except ValueError:
        n_readers = 10
    n_readers = max(2, min(8, n_readers))
    print(f"plan: switches={N_SWITCHES} readers={n_readers} "
          f"discriminators A={COUNT_A} B={COUNT_B}")

    DEFECTS = []
    obs_lock = threading.Lock()
    violations = []       # (kind, detail) collected by readers
    env_failures = []     # transport-class issues (healthz-gated)

    try:
        # ---- setup: two live collections, alias on A ----
        for c in (A, B):
            ok, err = rt.setup_default(c, 4, "Cosine")
            if not ok:
                print(f"SETUP_ERROR create {c}: {err}")
                return "SCRIPT_ERROR"
        if not seed_points(A, COUNT_A) or not seed_points(B, COUNT_B):
            print("SETUP_ERROR seeding points")
            return "SCRIPT_ERROR"
        s, raw = rt.request("POST", "update_aliases", {"actions": [
            {"create_alias": {"collection_name": A, "alias_name": LIVE}},
        ]})
        print(f"[create {LIVE}->{A}] status={s} raw={raw[:300]}")
        if s != 200:
            print(f"SETUP_ERROR create alias: {s} {raw[:200]}")
            return "SCRIPT_ERROR"

        # ---- pre-race controls ----
        for c, want in ((A, COUNT_A), (B, COUNT_B)):
            s, cnt, raw = exact_count(c)
            if s != 200 or cnt != want:
                print(f"SETUP_ERROR count {c}: status={s} count={cnt} want={want}")
                return "SCRIPT_ERROR"
        s, cnt, raw = exact_count(LIVE)
        print(f"[pre-race control via {LIVE}] status={s} count={cnt}")
        if s != 200 or cnt != COUNT_A:
            print(f"SETUP_ERROR pre-race alias read: {s}/{cnt} raw={raw[:200]}")
            return "SCRIPT_ERROR"

        # ---- reader threads: sample the alias resolution continuously ----
        stop_evt = threading.Event()

        def reader(idx):
            reads = 0
            while not stop_evt.is_set():
                s, cnt, raw = exact_count(LIVE)
                reads += 1
                if s == 200:
                    if cnt is None:
                        with obs_lock:
                            violations.append(
                                ("shape", f"reader{idx}: 200 but result.count missing/"
                                 f"non-integer — violates response_shape result.count "
                                 f"integer raw={str(raw)[:150]}"))
                    elif cnt not in (COUNT_A, COUNT_B):
                        with obs_lock:
                            violations.append(
                                ("phantom", f"reader{idx}: 200 with count={cnt} via "
                                 f"alias — resolved to neither A({COUNT_A}) nor "
                                 f"B({COUNT_B}) — phantom resolution "
                                 f"Type4_StateLogicViolation"))
                elif s == 404:
                    with obs_lock:
                        violations.append(
                            ("intermediate", f"reader{idx}: 404 reading through alias "
                             f"{LIVE} while both targets are alive — observable "
                             f"intermediate 'no alias' state mid-switch — "
                             f"Type4_StateLogicViolation raw={str(raw)[:150]}"))
                elif 500 <= s <= 599:
                    with obs_lock:
                        violations.append(
                            ("server5xx", f"reader{idx}: {s} reading through alias "
                             f"{LIVE} during switch — Type3_RuntimeFailure "
                             f"raw={str(raw)[:150]}"))
                elif s == 0:
                    # transport-class: D3b liveness re-check before any conclusion
                    with obs_lock:
                        env_failures.append(f"reader{idx}: transport {str(raw)[:120]}")
                    if not alive():
                        stop_evt.set()
                        return
                time.sleep(0.02)
            print(f"[reader{idx}] finished after {reads} reads")

        threads = [threading.Thread(target=reader, args=(i,), daemon=True)
                   for i in range(n_readers)]
        for t in threads:
            t.start()

        # ---- main thread: atomic switch batches A<->B ----
        switch_failures = []
        try:
            for i in range(N_SWITCHES):
                target = B if i % 2 == 0 else A
                s, raw = rt.request("POST", "update_aliases", {"actions": [
                    {"delete_alias": {"alias_name": LIVE}},
                    {"create_alias": {"collection_name": target, "alias_name": LIVE}},
                ]})
                if s not in (200, 201):
                    switch_failures.append((i, target, s, str(raw)[:150]))
                    print(f"[switch#{i} -> {target}] status={s} raw={raw[:200]}")
                time.sleep(0.05)
        finally:
            stop_evt.set()
            for t in threads:
                t.join(timeout=10)

        final_target = B if (N_SWITCHES - 1) % 2 == 0 else A
        print(f"switch failures: {len(switch_failures)}/{N_SWITCHES}; "
              f"expected final target {final_target}")

        # ---- post-race controls ----
        alive_A, alive_B = describe_status(A) == 200, describe_status(B) == 200
        print(f"[post-race targets alive] A={alive_A} B={alive_B}")
        s, cnt, raw = exact_count(LIVE)
        print(f"[post-race control via {LIVE}] status={s} count={cnt}")

        # switch batches: legal input on live collections must succeed (judge_200)
        all_failed = len(switch_failures) == N_SWITCHES
        if all_failed:
            # construction-level failure (e.g. body shape rejected from the start)
            print(f"SCRIPT_CONDITION: every switch batch failed; first failure: "
                  f"{switch_failures[0]}")
            return "SCRIPT_ERROR"
        if switch_failures:
            for i, target, fs_, fraw in switch_failures:
                DEFECTS.append(
                    f"switch#{i} (atomic batch -> {target}) returned {fs_} while both "
                    f"collections were alive — legal batch rejected — "
                    f"raw={fraw}"
                )

        if not (alive_A and alive_B):
            print("CONTROL_ANOMALY: a target collection stopped responding — cannot judge")
            return "SCRIPT_ERROR"
        if s != 200:
            DEFECTS.append(
                f"post-race: read via alias {LIVE} returned {s} after a fully "
                f"successful switch window — alias lost/dangling — "
                f"Type4_StateLogicViolation raw={str(raw)[:200]}"
            )
        else:
            want = COUNT_B if final_target == B else COUNT_A
            if cnt != want:
                DEFECTS.append(
                    f"post-race: alias {LIVE} resolves to count={cnt}, expected {want} "
                    f"(target {final_target}) — qdrant_bc_alias_switch_atomic_001: "
                    f"after a 200 the alias must resolve to the new target — "
                    f"Type4_StateLogicViolation"
                )
            else:
                print(f"post-race OK: {LIVE} -> {final_target} (count={cnt})")

        # ---- reader observations ----
        if env_failures and not violations and not DEFECTS:
            print(f"ENV_ISSUES: {env_failures[:3]}")
            return "SCRIPT_ERROR"
        for kind, detail in violations:
            print(f"VIOLATION({kind}): {detail}")
        if violations:
            DEFECTS.extend(d for _, d in violations)

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.request("POST", "update_aliases",
                       {"actions": [{"delete_alias": {"alias_name": LIVE}}]})
        except Exception:
            pass
        for c in (A, B):
            try:
                rt.drop_collection(c)
            except Exception:
                pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
