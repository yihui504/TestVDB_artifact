#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_aliases_list_001
# strategy: behavioral_contract
# endpoint: aliases+list
# constraint_ids: qdrant_behavioral_aliases_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collections-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - API contract verification / behavioral consistency of the global listing)
"""
Attack: behavioral_contract x qdrant_behavioral_aliases_list_001 (chunk_aliases+list; strategy 1, positive-aggregation face)
Oracle: GET /aliases returns HTTP 200 and result.aliases is an array whose every entry is {alias_name: str, collection_name: str}; the 3 prefix-scoped aliases registered across 2 collections each appear exactly once with the correct owner collection, and before any registration the prefix scope is empty (sibling-tolerant global-face oracle, assertion qdrant_behavioral_aliases_list_001)

Contract assertion qdrant_behavioral_aliases_list_001 (evidence_tier=explicit):
  "returns 200 with a list of {alias, collection_name} across all collections"
  (endpoint_registry doc_quote; source_url v-1-18-x api-reference
  get-collections-aliases).

Positive-branch verification of the promise:
  (1) a legal GET is accepted with HTTP 200 (rt.judge_200 face);
  (2) the payload is an array at result.aliases (contract response_shape:
      result.aliases = array of objects) and EVERY entry is a well-formed
      {alias_name: string, collection_name: string} pair - an endpoint-level
      shape contract that applies to every entry in the global list;
  (3) "across all collections": aliases registered on two different
      collections all appear in the single global listing;
  (4) ownership correctness: each entry's collection_name equals the
      collection the alias was registered on;
  (5) no duplicate alias_name rows inside the prefix scope;
  (6) baseline closure: before any registration the prefix scope is empty
      (empty is the minimal legal instance of the promised list).

Global-face sibling tolerance (reflection R1): membership assertions are
scoped to this script's unique name prefix; concurrent sibling scripts may
legitimately contribute their own entries to the same global listing, so
exact-equality is only ever asserted inside the prefix scope.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (list_aliases / update_aliases / create_collection /
drop_collection / healthz); literal paths forbidden; 2-tuple (status, raw).
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

SETUP_OK = False  # flipped True once fixtures exist; judges receive it as setup_ok


# ---------------- helpers ----------------
def parse_alias_entries(raw):
    """Extract the alias list from a GET /aliases body.

    Contract response_shape for aliases+list: result.aliases = array of
    {alias_name, collection_name}. A bare result list (legacy envelope) is
    tolerated; anything else means the promised list is absent -> None.
    """
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
    """Lightweight health re-check (D3b/G8): only a healthz-class endpoint
    may decide whether a transport failure means 'server dying'."""
    try:
        st, _ = rt.request("GET", "healthz", timeout=5)
        return st == 200
    except Exception:
        return False


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


TS = str(int(time.time()))
PREFIX = f"s2al1_{TS}_"
C1 = PREFIX + "c1"
C2 = PREFIX + "c2"
A1 = PREFIX + "a1"
A2 = PREFIX + "a2"
A3 = PREFIX + "a3"
COLLECTIONS = (C1, C2)
ALIASES = (A1, A2, A3)


def scoped_pairs(entries):
    """(alias_name, collection_name) pairs inside this script's prefix scope."""
    out = []
    for it in entries:
        if isinstance(it, dict) and str(it.get("alias_name", "")).startswith(PREFIX):
            out.append((it.get("alias_name"), it.get("collection_name")))
    return out


def cleanup():
    """Teardown: aliases first, then collections. Failure is non-fatal."""
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
    # ---- baseline: prefix scope empty before any registration ----
    st, raw = rt.request("GET", "list_aliases")
    print(f"baseline GET /aliases: status={st} raw={raw[:300]}")
    if st == 0 or 500 <= st <= 599:
        alive = liveness_ok()
        script_error(f"listing unavailable at baseline (status={st}, server alive={alive}); no defect conclusion")
    entries = parse_alias_entries(raw)
    if entries is None:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"expected result.aliases array per contract response_shape, got: {raw[:300]}")
        sys.exit(1)
    base_pairs = scoped_pairs(entries)
    print(f"baseline prefix-scope entries: {base_pairs}")
    if base_pairs:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"fresh prefix scope must be empty before registration, found phantom entries: {base_pairs}")
        sys.exit(1)

    # ---- setup: two collections, three aliases across both ----
    for name in COLLECTIONS:
        ok, err = rt.setup_default(name, dim=4, metric="Cosine")
        if not ok:
            script_error(f"setup failed creating {name}: {err}")
    s, raw = rt.request("POST", "update_aliases", {"actions": [
        {"create_alias": {"collection_name": C1, "alias_name": A1}},
        {"create_alias": {"collection_name": C1, "alias_name": A2}},
        {"create_alias": {"collection_name": C2, "alias_name": A3}},
    ]})
    print(f"setup create_alias batch: status={s} raw={raw[:200]}")
    if s == 0 or 500 <= s <= 599:
        alive = liveness_ok()
        script_error(f"alias registration unavailable (status={s}, server alive={alive}); no defect conclusion")
    if s not in (200, 201):
        script_error(f"setup create_alias failed: {s} {raw[:300]}")
    SETUP_OK = True

    # ---- attack: the global listing must reflect the promise ----
    st, raw = rt.request("GET", "list_aliases")
    print(f"attack GET /aliases: status={st} raw={raw[:500]}")
    v = rt.judge_200(st, raw, setup_ok=SETUP_OK)
    if v == "SCRIPT_ERROR":
        alive = liveness_ok()
        script_error(f"listing unavailable (status={st}, server alive={alive}); no defect conclusion")
    if v == "DEFECT_FOUND":
        print("VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
        print(f"legal GET /aliases rejected: status={st} raw={raw[:300]} (assertion expects HTTP 200)")
        sys.exit(1)

    entries = parse_alias_entries(raw)
    if entries is None:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"expected result.aliases array per contract response_shape, got: {raw[:300]}")
        sys.exit(1)
    print(f"global list carries {len(entries)} entries (sibling-tolerated)")

    # (2) endpoint-level shape: every entry must be a str/str pair object
    for it in entries:
        if (not isinstance(it, dict)
                or not isinstance(it.get("alias_name"), str)
                or not isinstance(it.get("collection_name"), str)):
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"entry violates the promised {{alias, collection_name}} shape: {it!r}")
            sys.exit(1)

    # (3)+(4)+(5) prefix-scoped aggregation, ownership, duplicate-freedom
    got = scoped_pairs(entries)
    expected = {(A1, C1), (A2, C1), (A3, C2)}
    print(f"prefix-scope entries: {sorted(got)}")
    names = [a for a, _ in got]
    if len(names) != len(set(names)):
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"duplicate alias_name rows in the global listing: {got}")
        sys.exit(1)
    if set(got) != expected:
        missing = expected - set(got)
        foreign = set(got) - expected
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"expected exactly {sorted(expected)} across both collections; got {sorted(got)} "
              f"(missing={sorted(missing)}, wrong-owner/phantom={sorted(foreign)})")
        sys.exit(1)

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
