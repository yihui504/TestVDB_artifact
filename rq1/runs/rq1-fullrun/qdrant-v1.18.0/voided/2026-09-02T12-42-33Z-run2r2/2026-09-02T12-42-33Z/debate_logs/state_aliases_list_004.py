#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_aliases_list_004
# strategy: concurrent
# endpoint: aliases+list
# constraint_ids: qdrant_behavioral_aliases_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collections-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness — alias-map churn vs the global listing face)
"""
Attack: concurrent (Strategy 4 concurrent operations + Strategy 7 lifecycle-churn
  discipline on the GLOBAL alias listing: N writer threads concurrently create N
  distinct aliases w_i->A while reader threads hammer GET /aliases; after settle
  the prefix map must equal exactly {w_i: A}; then N concurrent delete_alias; after
  settle the prefix map must be empty; reader reads must stay 200 + well-formed
  result.aliases throughout, with 5xx/reset reproduced before any Type3 claim)
  x qdrant_behavioral_aliases_list_001 (endpoint aliases+list; GET /aliases returns
  200 with a list of {alias, collection_name} across all collections)
Rationale (G6 mutation choice): concurrent name-keyed map mutations are the timing
  window most likely to break the listing invariant — last-writer races surface as
  lost/duplicate rows after settle, and contention on the consensus path surfaces
  as 5xx during churn (qdrant #9229 "Expected at least one response" shape).
Oracle: every reader GET /aliases during churn returns 200 with a well-formed
  result.aliases list (each entry has alias_name); any 5xx/conn-reset reproduced
  twice with healthz alive = Type3_RuntimeFailure; after create-churn settle the
  prefix map = exactly {w_i: A for all successfully applied creates} (loss or
  duplicate = Type4_StateLogicViolation); after delete-churn settle the prefix map
  = {} (residue = Type4_StateLogicViolation); healthz dead = SCRIPT_ERROR (env)
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

N_THREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10") or "10")
N_READERS = 3


# ---------------- helpers ----------------
def parse_aliases(raw):
    """result.aliases[] -> (mapping, anomalies). None mapping = wrong envelope shape."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None, []
    node = b.get("result") if isinstance(b, dict) else None
    items = node.get("aliases") if isinstance(node, dict) else None
    if not isinstance(items, list):
        return None, []
    mapping, anoms = {}, []
    for it in items:
        if isinstance(it, dict) and "alias_name" in it:
            a = it["alias_name"]
            if a in mapping:
                anoms.append(f"duplicate-row:{a}")
            mapping[a] = it.get("collection_name")
        else:
            anoms.append(f"malformed-entry:{str(it)[:60]}")
    return mapping, anoms


class Obs:
    """Thread-safe observation collector (reader + writer evidence)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reader_5xx = []        # (status, raw_snip) — reproduced/reproducible server failures
        self.reader_transients = []  # single 5xx/0 that did NOT reproduce on immediate re-probe
        self.reader_malformed = []   # 200 with non-list result.aliases or entries lacking alias_name
        self.env_down = []           # healthz dead observations

    def add(self, bucket, item):
        with self.lock:
            getattr(self, bucket).append(item)


def face_read(pfx, obs, tag):
    """One GET /aliases read with face-level adjudication.

    Returns (mode, prefix_map_or_None, status, raw). mode in {OK, FACE_DEFECT,
    ENV_DOWN, TRANSIENT}. Content (which aliases are present) is NOT judged
    mid-churn — reconciliation happens after settle.
    """
    s, raw = rt.request("GET", "list_aliases")
    if s == 0 or 500 <= s <= 599:
        hs, hraw = rt.request("GET", "healthz")
        if hs != 200:
            obs.add("env_down", f"healthz={hs} during {tag} after face status {s}")
            return "ENV_DOWN", None, s, raw
        # reproduction discipline (strategy 7): a single sporadic 5xx is re-probed
        s2, raw2 = rt.request("GET", "list_aliases")
        if s2 == 0 or 500 <= s2 <= 599:
            obs.add("reader_5xx", (s, str(raw)[:120], s2, str(raw2)[:120]))
            return "ENV_DOWN", None, s2, raw2
        obs.add("reader_transients", (s, str(raw)[:120]))
        s, raw = s2, raw2
    if s in (401, 403):
        hs, hraw = rt.request("GET", "healthz")
        if hs != 200:
            obs.add("env_down", f"healthz={hs} during {tag} after face status {s}")
        return "ENV_DOWN", None, s, raw
    v = rt.judge_200(s, raw, setup_ok=True)
    if v != "NO_DEFECT":
        return "FACE_DEFECT", None, s, raw
    mapping, anoms = parse_aliases(raw)
    if mapping is None:
        return "FACE_DEFECT", None, s, raw
    if anoms:
        obs.add("reader_malformed", [x for x in anoms if pfx in x] or anoms[:3])
    return "OK", {a: c for a, c in mapping.items() if str(a).startswith(pfx)}, s, raw


def reader_loop(pfx, obs, stop_evt, rid):
    n = 0
    while not stop_evt.is_set():
        mode, _, s, raw = face_read(pfx, obs, f"reader{rid}")
        n += 1
        if mode == "FACE_DEFECT":
            # 200-without-list or non-auth 4xx on a parameterless legal read is a
            # face-promise violation observable mid-churn; record evidence, keep looping
            obs.add("reader_malformed", f"reader{rid}: status={s} raw={str(raw)[:120]}")
        time.sleep(0.03)
    print(f"[reader{rid}] iterations={n}")


def writer_create(coll, alias, obs, results, i):
    s, raw = rt.request("POST", "update_aliases", {"actions": [
        {"create_alias": {"collection_name": coll, "alias_name": alias}},
    ]})
    if s in (200, 201):
        results[i] = "applied"
    elif s == 0 or 500 <= s <= 599:
        hs, _ = rt.request("GET", "healthz")
        if hs != 200:
            obs.add("env_down", f"healthz={hs} after writer{i} create status {s}")
        results[i] = f"server-error:{s}"
    else:
        results[i] = f"rejected:{s}"


def writer_delete(coll, alias, obs, results, i):  # noqa: ARG001 (coll unused; unified signature)
    s, raw = rt.request("POST", "update_aliases", {"actions": [
        {"delete_alias": {"alias_name": alias}},
    ]})
    if s in (200, 201):
        results[i] = "deleted"
    elif s == 0 or 500 <= s <= 599:
        hs, _ = rt.request("GET", "healthz")
        if hs != 200:
            obs.add("env_down", f"healthz={hs} after writer{i} delete status {s}")
        results[i] = f"server-error:{s}"
    else:
        results[i] = f"rejected:{s}"


def reconcile(pfx, expected, label, obs):
    """Settled read + exact expected-vs-actual comparison (one retry after 1s)."""
    mode, mine, s, raw = face_read(pfx, obs, f"reconcile:{label}")
    if mode == "FACE_DEFECT":
        print(f"[reconcile:{label}] FACE_DEFECT status={s} raw={str(raw)[:200]}")
        return [
            f"{label}: settled GET /aliases face failed ({s}) — unit promises 200 with "
            f"the alias list raw={str(raw)[:200]}"
        ], mode
    if mode != "OK":
        print(f"[reconcile:{label}] mode={mode} status={s}")
        return [], mode
    if mine != expected:
        print(f"[reconcile:{label}] first read mismatch: {mine} != {expected}; retrying after 1s")
        time.sleep(1.0)
        mode, mine, s, raw = face_read(pfx, obs, f"reconcile:{label}:retry")
        if mode != "OK":
            return [], mode
    problems = []
    if mine != expected:
        missing = sorted(set(expected) - set(mine))
        extra = sorted(set(mine) - set(expected))
        wrong = {a: (mine[a], expected[a]) for a in set(mine) & set(expected) if mine[a] != expected[a]}
        problems.append(
            f"{label}: settled prefix map mismatch — missing={missing} extra(residue)={extra} "
            f"wrong-targets={wrong} expected={len(expected)} rows "
            f"— Type4_StateLogicViolation"
        )
    else:
        print(f"[reconcile:{label}] OK: {len(expected)} rows as expected")
    return problems, "OK"


def run_churn(pfx, coll, aliases, obs, worker_fn, readers, stop_evt):
    results = [None] * len(aliases)
    threads = [threading.Thread(target=worker_fn, args=(coll, a, obs, results, i))
               for i, a in enumerate(aliases)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop_evt.set()
    for t in readers:
        t.join()
    return results


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sal4c_" + TS + "_"          # unique per run; tolerates concurrent siblings
    A = PFX + "colA"
    DEFECTS = []
    created = []
    obs = Obs()

    try:
        ok, err = rt.setup_default(A, 128, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {A}: {err}")
            return "SCRIPT_ERROR"
        created.append(A)

        aliases = [f"{PFX}w{i}" for i in range(N_THREADS)]

        def env_fatal():
            return bool(obs.env_down)

        # ---- phase 1: concurrent creates + concurrent reader churn ----
        stop1 = threading.Event()
        readers1 = [threading.Thread(target=reader_loop, args=(PFX, obs, stop1, r))
                    for r in range(N_READERS)]
        for t in readers1:
            t.start()
        results = run_churn(PFX, A, aliases, obs, writer_create, readers1, stop1)
        print(f"[phase1 writer results] {results}")
        if env_fatal():
            print(f"ENV_DOWN during phase1: {obs.env_down}")
            return "SCRIPT_ERROR"

        applied = sorted(a for a, r in zip(aliases, results) if r == "applied")
        rejected = [(a, r) for a, r in zip(aliases, results) if str(r).startswith("rejected:")]
        server_err = [(a, r) for a, r in zip(aliases, results) if str(r).startswith("server-error:")]
        if rejected:
            DEFECTS.append(
                f"phase1: concurrent create_alias rejected for distinct names: {rejected} "
                f"— concurrent mutation must not be refused (distinct alias names, live target)"
                f"— Type3_RuntimeFailure"
            )
        if server_err:
            DEFECTS.append(
                f"phase1: concurrent create_alias hit server errors (healthz alive): "
                f"{server_err} — Type3_RuntimeFailure"
            )

        d, mode = reconcile(PFX, {a: A for a in applied}, "after-create-churn", obs)
        DEFECTS += d
        if mode == "ENV_DOWN" and env_fatal():
            return "SCRIPT_ERROR"

        # ---- phase 2: concurrent deletes + concurrent reader churn ----
        stop2 = threading.Event()
        readers2 = [threading.Thread(target=reader_loop, args=(PFX, obs, stop2, r))
                    for r in range(N_READERS)]
        for t in readers2:
            t.start()
        dres = run_churn(PFX, A, applied, obs, writer_delete, readers2, stop2)
        print(f"[phase2 writer results] {dres}")
        if env_fatal():
            print(f"ENV_DOWN during phase2: {obs.env_down}")
            return "SCRIPT_ERROR"

        d_rejected = [(a, r) for a, r in zip(applied, dres) if str(r).startswith("rejected:")]
        d_server_err = [(a, r) for a, r in zip(applied, dres) if str(r).startswith("server-error:")]
        if d_rejected:
            DEFECTS.append(
                f"phase2: concurrent delete_alias rejected for existing aliases: {d_rejected} "
                f"— Type3_RuntimeFailure"
            )
        if d_server_err:
            DEFECTS.append(
                f"phase2: concurrent delete_alias hit server errors (healthz alive): "
                f"{d_server_err} — Type3_RuntimeFailure"
            )
        deleted = {a for a, r in zip(applied, dres) if r == "deleted"}
        expected_final = {a: A for a in applied if a not in deleted}
        d, mode = reconcile(PFX, expected_final, "after-delete-churn", obs)
        DEFECTS += d
        if mode == "ENV_DOWN" and env_fatal():
            return "SCRIPT_ERROR"

        # ---- reader-side evidence roll-up ----
        if obs.reader_5xx:
            DEFECTS.append(
                f"reader evidence: reproduced 5xx/conn-reset on GET /aliases during churn "
                f"(healthz alive): {obs.reader_5xx[:5]} — Type3_RuntimeFailure"
            )
        if obs.reader_malformed:
            DEFECTS.append(
                f"reader evidence: malformed listing payloads during churn: "
                f"{obs.reader_malformed[:5]} — result.aliases must stay a well-formed list"
            )
        if obs.reader_transients:
            print(f"INFO transient (not reproduced) face failures during churn: {obs.reader_transients[:5]}")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.request("POST", "update_aliases", {"actions": [
                {"delete_alias": {"alias_name": f"{PFX}w{i}"}} for i in range(N_THREADS)
            ]})
        except Exception:
            pass
        for c in created:
            try:
                rt.drop_collection(c)
            except Exception:
                pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
