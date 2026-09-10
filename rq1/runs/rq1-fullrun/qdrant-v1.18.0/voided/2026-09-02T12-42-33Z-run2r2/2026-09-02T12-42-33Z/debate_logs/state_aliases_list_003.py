#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_aliases_list_003
# strategy: upsert_idempotence
# endpoint: aliases+list
# constraint_ids: qdrant_behavioral_aliases_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collections-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (alias map keyed by name — duplicate creates / rebinds vs the listing face)
"""
Attack: upsert_idempotence (Strategy 3 on the global alias listing: create x->A,
  duplicate create x->A again, then re-bind create x->B; after every step the
  listing must hold EXACTLY ONE entry for x — no duplicate rows, no lost entry,
  target reflects the latest successful create)
  x qdrant_behavioral_aliases_list_001 (endpoint aliases+list; GET /aliases returns
  200 with a list of {alias, collection_name} pairs — one mapping per alias name)
Rationale (G6 mutation choice): the alias map is keyed by alias_name, so duplicate
  creation is the mutation most likely to break the one-row-per-name invariant on
  the listing face (a create that appends instead of upserts surfaces as duplicate
  rows; a create that misses the key swap surfaces as a stale collection_name).
Oracle: after create1 x->A: GET /aliases prefix map = {x:A} (exactly 1 row); after
  duplicate create2 x->A: still {x:A} (still exactly 1 row; update-face status itself
  is out-of-chunk and not judged); after re-bind create3 x->B (if accepted): {x:B}
  (exactly 1 row, last write wins); if re-bind rejected 4xx: {x:A} stands.
  0 rows, >=2 rows, or a stale target = Type4_StateLogicViolation
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
    """result.aliases[] -> (mapping, anomalies). None mapping = wrong envelope shape.

    (response keys per contract api_endpoints[aliases+list].response_shape)
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
    """GET /aliases global face -> (mode, prefix-map or None, status, raw).

    Only prefix-filtered entries are asserted (concurrent sibling scripts share the
    global list). mode in {OK, FACE_DEFECT, ENV_DOWN}.
    """
    s, raw = rt.request("GET", "list_aliases")
    print(f"[list_aliases] status={s} raw={raw[:800]}")
    if s == 0 or 500 <= s <= 599 or s in (401, 403):
        hs, hraw = rt.request("GET", "healthz")
        print(f"[healthz re-check] status={hs} raw={str(hraw)[:120]}")
        return "ENV_DOWN", None, s, raw  # D3b: transport/5xx/auth = environment-class
    v = rt.judge_200(s, raw, setup_ok=True)
    if v != "NO_DEFECT":
        return "FACE_DEFECT", None, s, raw
    mapping, _ = parse_aliases(raw)
    if mapping is None:
        return "FACE_DEFECT", None, s, raw
    return "OK", {a: c for a, c in mapping.items() if str(a).startswith(pfx)}, s, raw


def alias_call(label, action):
    """One update_aliases mutation. Returns (applied: bool, judgable: bool).

    Update-face statuses are NOT judged here (chunk scope = aliases+list unit):
    2xx -> applied; 4xx -> rejected (legal to reject, not judged); 5xx/0 with a dead
    healthz -> environment down (script cannot continue reliably).
    """
    s, raw = rt.request("POST", "update_aliases", {"actions": [action]})
    print(f"[{label}] status={s} raw={str(raw)[:300]}")
    if s in (0,) or 500 <= s <= 599:
        hs, hraw = rt.request("GET", "healthz")
        print(f"[healthz re-check] status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            return False, False
        print(f"INFO_OUT_OF_CHUNK_FACE: {label} update-face returned {s} with healthz alive — recorded as evidence, list-face state still adjudicated")
        return False, True
    return s in (200, 201), True


def expect_one_row(label, mine, alias, target):
    """Expected-vs-actual: exactly one row {alias: target} in the prefix map."""
    got_t = mine.get(alias)
    if got_t != target:
        return [
            f"{label}: prefix map = {mine}, expected exactly {{{alias}: {target}}} "
            f"(one row per alias name) — got target={got_t!r} — Type4_StateLogicViolation"
        ]
    print(f"{label}: OK exactly one row {alias}->{target}")
    return []


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sal3u_" + TS + "_"          # unique per run; tolerates concurrent siblings
    A = PFX + "colA"
    B = PFX + "colB"
    X = PFX + "x"                      # the single alias name reused across creates
    DEFECTS = []
    created = []

    try:
        # ---- setup ----
        for c in (A, B):
            ok, err = rt.setup_default(c, 128, "Cosine")
            if not ok:
                print(f"SETUP_ERROR create {c}: {err}")
                return "SCRIPT_ERROR"
            created.append(c)

        # ---- step 1: create x->A (must apply; this is setup machinery) ----
        applied, judgable = alias_call("create1 x->A", {"create_alias": {"collection_name": A, "alias_name": X}})
        if not judgable:
            return "SCRIPT_ERROR"
        if not applied:
            print(f"SETUP_ERROR create1 did not apply (chunk sibling face)")
            return "SCRIPT_ERROR"
        mode, mine, s, raw = read_face(PFX)
        if mode == "ENV_DOWN":
            return "SCRIPT_ERROR"
        if mode == "FACE_DEFECT":
            DEFECTS.append(f"after-create1: GET /aliases face failed ({s}) raw={str(raw)[:200]}")
        else:
            DEFECTS += expect_one_row("after-create1", mine, X, A)

        # ---- step 2: duplicate create x->A (idempotence probe; update face not judged) ----
        applied2, judgable = alias_call("create2 x->A (duplicate)", {"create_alias": {"collection_name": A, "alias_name": X}})
        if not judgable:
            return "SCRIPT_ERROR"
        mode, mine, s, raw = read_face(PFX)
        if mode == "ENV_DOWN":
            return "SCRIPT_ERROR"
        if mode == "FACE_DEFECT":
            DEFECTS.append(f"after-create2: GET /aliases face failed ({s}) raw={str(raw)[:200]}")
        else:
            # whether the duplicate was accepted (idempotent) or rejected (conflict),
            # the listing must still hold exactly one row for x -> A
            DEFECTS += expect_one_row(f"after-create2 (duplicate applied={applied2})", mine, X, A)

        # ---- step 3: re-bind x->B (alias switch; last successful write must win) ----
        applied3, judgable = alias_call("create3 x->B (re-bind)", {"create_alias": {"collection_name": B, "alias_name": X}})
        if not judgable:
            return "SCRIPT_ERROR"
        mode, mine, s, raw = read_face(PFX)
        if mode == "ENV_DOWN":
            return "SCRIPT_ERROR"
        expected_target = B if applied3 else A
        if mode == "FACE_DEFECT":
            DEFECTS.append(f"after-create3: GET /aliases face failed ({s}) raw={str(raw)[:200]}")
        else:
            DEFECTS += expect_one_row(f"after-create3 (re-bind applied={applied3})", mine, X, expected_target)

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.request("POST", "update_aliases", {"actions": [
                {"delete_alias": {"alias_name": X}},
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
