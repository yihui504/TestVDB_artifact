#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_aliases_update_003
# strategy: search_correctness
# endpoint: aliases+update
# constraint_ids: qdrant_bc_alias_switch_atomic_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - atomicity promise observed from the read side)
"""
Attack: search_correctness x qdrant_bc_alias_switch_atomic_001 (chunk_aliases+update; strategy 5, concurrent no-observable-intermediate-state face)
Oracle: with 3 reader threads continuously scrolling through alias 'live' while the writer performs >=8 atomic switch batches (live -> CB -> CA -> ...), EVERY reader request returns HTTP 200 and each response's ids are homogeneous (all within {1..5} = CA fixture or all within {101..105} = CB fixture, never empty, never mixed); a single 404 means an intermediate state (alias resolving to nothing) leaked to readers => Type4_StateLogicViolation; a 5xx/transport failure while /healthz stays alive => Type3_RuntimeFailure; every switch batch must return 200 (a rejected legal switch => Type1_IllegalRejection)

Behavioral contract qdrant_bc_alias_switch_atomic_001 (evidence_tier=explicit):
  expected_behavior: "after a 200 the alias resolves to the new target;
  during and after the atomic batch no collection modification can
  interleave between alias operations (alias changes are ATOMIC per the
  spec description)"; scenario explicitly names "concurrent/sequential
  reads through alias 'live'".

The concurrent face of the contract: alias 'live' is flipped between two
5-point collections repeatedly while readers resolve it. Because the two
fixtures carry disjoint id sets, the owning collection of any read is
identifiable from the response itself. Atomicity forbids any read from
observing the window between the batch's delete and create: no 404, no
empty result, no mixed snapshot. This is exactly the zero-downtime
switching semantics aliases exist to provide.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP
via rt.request path_key (update_aliases / scroll / upsert_points / count /
create_collection via setup_default / drop_collection / healthz); literal
paths forbidden.
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

SETUP_OK = False


# ---------------- helpers ----------------
def parse_json(raw):
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def scroll_ids(raw):
    b = parse_json(raw)
    if b is None:
        return None
    res = b.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("points"), list):
        return None
    return [p.get("id") for p in res["points"] if isinstance(p, dict)]


def count_value(raw):
    b = parse_json(raw)
    if b is None:
        return None
    res = b.get("result")
    if isinstance(res, dict) and isinstance(res.get("count"), int):
        return res["count"]
    return None


def liveness_ok():
    try:
        st, _ = rt.request("GET", "healthz", timeout=5)
        return st == 200
    except Exception:
        return False


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


TS = str(int(time.time()))
PREFIX = f"s2au3_{TS}_"
CA = PREFIX + "ca"
CB = PREFIX + "cb"
LIVE = PREFIX + "live"
IDS_A = frozenset(range(1, 6))
IDS_B = frozenset(range(101, 106))
COLLECTIONS = (CA, CB)
ALIASES = (LIVE,)
FLIPS = 8
READERS = 3

READS = []          # (status, ids_or_None, raw_snippet)
READS_LOCK = threading.Lock()
STOP = threading.Event()


def reader():
    """Continuously resolve 'live' by scrolling through it; record every observation."""
    while not STOP.is_set():
        try:
            st, raw = rt.request("POST", "scroll",
                                 {"limit": 3, "with_payload": False, "with_vector": False},
                                 path_params={"name": LIVE}, timeout=10)
        except Exception as e:
            with READS_LOCK:
                READS.append((0, None, f"reader-exception:{e}"))
            continue
        with READS_LOCK:
            READS.append((st, scroll_ids(raw), raw[:120]))


def cleanup():
    for al in ALIASES:
        try:
            rt.request("POST", "update_aliases",
                       {"actions": [{"delete_alias": {"alias_name": al}}]}, timeout=15)
        except Exception:
            pass
    for name in COLLECTIONS:
        try:
            rt.drop_collection(name)
        except Exception:
            pass


try:
    # ---- setup: two disjoint fixtures + live alias on CA ----
    for name in COLLECTIONS:
        ok, err = rt.setup_default(name, dim=4, metric="Cosine")
        if not ok:
            script_error(f"setup failed creating {name}: {err}")
    for name, ids in ((CA, sorted(IDS_A)), (CB, sorted(IDS_B))):
        pts = [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in ids]
        s, raw = rt.request("PUT", "upsert_points", {"points": pts},
                            path_params={"name": name})
        print(f"setup upsert {name}: status={s} raw={raw[:160]}")
        if s not in (200, 201):
            script_error(f"setup upsert into {name} failed: {s} {raw[:200]}")
    for name in COLLECTIONS:
        seen = None
        for _ in range(12):
            cs, craw = rt.request("POST", "count", {"exact": True},
                                  path_params={"name": name}, timeout=10)
            seen = count_value(craw) if cs == 200 else None
            if seen == 5:
                break
            time.sleep(0.3)
        if seen != 5:
            script_error(f"fixture {name} not countable at 5 (last count={seen})")
    s, raw = rt.request("POST", "update_aliases", {"actions": [
        {"create_alias": {"collection_name": CA, "alias_name": LIVE}},
    ]})
    print(f"setup live->{CA}: status={s} raw={raw[:200]}")
    if s == 0 or 500 <= s <= 599:
        alive = liveness_ok()
        script_error(f"alias registration unavailable (status={s}, server alive={alive}); no defect conclusion")
    if s != 200:
        script_error(f"setup create_alias failed: {s} {raw[:300]}")
    SETUP_OK = True

    # ---- attack: concurrent readers + repeated atomic switches ----
    threads = [threading.Thread(target=reader) for _ in range(READERS)]
    for t in threads:
        t.start()
    time.sleep(0.3)  # let readers spin up before the first flip

    flip_failures = []
    for i in range(FLIPS):
        target = CB if i % 2 == 0 else CA
        st, raw = rt.request("POST", "update_aliases", {"actions": [
            {"delete_alias": {"alias_name": LIVE}},
            {"create_alias": {"collection_name": target, "alias_name": LIVE}},
        ]}, timeout=15)
        print(f"flip {i + 1}/{FLIPS} live->{target.split('_')[-1]}: status={st} raw={raw[:120]}")
        if st != 200:
            flip_failures.append((st, target, raw[:200]))
        time.sleep(0.05)

    STOP.set()
    for t in threads:
        t.join(timeout=30)

    # ---- adjudication ----
    if flip_failures:
        st0, tgt0, raw0 = flip_failures[0]
        if st0 == 0 or 500 <= st0 <= 599:
            alive = liveness_ok()
            if not alive:
                script_error(f"a switch batch failed at transport level (status={st0}) and /healthz is dead; no defect conclusion")
            defect("Type3_RuntimeFailure",
                   f"a legal atomic switch batch returned status={st0} (server alive on /healthz); "
                   f"raw={raw0} (target={tgt0}) - crash-class failure on legal input")
        defect("Type1_IllegalRejection",
               f"a legal atomic switch batch was rejected: status={st0} raw={raw0} "
               f"(behavioral contract qdrant_bc_alias_switch_atomic_001 expects 200)")

    total = len(READS)
    if total < READERS:
        script_error(f"readers produced only {total} observations; concurrent window did not open")
    print(f"reader observations: {total}")

    n404 = [r for r in READS if r[0] == 404]
    if n404:
        defect("Type4_StateLogicViolation",
               f"{len(n404)}/{total} reads through 'live' got 404 while the alias was being "
               f"atomically switched - an intermediate state (alias resolving to nothing) is "
               f"observable, violating qdrant_bc_alias_switch_atomic_001 "
               f"'no intermediate state is observable'; first={n404[0]}")

    n5 = [r for r in READS if r[0] == 0 or 500 <= r[0] <= 599]
    if n5:
        alive = liveness_ok()
        if not alive:
            script_error(f"{len(n5)}/{total} reads failed at transport level and /healthz is dead; no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"{len(n5)}/{total} reads through 'live' returned 5xx/transport failure while the "
               f"server is alive on /healthz; first={n5[0]} - runtime failure during legal alias switch")

    nempty = [r for r in READS if r[0] == 200 and r[1] is not None and len(r[1]) == 0]
    if nempty:
        defect("Type4_StateLogicViolation",
               f"{len(nempty)}/{total} reads through 'live' returned HTTP 200 "
               f"with an EMPTY point set - the alias resolved to a collection view holding none of "
               f"the two 5-point fixtures (intermediate/empty state observable); first={nempty[0]}")

    nmixed = [r for r in READS if r[0] == 200 and r[1] is not None and len(r[1]) > 0
              and (set(r[1]) - IDS_A) and (set(r[1]) - IDS_B)]
    if nmixed:
        defect("Type4_StateLogicViolation",
               f"{len(nmixed)}/{total} reads returned ids from BOTH fixtures in one response - "
               f"a mixed snapshot across the switch boundary; first={nmixed[0]}")

    nother = [r for r in READS if r[0] == 200 and r[1] is not None and len(r[1]) > 0
              and not (set(r[1]) <= IDS_A or set(r[1]) <= IDS_B)]
    if nother:
        defect("Type4_StateLogicViolation",
               f"{len(nother)}/{total} reads returned ids belonging to NEITHER fixture "
               f"(foreign data through the alias); first={nother[0]}")

    owners_a = sum(1 for r in READS if r[0] == 200 and r[1] and set(r[1]) <= IDS_A)
    owners_b = sum(1 for r in READS if r[0] == 200 and r[1] and set(r[1]) <= IDS_B and (set(r[1]) & IDS_B))
    print(f"observations per owner: CA-like={owners_a} CB-like={owners_b} "
          f"(overlap is desirable but not required for the atomicity verdict)")

    print("VERDICT: NO_DEFECT")
finally:
    STOP.set()
    cleanup()
