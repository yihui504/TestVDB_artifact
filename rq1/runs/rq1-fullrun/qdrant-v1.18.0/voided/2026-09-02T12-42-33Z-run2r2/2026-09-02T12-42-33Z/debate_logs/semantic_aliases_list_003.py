#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_aliases_list_003
# strategy: metamorphic
# endpoint: aliases+list
# constraint_ids: qdrant_behavioral_aliases_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collections-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - behavioral consistency of the listing across the alias lifecycle)
"""
Attack: metamorphic x qdrant_behavioral_aliases_list_001 (chunk_aliases+list; strategy 6, lifecycle-evolution face create/rename/re-point/delete)
Oracle: after each accepted alias operation the prefix-scoped GET /aliases snapshot equals the expected map exactly - create L1->C1 shows {(L1,C1)}; rename L1->L2 leaves L1 absent and shows (L2,C1); re-point L2 to C2 (delete+recreate same name) shows (L2,C2) and not (L2,C1); deleting L2 empties the prefix scope

The assertion qdrant_behavioral_aliases_list_001 promises the global listing
"returns 200 with a list of {alias, collection_name} across all collections"
(evidence_tier=explicit). A listing is only a faithful list if it tracks the
alias map through its lifecycle; each mutation below rewrites exactly one
edge of the map, so the prefix-scoped snapshot after each accepted op is
fully determined:

  P1 create  L1 -> C1      expected scope {(L1, C1)}
  P2 rename  L1 => L2      expected scope {(L2, C1)}; L1 must be gone
  P3 re-point L2 -> C2     (delete_alias L2 + create_alias L2->C2 in one
                            atomic actions batch, per aliases+update
                            request_required_paths) expected scope
                            {(L2, C2)}; (L2, C1) would be a stale value
  P4 delete  L2            expected scope {} (empty closure)

Why these mutation points (G6): rename rewrites the map key in place - the
classic stale-listing break; re-point rewrites only the value, catching a
listing that caches the old owner; delete removes the edge, catching
lingering rows. Aliases are metadata ops committed before the 200 returns
(registry doc_quote: "Alias changes are ATOMIC"), so no eventual-consistency
carve-out applies; a 0.3s grace is given only against scheduling jitter.

Global-face sibling tolerance (reflection R1): every assertion is scoped to
this script's unique prefix; sibling entries in the same global list are
ignored.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (list_aliases / update_aliases / create_collection /
drop_collection / healthz); literal paths forbidden; 2-tuple return.
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
def parse_alias_entries(raw):
    """result.aliases array per contract response_shape (bare result list tolerated)."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    if not isinstance(b, dict):
        return None
    res = b.get("result")
    if isinstance(res, dict) and isinstance(res.get("aliases"), list):
        return res["aliases"]
    if isinstance(res, list):
        return res
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


TS = str(int(time.time()))
PREFIX = f"s2al3_{TS}_"
C1 = PREFIX + "c1"
C2 = PREFIX + "c2"
L1 = PREFIX + "l1"
L2 = PREFIX + "l2"
COLLECTIONS = (C1, C2)
ALIASES = (L1, L2)


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


def apply_actions(actions, label):
    """Run one atomic alias-op batch; a failed op is a step failure (G8),
    never a defect conclusion about the listing."""
    s, raw = rt.request("POST", "update_aliases", {"actions": actions})
    print(f"[op:{label}] status={s} raw={raw[:200]}")
    if s == 0 or 500 <= s <= 599:
        alive = liveness_ok()
        script_error(f"alias op {label} unavailable (status={s}, server alive={alive}); no defect conclusion")
    if s not in (200, 201):
        script_error(f"step failure at {label}: {s} {raw[:300]}")
    time.sleep(0.3)  # scheduling grace only; alias ops are committed at 200
    return s


def check_scope(phase, expected_pairs):
    """Read the global listing and compare the prefix-scoped snapshot against
    the declared expectation (expected vs actual, G7)."""
    st, raw = rt.request("GET", "list_aliases")
    print(f"[check:{phase}] GET /aliases status={st} raw={raw[:400]}")
    v = rt.judge_200(st, raw, setup_ok=SETUP_OK)
    if v == "SCRIPT_ERROR":
        alive = liveness_ok()
        script_error(f"listing unavailable at {phase} (status={st}, server alive={alive}); no defect conclusion")
    if v == "DEFECT_FOUND":
        print("VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
        print(f"legal GET /aliases rejected at {phase}: status={st} raw={raw[:300]} (assertion expects HTTP 200)")
        sys.exit(1)
    entries = parse_alias_entries(raw)
    if entries is None:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"expected result.aliases array per contract response_shape at {phase}, got: {raw[:300]}")
        sys.exit(1)
    got = sorted(
        (it.get("alias_name"), it.get("collection_name"))
        for it in entries
        if isinstance(it, dict) and str(it.get("alias_name", "")).startswith(PREFIX)
    )
    expected = sorted(expected_pairs)
    print(f"[check:{phase}] prefix-scope={got} expected={expected}")
    if got != expected:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        detail = []
        got_map = dict(got)
        for a, c in expected:
            if a not in got_map:
                detail.append(f"missing {a}->{c}")
            elif got_map[a] != c:
                detail.append(f"stale {a}->{got_map[a]} (expected {c})")
        for a, c in got:
            if (a, c) not in expected:
                detail.append(f"lingering/phantom {a}->{c}")
        print(f"listing snapshot at {phase} is {got}, expected {expected}: " + "; ".join(detail))
        sys.exit(1)


try:
    # ---- setup: two collections ----
    for name in COLLECTIONS:
        ok, err = rt.setup_default(name, dim=4, metric="Cosine")
        if not ok:
            script_error(f"setup failed creating {name}: {err}")
    SETUP_OK = True

    # ---- baseline: prefix scope empty ----
    check_scope("baseline", [])

    # ---- P1: create L1 -> C1 ----
    apply_actions([{"create_alias": {"collection_name": C1, "alias_name": L1}}], "P1 create L1->C1")
    check_scope("P1 after create", [(L1, C1)])

    # ---- P2: rename L1 => L2 (map key rewritten in place) ----
    apply_actions([{"rename_alias": {"old_alias_name": L1, "new_alias_name": L2}}], "P2 rename L1=>L2")
    check_scope("P2 after rename", [(L2, C1)])

    # ---- P3: re-point L2 -> C2 (atomic delete+create of the same alias name) ----
    apply_actions([
        {"delete_alias": {"alias_name": L2}},
        {"create_alias": {"collection_name": C2, "alias_name": L2}},
    ], "P3 re-point L2->C2")
    check_scope("P3 after re-point", [(L2, C2)])

    # ---- P4: delete L2 (empty closure of the prefix scope) ----
    apply_actions([{"delete_alias": {"alias_name": L2}}], "P4 delete L2")
    check_scope("P4 after delete", [])

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
