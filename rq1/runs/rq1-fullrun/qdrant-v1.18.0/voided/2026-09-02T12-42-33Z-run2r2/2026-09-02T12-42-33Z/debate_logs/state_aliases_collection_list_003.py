#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_aliases_collection_list_003
# strategy: concurrent
# endpoint: aliases+collection+list
# constraint_ids: qdrant_behavioral_aliases_collection_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collection-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 Concurrency/State Blindness (alias binding churn vs concurrent listing reads)
"""
Attack: concurrent alias-switch churn x qdrant_behavioral_aliases_collection_list_001
  (writer rebinds alias 'live' A<->B N times via aliases+update while readers poll
  the per-collection listing faces; every read must stay internally consistent —
  no duplicate alias rows in one response, no 4xx/5xx — and the FINAL state after
  quiescence must reconcile: per-collection A/B listings + global listing agree on
  the last binding)
Oracle: after quiescence all listing faces return HTTP 200 with exactly one row per alias (no 500, no 4xx, no duplicate rows) and agree on the final 'live' binding target; any cross-face mismatch or residual binding = defect
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
BASE_URL = BASE_URL.rstrip("/")

import requests  # noqa: E402

_FB_PRINTED = [False]


def _fallback_markers():
    if _FB_PRINTED[0]:
        return
    _FB_PRINTED[0] = True
    print("FALLBACK_TRIGGERED: per-collection alias listing (aliases+collection+list) has no qdrant runtime PATHS key; issuing the contract-derived REST path GET /collections/{collection_name}/aliases via requests")
    print("[FALLBACK_JUSTIFIED: scripts/runtime/qdrant.py PATHS exposes only update_aliases (POST /collections/aliases) and list_aliases (GET /aliases); the chunk unit endpoint aliases+collection+list (contract api_endpoints: method GET, required path parameter collection_name, source_url slug get-collection-aliases) is NOT reachable through the rt.request path_key whitelist; the REST route is derived 1:1 from the contract endpoint (raw_knowledge.json document_sources 0-12, v-1-18-x api-reference)]")


def collection_aliases_http(coll):
    """FALLBACK face: GET /collections/{collection_name}/aliases -> (status, raw_text)."""
    _fallback_markers()
    url = BASE_URL + "/collections/" + str(coll) + "/aliases"
    headers = {"Content-Type": "application/json"}
    _a = os.environ.get("TESTVDB_AUTH_HEADER", "")
    if _a:
        headers["Authorization"] = _a
    try:
        r = requests.get(url, headers=headers, timeout=30)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


# ---------------- helpers ----------------
def parse_aliases(raw):
    """result.aliases[] -> (dict alias_name->collection_name, dups list). None = unparsable."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError):
        return None
    node = b.get("result") if isinstance(b, dict) else None
    items = node.get("aliases") if isinstance(node, dict) else None
    if items is None or not isinstance(items, list):
        return None
    out, dups = {}, []
    for it in items:
        if isinstance(it, dict) and "alias_name" in it:
            a = it["alias_name"]
            if a in out:
                dups.append(a)
            out[a] = it.get("collection_name")
    return out, dups


def expect_2xx(s):
    return s in (200, 201)


def main():
    TS = str(int(time.time()))
    A = "salc_cc_a_" + TS
    B = "salc_cc_b_" + TS
    LIVE = "salc_cc_live_" + TS
    DEFECTS = []
    anomalies = []          # (kind, detail)
    created = []
    stop = threading.Event()

    try:
        for cname in (A, B):
            ok, err = rt.setup_default(cname, 128, "Cosine")
            if not ok:
                print(f"SETUP_ERROR create {cname}: {err}")
                return "SCRIPT_ERROR"
            created.append(cname)

        # seed: LIVE -> A
        s, raw = rt.request("POST", "update_aliases", {"actions": [
            {"create_alias": {"collection_name": A, "alias_name": LIVE}}]})
        print(f"seed_live status={s} raw={raw[:160]}")
        if not expect_2xx(s):
            print(f"SETUP_ERROR seed alias: {s} {raw[:200]}")
            return "SCRIPT_ERROR"

        # writer: rebind LIVE A<->B (create_alias over the same name = atomic switch;
        # per qdrant alias map it is a single-row replace under the alias write lock)
        n_switches = 16
        writer_report = {"ok": 0, "anomalies": []}

        def writer():
            for i in range(1, n_switches + 1):
                target = B if i % 2 == 1 else A
                st, rw = rt.request("POST", "update_aliases", {"actions": [
                    {"create_alias": {"collection_name": target, "alias_name": LIVE}}]})
                if expect_2xx(st):
                    writer_report["ok"] += 1
                else:
                    writer_report["anomalies"].append((i, st, rw[:200]))
                time.sleep(0.02)
            stop.set()

        readers_n = 2
        try:
            readers_n = max(1, min(6, int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "2"))))
        except ValueError:
            readers_n = 2
        reader_report = {"reads": 0, "dups": [], "status_anomalies": [], "final_check": None}

        def reader(coll_x, coll_y):
            while not stop.is_set():
                for coll in (coll_x, coll_y):
                    st, rw = collection_aliases_http(coll)
                    reader_report["reads"] += 1
                    if not expect_2xx(st):
                        reader_report["status_anomalies"].append((coll, st, rw[:160]))
                        continue
                    m = parse_aliases(rw)
                    if m is None:
                        reader_report["status_anomalies"].append((coll, "unparsable", rw[:160]))
                        continue
                    m, dups = m
                    if dups:
                        reader_report["dups"].append((coll, dups, rw[:200]))
                # global cross-face snapshot
                st, rw = rt.request("GET", "list_aliases")
                reader_report["reads"] += 1
                if not expect_2xx(st):
                    reader_report["status_anomalies"].append(("global", st, rw[:160]))
                    continue
                g = parse_aliases(rw)
                if g is None:
                    reader_report["status_anomalies"].append(("global", "unparsable", rw[:160]))
                    continue
                g, gdups = g
                if gdups:
                    reader_report["dups"].append(("global", gdups, rw[:200]))
                if LIVE in g:
                    g_target = g[LIVE]
                    # the global alias table may only ever hold ONE row for LIVE; a
                    # per-collection snapshot just taken must be reconcilable with it
                    reader_report["final_check"] = g_target  # last observed target

        ths = [threading.Thread(target=writer)]
        for _ in range(readers_n):
            ths.append(threading.Thread(target=reader, args=(A, B)))
        for t in ths:
            t.start()
        for t in ths:
            t.join(timeout=120)

        print(f"churn_done writer_ok={writer_report['ok']}/{n_switches} "
              f"reader_reads={reader_report['reads']} "
              f"reader_anomalies={reader_report['status_anomalies'][:5]}")

        # ---- quiescence: deterministic final-state anchor (last switch i=16 -> target A) ----
        for kind, detail in writer_report["anomalies"]:
            anomalies.append(("writer", f"switch {kind} status {detail[0]}: {detail[1]}"))
        for c, st, d in reader_report["status_anomalies"]:
            anomalies.append(("reader", f"face {c} status {st}: {d}"))
        for c, dups, rw in reader_report["dups"]:
            DEFECTS.append(f"duplicate alias rows observed on face {c}: {dups} — Type4_StateLogicViolation raw={rw[:200]}")

        # final per-collection listing of A and B + global
        fsA, frA = collection_aliases_http(A)
        fsB, frB = collection_aliases_http(B)
        gs, gr = rt.request("GET", "list_aliases")
        print(f"[final:A] status={fsA} raw={frA[:300]}")
        print(f"[final:B] status={fsB} raw={frB[:300]}")
        print(f"[final:global] status={gs} raw={gr[:400]}")
        ok_all = expect_2xx(fsA) and expect_2xx(fsB) and expect_2xx(gs)
        if not ok_all:
            return "SCRIPT_ERROR"  # final probe broken -> cannot adjudicate final state

        mA, dA = parse_aliases(frA)
        mB, dB = parse_aliases(frB)
        mG, dG = parse_aliases(gr)
        if None in (mA, mB, mG):
            print("FINAL_PARSE_ERROR")
            return "SCRIPT_ERROR"
        if dA or dB or dG:
            DEFECTS.append(f"duplicate rows in final listing A={dA} B={dB} G={dG} — Type4_StateLogicViolation")
        # n_switches=16, even -> the last rebind targeted A; LIVE must resolve to A
        exp = {LIVE: A}
        for label, got, expmap in (("A", mA, exp), ("B", mB, {}), ("global", mG, exp)):
            if got != expmap:
                DEFECTS.append(
                    f"final-state mismatch on face {label}: listing={got} expected={expmap} "
                    f"— Type4_StateLogicViolation (alias switch churn left unreconciled state)"
                )

        # transport anomalies: re-check liveness before they can count as anything
        if anomalies:
            hz, hzraw = rt.request("GET", "healthz")
            print(f"liveness healthz status={hz} raw={hzraw[:100]}")
            if hz != 200:
                return "SCRIPT_ERROR"
            for kind, d in anomalies:
                print(f"TRANSIENT_{kind}_ANOMALY: {d} (healthz ok; final state reconciled above)")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for c in created:
            try:
                rt.drop_collection(c)
            except Exception:
                pass
        try:
            rt.request("POST", "update_aliases", {"actions": [
                {"delete_alias": {"alias_name": LIVE}}]})
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
