#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_aliases_list_004
# strategy: behavioral_contract
# endpoint: aliases+list
# constraint_ids: qdrant_behavioral_aliases_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collections-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - listing-state consistency when the aliased collection disappears)
"""
Attack: behavioral_contract x qdrant_behavioral_aliases_list_001 (chunk_aliases+list; strategy 1, stale-state face: dangling alias advertisement)
Oracle: after dropping the aliased collection, GET /aliases contains no prefix-scoped entry whose collection_name references the dropped collection - an entry still advertising the dead collection is a violation, and if the alias name itself is still advertised it must not resolve (resolving it must NOT return 200 with the dead collection's data)

The assertion qdrant_behavioral_aliases_list_001 (evidence_tier=explicit)
promises "returns 200 with a list of {alias, collection_name} across all
collections". The phrase "across all collections" makes the listing a map
over EXISTING collections: an entry whose collection_name no longer exists
advertises a dead route.

Sequence under test (positive branch first, then the mutation):
  (1) create C1 (+ alias A->C1); the listing advertises exactly (A, C1)
      - the promise's positive face, so the later absence is attributable
      to the collection drop alone (G4 pairing);
  (2) drop C1 (accepted DELETE);
  (3) re-read the global listing: no prefix-scoped entry may reference C1.
      Two defect shapes are distinguished:
        (3a) entry (A, C1) still advertised - dangling advertisement;
        (3b) alias A still advertised but pointing elsewhere it never had
             - phantom remap;
  (4) corroborating probe: if A is still advertised, resolving by A must
      not return the dead collection's data (200 + C1's vector config
      while C1 is dropped would prove the advertisement routes somewhere
      illegal). This probe only corroborates; the defect claim rests on (3).

Not by-design: the threat model's by-design list covers idempotent DELETE
200 for points and HNSW pagination duplication - neither addresses alias
map cleanup on collection drop; no carve-out exists for dangling aliases.

Global-face sibling tolerance (reflection R1): assertions are scoped to
this script's unique prefix; sibling entries are ignored.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (list_aliases / update_aliases / create_collection /
drop_collection / describe_collection / healthz); literal paths forbidden.
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
PREFIX = f"s2al4_{TS}_"
C1 = PREFIX + "c1"
C2 = PREFIX + "c2"   # control collection that stays alive
A1 = PREFIX + "a1"   # alias on the collection that will be dropped
A2 = PREFIX + "a2"   # control alias on the surviving collection
COLLECTIONS = (C1, C2)
ALIASES = (A1, A2)


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


def read_scope(label):
    """GET /aliases -> (entries, prefix-scoped pairs); adjudicates the
    accept face through rt.judge_200 and the shape face against the
    contract response_shape."""
    st, raw = rt.request("GET", "list_aliases")
    print(f"[{label}] GET /aliases status={st} raw={raw[:400]}")
    v = rt.judge_200(st, raw, setup_ok=SETUP_OK)
    if v == "SCRIPT_ERROR":
        alive = liveness_ok()
        script_error(f"listing unavailable at {label} (status={st}, server alive={alive}); no defect conclusion")
    if v == "DEFECT_FOUND":
        print("VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
        print(f"legal GET /aliases rejected at {label}: status={st} raw={raw[:300]} (assertion expects HTTP 200)")
        sys.exit(1)
    entries = parse_alias_entries(raw)
    if entries is None:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"expected result.aliases array per contract response_shape at {label}, got: {raw[:300]}")
        sys.exit(1)
    pairs = sorted(
        (it.get("alias_name"), it.get("collection_name"))
        for it in entries
        if isinstance(it, dict) and str(it.get("alias_name", "")).startswith(PREFIX)
    )
    print(f"[{label}] prefix-scope={pairs}")
    return pairs


try:
    # ---- setup: C1 (to be dropped) + C2 (control), aliases A1->C1, A2->C2 ----
    for name in COLLECTIONS:
        ok, err = rt.setup_default(name, dim=4, metric="Cosine")
        if not ok:
            script_error(f"setup failed creating {name}: {err}")
    s, raw = rt.request("POST", "update_aliases", {"actions": [
        {"create_alias": {"collection_name": C1, "alias_name": A1}},
        {"create_alias": {"collection_name": C2, "alias_name": A2}},
    ]})
    print(f"setup create_alias batch: status={s} raw={raw[:200]}")
    if s == 0 or 500 <= s <= 599:
        alive = liveness_ok()
        script_error(f"alias registration unavailable (status={s}, server alive={alive}); no defect conclusion")
    if s not in (200, 201):
        script_error(f"setup create_alias failed: {s} {raw[:300]}")
    SETUP_OK = True

    # ---- (1) positive branch: the promise holds before the mutation ----
    pairs = read_scope("before-drop")
    expected_before = sorted([(A1, C1), (A2, C2)])
    if pairs != expected_before:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"positive branch failed before any drop: prefix-scope {pairs}, expected {expected_before}")
        sys.exit(1)

    # ---- (2) mutation: drop the aliased collection ----
    s, raw = rt.request("DELETE", "drop_collection", path_params={"name": C1})
    print(f"drop {C1}: status={s} raw={raw[:200]}")
    if s == 0 or 500 <= s <= 599:
        alive = liveness_ok()
        script_error(f"drop of {C1} unavailable (status={s}, server alive={alive}); no defect conclusion")
    if s not in (200, 201):
        script_error(f"step failure dropping {C1}: {s} {raw[:300]}")
    time.sleep(0.3)  # scheduling grace only; the drop is committed at 200

    # ---- (3) oracle: no prefix-scoped entry may reference the dead C1 ----
    pairs = read_scope("after-drop")
    dangling = [p for p in pairs if p[1] == C1]
    if dangling:
        # (4) corroborating probe: does the advertised alias still route?
        probe_note = ""
        alias_names = [a for a, _ in dangling]
        for a in alias_names:
            ds, draw = rt.request("GET", "describe_collection", path_params={"name": a})
            print(f"corroboration resolve {a}: status={ds} raw={draw[:200]}")
            if ds == 200:
                probe_note += (f" [alias {a} still resolves with status=200 while its advertised "
                               f"collection {C1} is dropped]")
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"after dropping {C1}, GET /aliases still advertises {dangling} - the listing "
              f"maps aliases 'across all collections' and must not reference a dropped "
              f"collection (stale/dangling advertisement){probe_note}")
        sys.exit(1)
    remapped = [p for p in pairs if p[0] == A1 and p[1] != C1]
    if remapped:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"after dropping {C1}, alias {A1} is re-advertised as {remapped} without any "
              f"such registration (phantom remap)")
        sys.exit(1)

    # ---- control: the surviving collection's alias is unaffected ----
    if (A2, C2) not in pairs:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"control alias (A2 -> C2) disappeared from the listing after an unrelated "
              f"collection drop; prefix-scope={pairs}")
        sys.exit(1)

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
