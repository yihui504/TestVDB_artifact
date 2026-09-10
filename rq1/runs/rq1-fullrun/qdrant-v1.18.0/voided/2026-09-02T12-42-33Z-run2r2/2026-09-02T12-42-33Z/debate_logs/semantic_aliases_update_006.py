#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_aliases_update_006
# strategy: type_coercion
# endpoint: aliases+update
# constraint_ids: qdrant_behavioral_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust - nested alias action structures accepted silently)
"""
Attack: type_coercion x qdrant_behavioral_aliases_update_001 (chunk_aliases+update; strategy 4, malformed actions matrix)
Oracle: all 12 malformed bodies are REJECTED with a 4xx (400/422 expected for serde/schema violations; any 4xx proves validation) - a 200/201 means the malformed structure was silently coerced/accepted => Type1_IllegalSuccess; 5xx while /healthz alive => Type3_RuntimeFailure; and after the whole matrix the scoped alias map still equals the control-only baseline (no phantom alias persisted by any malformed call => else Type4_StateLogicViolation)

Contract anchors (aliases+update, v-1-18-x api-reference):
  parameter actions: array[create_alias|delete_alias|rename_alias],
  required; request_required_paths pin the per-branch required fields:
    actions[].create_alias  -> {alias_name, collection_name}
    actions[].delete_alias  -> {alias_name}
    actions[].rename_alias  -> {old_alias_name, new_alias_name}
  response_shape: result = boolean.

Malformed matrix (each case violates the declared schema, not the
semantics - semantic 404s are covered by semantic_aliases_update_004):
  01 actions={}            - object where an array is declared
  02 actions="create_alias" - string where an array is declared
  03 actions=null          - explicit null for a required array
  04 body {}               - required 'actions' absent entirely
  05 create_alias missing alias_name (required path absent)
  06 create_alias missing collection_name (required path absent)
  07 alias_name=123        - number where a string is declared (BS-01)
  08 alias_name=true       - boolean where a string is declared (BS-01)
  09 alias_name=[...]      - array where a string is declared
  10 unknown action discriminator {"bogus_alias": {...}}
  11 two discriminators in one action (oneOf violation)
  12 collection_name=123   - number where a string is declared (BS-01)

Per G3 (shape generalization) cases 07/08/12 represent the whole
number/boolean-for-string family; per the threat model, 'filter=null is
treated as no-filter' style leniency applies to QUERY semantics - here
the declared type is a struct/array schema, where silent coercion changes
which branch (create/delete/rename) executes.

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
PREFIX = f"s2au6_{TS}_"
COL = PREFIX + "col"
CTRL = PREFIX + "ctrl"
VICTIM = PREFIX + "victim"   # live alias targeted by the double-discriminator case
ALIASES = (CTRL, VICTIM)
COLLECTIONS = (COL,)

CASES = [
    ("01 actions={} (object not array)", {"actions": {}}),
    ("02 actions=string", {"actions": "create_alias"}),
    ("03 actions=null", {"actions": None}),
    ("04 actions absent (empty body)", {}),
    ("05 create_alias missing alias_name",
     {"actions": [{"create_alias": {"collection_name": COL}}]}),
    ("06 create_alias missing collection_name",
     {"actions": [{"create_alias": {"alias_name": PREFIX + "x5"}}]}),
    ("07 alias_name=123 (number as string)",
     {"actions": [{"create_alias": {"collection_name": COL, "alias_name": 123}}]}),
    ("08 alias_name=true (boolean as string)",
     {"actions": [{"create_alias": {"collection_name": COL, "alias_name": True}}]}),
    ("09 alias_name=list (array as string)",
     {"actions": [{"create_alias": {"collection_name": COL,
                                    "alias_name": [PREFIX + "x9"]}}]}),
    ("10 unknown discriminator bogus_alias",
     {"actions": [{"bogus_alias": {"alias_name": PREFIX + "x10",
                                   "collection_name": COL}}]}),
    ("11 double discriminator create_alias+delete_alias",
     {"actions": [{"create_alias": {"collection_name": COL, "alias_name": PREFIX + "x11"},
                   "delete_alias": {"alias_name": VICTIM}}]}),
    ("12 collection_name=123 (number as string)",
     {"actions": [{"create_alias": {"collection_name": 123,
                                    "alias_name": PREFIX + "x12"}}]}),
]


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
    # ---- setup: one real collection + control alias (proves the API path works) ----
    ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL}: {err}")
    s, raw = rt.request("POST", "update_aliases", {"actions": [
        {"create_alias": {"collection_name": COL, "alias_name": CTRL}},
        {"create_alias": {"collection_name": COL, "alias_name": VICTIM}},
    ]})
    print(f"setup control aliases: status={s} raw={raw[:200]}")
    if s == 0 or 500 <= s <= 599:
        alive = liveness_ok()
        script_error(f"alias API unavailable (status={s}, server alive={alive}); no defect conclusion")
    if s != 200:
        script_error(f"setup create_alias failed: {s} {raw[:300]}")
    SETUP_OK = True
    baseline = scoped_map()
    print(f"baseline scoped map: {baseline}")
    if baseline != [(CTRL, COL), (VICTIM, COL)]:
        script_error(f"baseline scoped map unexpected: {baseline}")

    # ---- attack: every malformed body must be rejected ----
    accepted = []
    for label, body in CASES:
        st, rraw = rt.request("POST", "update_aliases", body, timeout=15)
        print(f"{label}: status={st} raw={rraw[:240]}")
        if st in (200, 201):
            accepted.append((label, st, rraw[:200]))
            continue
        if st == 0 or 500 <= st <= 599:
            alive = liveness_ok()
            if not alive:
                script_error(f"{label}: transport-level failure (status={st}) and /healthz dead; no defect conclusion")
            defect("Type3_RuntimeFailure",
                   f"{label}: malformed body crashed the endpoint with status={st} while "
                   f"/healthz is alive; raw={rraw[:200]}")
        # 404 would be inconclusive for a malformed-body case (route-level), record it
        if st == 404:
            print(f"{label}: rejected with 404 at route level (recorded, still a rejection)")
    if accepted:
        label, st, snippet = accepted[0]
        defect("Type1_IllegalSuccess",
               f"{label}: schema-violating body was ACCEPTED with status={st} - silent type "
               f"coercion on the actions structure (BS-01); {len(accepted)} of {len(CASES)} "
               f"malformed cases accepted; first raw={snippet}")

    # ---- integrity: no malformed call may have left state behind ----
    after = scoped_map()
    print(f"scoped map after matrix: {after}")
    if after != baseline:
        defect("Type4_StateLogicViolation",
               f"rejected malformed batches changed the alias map: baseline={baseline} "
               f"after={after} (phantom/mutated state from schema-violating input)")

    print(f"all {len(CASES)} malformed bodies rejected; scoped map unchanged")
    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
