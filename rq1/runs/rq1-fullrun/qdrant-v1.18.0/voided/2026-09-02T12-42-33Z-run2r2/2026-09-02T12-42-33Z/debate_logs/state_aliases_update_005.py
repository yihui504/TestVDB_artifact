#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_aliases_update_005
# strategy: concurrent
# endpoint: aliases+update
# constraint_ids: qdrant_state_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (lifecycle x alias-table race: collection drop interleaving an alias batch)
"""
Attack: concurrent lifecycle x access (Strategy 7 variant, mutation side of
  the atomicity constraint): thread L cycles create->drop of collection C
  (the alias target); thread W applies the alias batch
  [delete_alias al, create_alias al->C] over and over; thread R samples the
  global alias face GET /aliases. The constraint under fire is the SECOND
  clause of qdrant_state_aliases_update_001: 'no collection modification
  can interleave between the alias operations of one request' — a drop that
  lands between a batch's operations must not leave the alias table
  self-inconsistent (rows to nowhere / 5xx panic / malformed rows).
  Judged signals: 5xx from update_aliases or GET /aliases during the race
  (>=2 occurrences, strategy-7 reproduction rule; a single one is logged as
  an inconclusive observation); 404/400 while C is absent is CORRECT
  'temporarily unavailable' semantics, not a defect; after quiescence (C
  verifiably dropped) every surviving prefix-alias row must point to a
  LIVE collection (describe target = 200) and rows must be well-formed
  x qdrant_state_aliases_update_001
  [chunk_aliases+update coverage: concurrent(lifecycle) x
   qdrant_state_aliases_update_001]
Oracle: during the race GET /aliases keeps answering 200 and update_aliases
  never answers 5xx (>=2 x 5xx = Type3_RuntimeFailure); after the final
  drop of C (describe control = 404) and settle, GET /aliases lists no
  prefix alias whose target describes as 404 (dangling row =
  Type4_StateLogicViolation) and contains no duplicate/malformed rows
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
def parse_aliases(raw):
    """result.aliases[] -> (mapping alias_name->collection_name, anomalies list)."""
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


def alive():
    """D3b liveness re-check via the lightweight health endpoint."""
    hs, hraw = rt.request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sau5_" + TS + "_"
    C = PFX + "colC"
    AL = PFX + "al"
    N_CYCLES = max(3, int(os.environ.get("TESTVDB_ALIAS_LIFECYCLE_CYCLES", "8")))
    DEFECTS = []
    lock = threading.Lock()
    writer_5xx = []       # 5xx from update_aliases during the race
    face_5xx = []         # 5xx from GET /aliases during the race
    env_failures = []
    stop_evt = threading.Event()

    def lifecycle_thread():
        """Thread L: create -> drop cycles of the alias target C."""
        for i in range(N_CYCLES):
            if stop_evt.is_set():
                return
            try:
                ok, err = rt.setup_default(C, 4, "Cosine")
                if not ok:
                    print(f"[L#{i}] create not ok: {err[:120]}")
            except Exception as e:
                print(f"[L#{i}] create exception: {e}")
            time.sleep(0.08)
            try:
                rt.request("DELETE", "drop_collection", path_params={"name": C})
            except Exception as e:
                print(f"[L#{i}] drop exception: {e}")
            time.sleep(0.08)
        print("[L] lifecycle loop finished")

    def writer_thread():
        """Thread W: alias batch referencing C while C's existence flips."""
        for i in range(N_CYCLES * 2):
            if stop_evt.is_set():
                return
            try:
                s, raw = rt.request("POST", "update_aliases", {"actions": [
                    {"delete_alias": {"alias_name": AL}},
                    {"create_alias": {"collection_name": C, "alias_name": AL}},
                ]})
                if s == 0:
                    with lock:
                        env_failures.append(f"W#{i}: transport {str(raw)[:120]}")
                elif 500 <= s <= 599:
                    with lock:
                        writer_5xx.append(f"W#{i}: {s} raw={str(raw)[:150]}")
                # 404/400 while C is mid-drop = correct unavailable semantics
            except Exception as e:
                with lock:
                    env_failures.append(f"W#{i}: exception {str(e)[:120]}")
            time.sleep(0.05)
        print("[W] writer loop finished")

    def reader_thread():
        """Thread R: sample the global alias face."""
        for i in range(N_CYCLES * 4):
            if stop_evt.is_set():
                return
            try:
                s, raw = rt.request("GET", "list_aliases")
                if s == 0:
                    with lock:
                        env_failures.append(f"R#{i}: transport {str(raw)[:120]}")
                elif 500 <= s <= 599:
                    with lock:
                        face_5xx.append(f"R#{i}: {s} raw={str(raw)[:150]}")
                elif s == 200:
                    mapping, anoms = parse_aliases(raw)
                    if mapping is None:
                        with lock:
                            face_5xx.append(
                                f"R#{i}: 200 but alias envelope unparseable "
                                f"raw={str(raw)[:150]}")
                    else:
                        mine = [x for x in anoms if PFX in str(x)]
                        if mine:
                            with lock:
                                face_5xx.append(f"R#{i}: malformed rows {mine}")
            except Exception as e:
                with lock:
                    env_failures.append(f"R#{i}: exception {str(e)[:120]}")
            time.sleep(0.03)
        print("[R] reader loop finished")

    try:
        # ---- setup: C exists once so the first writer batch can legally land ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"
        s, raw = rt.request("POST", "update_aliases", {"actions": [
            {"create_alias": {"collection_name": C, "alias_name": AL}},
        ]})
        print(f"[seed alias {AL}->{C}] status={s} raw={raw[:300]}")
        if s != 200:
            print(f"SETUP_ERROR seed alias: {s} {raw[:200]}")
            return "SCRIPT_ERROR"

        # ---- race window ----
        threads = [
            threading.Thread(target=lifecycle_thread, daemon=True),
            threading.Thread(target=writer_thread, daemon=True),
            threading.Thread(target=reader_thread, daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        stop_evt.set()

        # ---- quiescence: C must be verifiably gone before judging residue ----
        gone = False
        for _ in range(20):
            try:
                s, _raw = rt.request("GET", "describe_collection", path_params={"name": C})
            except Exception:
                s = -1
            if s == 404:
                gone = True
                break
            time.sleep(0.5)
        print(f"[quiescence] describe({C}) -> 404? {gone}")
        if not gone:
            try:
                rt.request("DELETE", "drop_collection", path_params={"name": C})
            except Exception:
                pass
            time.sleep(1.0)
        time.sleep(1.0)  # settle any async alias-table cleanup

        # ---- post-race alias table: no dangling rows, well-formed entries ----
        s, raw = rt.request("GET", "list_aliases")
        print(f"[final list_aliases] status={s} raw={raw[:800]}")
        if s == 0 or 500 <= s <= 599 or s in (401, 403):
            alive()
            return "SCRIPT_ERROR"
        if s != 200:
            DEFECTS.append(
                f"post-race: GET /aliases returned {s} after quiescence — "
                f"raw={str(raw)[:200]}"
            )
        else:
            mapping, anoms = parse_aliases(raw)
            if mapping is None:
                DEFECTS.append(
                    f"post-race: 200 but alias envelope unparseable — "
                    f"raw={str(raw)[:200]}"
                )
            else:
                mine = {a: c for a, c in mapping.items() if str(a).startswith(PFX)}
                my_anoms = [x for x in anoms if PFX in str(x)]
                if my_anoms:
                    DEFECTS.append(
                        f"post-race: malformed/duplicate alias rows: {my_anoms} — "
                        f"Type4_StateLogicViolation"
                    )
                for a, tgt in sorted(mine.items()):
                    try:
                        ts, traw = rt.request("GET", "describe_collection",
                                              path_params={"name": tgt})
                    except Exception:
                        ts, traw = -1, "exception"
                    print(f"[residue check] {a}->{tgt} describe={ts}")
                    if ts == 404:
                        DEFECTS.append(
                            f"post-race: alias {a} still listed pointing at {tgt} "
                            f"whose describe returns 404 — dangling alias row after "
                            f"target deletion under concurrent alias batches — "
                            f"Type4_StateLogicViolation"
                        )
                    elif ts != 200:
                        print(f"[residue check] unexpected describe status {ts} for "
                              f"{tgt} — not judged (environment-class)")
                if not mine:
                    print("post-race OK: no surviving prefix aliases (auto-cleanup)")

        # ---- race-window 5xx (strategy-7 reproduction rule: >=2 occurrences) ----
        for tag, bucket in (("update_aliases", writer_5xx), ("GET /aliases", face_5xx)):
            if len(bucket) >= 2:
                DEFECTS.append(
                    f"race window: {len(bucket)} x 5xx/panic on {tag} while the "
                    f"collection lifecycle interleaved the alias batch — graceful "
                    f"404/503 was expected — Type3_RuntimeFailure — samples: "
                    f"{bucket[:3]}"
                )
            elif bucket:
                print(f"OBSERVATION (inconclusive, <2 occurrences): {tag}: {bucket}")
        if env_failures and not DEFECTS:
            print(f"ENV_ISSUES: {env_failures[:3]}")
            if not alive():
                return "SCRIPT_ERROR"

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        stop_evt.set()
        try:
            rt.request("POST", "update_aliases",
                       {"actions": [{"delete_alias": {"alias_name": AL}}]})
        except Exception:
            pass
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
