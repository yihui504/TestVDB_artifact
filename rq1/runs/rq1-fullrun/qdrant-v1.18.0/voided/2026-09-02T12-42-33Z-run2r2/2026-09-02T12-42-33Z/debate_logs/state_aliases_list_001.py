#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_aliases_list_001
# strategy: count_consistency
# endpoint: aliases+list
# constraint_ids: qdrant_behavioral_aliases_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collections-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (alias map state transitions vs the global listing face)
"""
Attack: count_consistency (Strategy 1 CRUD-then-COUNT on the global alias listing:
  baseline empty -> create {a1->A, a2->B} -> listed with exact mapping -> delete a1 ->
  a1 gone & a2 intact -> rename a2->a3 -> old name gone & new name present)
  x qdrant_behavioral_aliases_list_001 (endpoint aliases+list; GET /aliases returns
  200 with a list of {alias, collection_name} across all collections)
Oracle: each settled GET /aliases returns 200 and its prefix-filtered alias map equals
  the expected state: {} baseline, {a1:A, a2:B} after create, {a2:B} after delete,
  {a3:B} after rename; any missing entry, post-delete residue, non-atomic rename
  (old+new both present), duplicate rows, or wrong collection_name = Type4_StateLogicViolation
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


# ---------------- helpers ----------------
def parse_aliases(raw):
    """result.aliases[] -> (mapping alias_name->collection_name, anomalies list).

    None mapping = body not JSON or result.aliases not a list (wrong envelope shape).
    anomalies = duplicate alias_name rows and entries lacking alias_name.
    (response keys per contract api_endpoints[aliases+list].response_shape:
     result.aliases[].alias_name / result.aliases[].collection_name)
    """
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


def read_face(pfx):
    """GET /aliases (global face). Returns (mode, payload, status, raw).

    mode 'OK'         -> payload = (prefix-filtered map, prefix-filtered anomalies)
    mode 'FACE_DEFECT'-> legal read rejected with non-auth 4xx, or 200 without the
                         promised result.aliases list (unit promise: 200 WITH a list)
                         -> payload = defect description string
    mode 'ENV_DOWN'   -> transport failure / 5xx / 401 / 403 with healthz re-check
                         (D3b: liveness must be re-proven before any env conclusion)
    Global-face tolerance: sibling scripts run concurrently, so ONLY prefix-filtered
    entries are ever asserted; anomalies are filtered to the prefix as well.
    """
    s, raw = rt.request("GET", "list_aliases")
    print(f"[list_aliases] status={s} raw={raw[:800]}")
    if s == 0 or 500 <= s <= 599 or s in (401, 403):
        hs, hraw = rt.request("GET", "healthz")
        print(f"[healthz re-check] status={hs} raw={str(hraw)[:120]}")
        # D3b: transport / 5xx / auth branches are environment-class for this
        # sequential script (churn-time 5xx adjudication with reproduction
        # discipline lives in state_aliases_list_004 per strategy 7)
        return "ENV_DOWN", None, s, raw
    v = rt.judge_200(s, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        return "FACE_DEFECT", (
            f"GET /aliases returned {s} for a parameterless legal read "
            f"(unit promises HTTP 200) raw={str(raw)[:200]}"
        ), s, raw
    mapping, anoms = parse_aliases(raw)
    if mapping is None:
        return "FACE_DEFECT", (
            f"GET /aliases returned 200 but body lacks the promised result.aliases list "
            f"(unit: 200 WITH a list of {{alias, collection_name}}) raw={str(raw)[:200]}"
        ), s, raw
    mine = {a: c for a, c in mapping.items() if str(a).startswith(pfx)}
    my_anoms = [x for x in anoms if pfx in x]
    return "OK", (mine, my_anoms), s, raw


def expect_state(label, got, expected_map):
    """Explicit expected-vs-actual comparison for the prefix-filtered alias map."""
    if got is None:
        return [f"{label}: face unreadable — cannot compare to expected {expected_map}"]
    mine, anoms = got
    problems = []
    if anoms:
        problems.append(f"{label}: anomalies in listing rows {anoms} (expected none for this prefix)")
    if mine != expected_map:
        problems.append(
            f"{label}: prefix-filtered alias map = {mine}, expected exactly {expected_map}"
            f" — Type4_StateLogicViolation"
        )
    else:
        print(f"{label}: OK map={mine}")
    return problems


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sal1c_" + TS + "_"          # unique per run; tolerates concurrent siblings
    A = PFX + "colA"
    B = PFX + "colB"
    A1 = PFX + "a1"
    A2 = PFX + "a2"
    A3 = PFX + "a3"
    DEFECTS = []
    created = []

    def step_face(label, expected_map):
        """One settled read + reconciliation. Returns (defects, fatal)."""
        mode, payload, s, raw = read_face(PFX)
        if mode == "ENV_DOWN":
            print(f"{label}: ENV_DOWN status={s}")
            return [], True
        if mode == "FACE_DEFECT":
            return [f"{label}: {payload} — unit promise 'HTTP 200 with a list' violated "
                    f"on the global listing face"], False
        return expect_state(label, payload, expected_map), False

    try:
        # ---- setup: two live collections as alias targets ----
        for c in (A, B):
            ok, err = rt.setup_default(c, 128, "Cosine")
            if not ok:
                print(f"SETUP_ERROR create {c}: {err}")
                return "SCRIPT_ERROR"
            created.append(c)

        # ---- baseline: fresh prefix must be absent (Strategy 1 count_before) ----
        d, fatal = step_face("baseline", {})
        DEFECTS += d
        if fatal:
            return "SCRIPT_ERROR"

        # ---- create a1->A, a2->B -> both listed with exact targets ----
        cs, craw = rt.request("POST", "update_aliases", {"actions": [
            {"create_alias": {"collection_name": A, "alias_name": A1}},
            {"create_alias": {"collection_name": B, "alias_name": A2}},
        ]})
        print(f"create_alias_batch status={cs} raw={craw[:300]}")
        if cs not in (200, 201):
            print(f"SETUP_ERROR alias create batch: {cs} {craw[:200]}")
            return "SCRIPT_ERROR"
        d, fatal = step_face("after-create", {A1: A, A2: B})
        DEFECTS += d
        if fatal:
            return "SCRIPT_ERROR"

        # ---- delete a1 -> a1 gone, a2 untouched ----
        ds, draw = rt.request("POST", "update_aliases", {"actions": [
            {"delete_alias": {"alias_name": A1}},
        ]})
        print(f"delete_alias status={ds} raw={draw[:300]}")
        if ds not in (200, 201):
            print(f"SETUP_ERROR alias delete: {ds} {draw[:200]}")
            return "SCRIPT_ERROR"
        d, fatal = step_face("after-delete", {A2: B})
        DEFECTS += d
        if fatal:
            return "SCRIPT_ERROR"

        # ---- rename a2 -> a3: swap must be atomic on the listing face ----
        rs, rraw = rt.request("POST", "update_aliases", {"actions": [
            {"rename_alias": {"old_alias_name": A2, "new_alias_name": A3}},
        ]})
        print(f"rename_alias status={rs} raw={rraw[:300]}")
        if rs not in (200, 201):
            print(f"SETUP_ERROR alias rename: {rs} {rraw[:200]}")
            return "SCRIPT_ERROR"
        d, fatal = step_face("after-rename", {A3: B})
        DEFECTS += d
        if fatal:
            return "SCRIPT_ERROR"

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.request("POST", "update_aliases", {"actions": [
                {"delete_alias": {"alias_name": A1}},
                {"delete_alias": {"alias_name": A2}},
                {"delete_alias": {"alias_name": A3}},
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
