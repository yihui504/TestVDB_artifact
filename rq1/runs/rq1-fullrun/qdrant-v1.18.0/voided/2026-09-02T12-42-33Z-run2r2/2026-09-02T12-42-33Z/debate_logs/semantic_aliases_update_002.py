#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_aliases_update_002
# strategy: behavioral_contract
# endpoint: aliases+update
# constraint_ids: qdrant_state_aliases_update_001, qdrant_behavioral_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - atomicity promise vs actually applied partial state)
"""
Attack: behavioral_contract x qdrant_state_aliases_update_001 (chunk_aliases+update; strategy 1, all-or-nothing atomicity face) | co-anchored: qdrant_behavioral_aliases_update_001 (rejection codes of the invalid action)
Oracle: every mixed batch that contains one invalid action (create_alias -> nonexistent collection, documented 404 by qdrant_behavioral_aliases_update_001) is rejected with status>=400 (a 200 => Type1_IllegalSuccess), and after each rejection the prefix-scoped alias map is exactly the pre-batch map: the valid co-actions (AY/AZ2/AY2) must NOT exist, and in the destructive case the delete of the live alias AX inside the failed batch must NOT be applied (AX -> C1 still present) => partial application is Type4_StateLogicViolation

State constraint qdrant_state_aliases_update_001 (evidence_tier=explicit):
  "alias changes are ATOMIC: no collection modifications can happen between
  the alias operations of one request [SPEC description]"
  assertion: "alias operations in one request are applied atomically - no
  intermediate state is observable and no collection modification can
  interleave" (source: v-1-18-x api-reference aliases/update-aliases).

Operationalization of "atomic": a request is the unit - if the batch is
rejected, NONE of its actions may be applied (all-or-nothing). A failed
batch that leaves a valid co-action behind, or that consumes a destructive
delete of a live alias, exposes an intermediate/partial state exactly as
forbidden by the constraint.

Why this mutation point (G6): case C places a DELETE of a live alias in
the same batch as a failing create - partial application here is maximally
observable and maximally harmful (a rejected request destroys a working
alias), which is the strongest falsifier of the atomicity promise.

Global-face sibling tolerance (reflection R1): map comparisons are scoped
to this script's unique prefix.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP
via rt.request path_key (update_aliases / list_aliases / create_collection
via setup_default / drop_collection / healthz); literal paths forbidden.
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
def parse_json(raw):
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def scoped_map():
    """sorted (alias, collection) pairs under this script's prefix; None on listing failure."""
    st, raw = rt.request("GET", "list_aliases", timeout=10)
    if st != 200:
        return None
    b = parse_json(raw)
    if b is None:
        return None
    res = b.get("result")
    entries = None
    if isinstance(res, dict) and isinstance(res.get("aliases"), list):
        entries = res["aliases"]
    elif isinstance(res, list):
        entries = res
    if entries is None:
        return None
    return sorted((it.get("alias_name"), it.get("collection_name")) for it in entries
                  if isinstance(it, dict) and str(it.get("alias_name", "")).startswith(PREFIX))


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
PREFIX = f"s2au2_{TS}_"
C1 = PREFIX + "c1"        # real collection
MISSING = PREFIX + "no_such_collection"  # definitely nonexistent target
AX = PREFIX + "ax"        # live alias on C1 (must survive failed batches)
COLLECTIONS = (C1,)
ALIASES = (AX, PREFIX + "ay", PREFIX + "az", PREFIX + "az2", PREFIX + "ay2",
           PREFIX + "aw")


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
    # ---- setup: one collection + one live alias ----
    ok, err = rt.setup_default(C1, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {C1}: {err}")
    s, raw = rt.request("POST", "update_aliases", {"actions": [
        {"create_alias": {"collection_name": C1, "alias_name": AX}},
    ]})
    print(f"setup create {AX}->{C1}: status={s} raw={raw[:200]}")
    if s == 0 or 500 <= s <= 599:
        alive = liveness_ok()
        script_error(f"alias registration unavailable (status={s}, server alive={alive}); no defect conclusion")
    if s != 200:
        script_error(f"setup create_alias failed: {s} {raw[:300]}")
    SETUP_OK = True
    baseline = scoped_map()
    print(f"baseline scoped map: {baseline}")
    if baseline != [(AX, C1)]:
        script_error(f"baseline scoped map unexpected: {baseline}")

    def run_case(label, actions, expect_map):
        """Fire a mixed batch; oracle: rejected (>=400) AND map unchanged."""
        before = scoped_map()
        if before is None:
            script_error(f"{label}: alias listing unavailable before batch")
        st, rraw = rt.request("POST", "update_aliases", {"actions": actions}, timeout=15)
        print(f"{label}: status={st} raw={rraw[:300]}")
        if st in (200, 201):
            defect("Type1_IllegalSuccess",
                   f"{label}: batch with create_alias -> nonexistent collection '{MISSING}' "
                   f"was ACCEPTED (status={st}); assertion qdrant_behavioral_aliases_update_001 "
                   f"documents 404 for create_alias of a missing collection. raw={rraw[:200]}")
        if st == 0 or 500 <= st <= 599:
            # rejection via 5xx is still a rejection for the atomicity oracle, but
            # a transport-level failure needs a liveness check before any conclusion
            alive = liveness_ok()
            if not alive:
                script_error(f"{label}: transport-level failure (status={st}) and /healthz dead; no defect conclusion")
            print(f"{label}: rejected with 5xx while server alive (status={st}) - treated as rejected, atomicity still checked")
        after = scoped_map()
        if after is None:
            defect("Type4_StateLogicViolation",
                   f"{label}: after the rejected batch the alias listing is unreadable/unshaped")
        print(f"{label}: scoped map before={before} after={after}")
        if after != before:
            defect("Type4_StateLogicViolation",
                   f"{label}: rejected batch left partial state - constraint "
                   f"qdrant_state_aliases_update_001 requires atomic (all-or-nothing) "
                   f"application; map changed from {before} to {after}")
        if after != expect_map:
            defect("Type4_StateLogicViolation",
                   f"{label}: scoped map {after} deviates from the expected untouched "
                   f"baseline {expect_map}")

    # case A: valid create AFTER the invalid create
    run_case("caseA [valid create, invalid create]",
             [{"create_alias": {"collection_name": C1, "alias_name": PREFIX + "ay"}},
              {"create_alias": {"collection_name": MISSING, "alias_name": PREFIX + "az"}}],
             [(AX, C1)])

    # case B: invalid create BEFORE the valid create (order flipped)
    run_case("caseB [invalid create, valid create]",
             [{"create_alias": {"collection_name": MISSING, "alias_name": PREFIX + "az2"}},
              {"create_alias": {"collection_name": C1, "alias_name": PREFIX + "ay2"}}],
             [(AX, C1)])

    # case C (G6 destructive mutation): delete of the LIVE alias + invalid create;
    # if the batch is partially applied the working alias AX is destroyed by a
    # request the server itself rejected - the strongest observable atomicity break
    run_case("caseC [delete live alias, invalid create]",
             [{"delete_alias": {"alias_name": AX}},
              {"create_alias": {"collection_name": MISSING, "alias_name": PREFIX + "aw"}}],
             [(AX, C1)])

    final = scoped_map()
    print(f"final scoped map: {final}")
    if final != [(AX, C1)]:
        defect("Type4_StateLogicViolation",
               f"final scoped map must still be [({AX}, {C1})] after three rejected "
               f"batches, got {final}")

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
