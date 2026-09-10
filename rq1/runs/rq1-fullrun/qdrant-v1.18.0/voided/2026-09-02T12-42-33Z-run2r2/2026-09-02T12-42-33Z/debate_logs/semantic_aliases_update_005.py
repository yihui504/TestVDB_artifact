#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_aliases_update_005
# strategy: illegal_rejection
# endpoint: aliases+update
# constraint_ids: qdrant_behavioral_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - request_required_paths vs actually accepted minimal bodies)
"""
Attack: illegal_rejection x qdrant_behavioral_aliases_update_001 (chunk_aliases+update; strategy 3, legal-batch positive matrix incl. request_required_paths minimal forms)
Oracle: all 6 legal batches return HTTP 200 with result=true (aliases+update response_shape result:boolean): (1) single create_alias; (2) rename_alias body carrying ONLY old_alias_name+new_alias_name (request_required_paths for rename_alias lists no collection_name); (3) delete_alias body carrying ONLY alias_name (request_required_paths for delete_alias lists alias_name alone); (4) create->rename->delete chain of one alias inside ONE atomic batch (end state: both chain names absent from the scoped map); (5) unicode alias name; (6) 128-char alias name; any non-200 => Type1_IllegalRejection (legal-per-contract input refused); 5xx while /healthz alive => Type3_RuntimeFailure

Assertion qdrant_behavioral_aliases_update_001 (evidence_tier=explicit):
  expected_behavior: "valid alias batch returns HTTP 200" (source:
  v-1-18-x api-reference aliases/update-aliases).

The contract's request_required_paths for aliases+update pins the minimal
legal bodies per action branch:
  actions[].create_alias  -> {alias_name, collection_name}
  actions[].delete_alias  -> {alias_name}                       (no collection_name)
  actions[].rename_alias  -> {old_alias_name, new_alias_name}   (no collection_name)
Cases (2) and (3) fire exactly those minimal bodies: a 4xx there is a
refusal of a request the contract declares complete (doc/impl drift on
the optional collection_name), which is the Type1_IllegalRejection class
this strategy hunts.

Case (4) additionally checks within-batch ordering semantics: the same
request creates, renames and deletes one alias; per the atomic-batch
model all actions apply in order against the batch's own effects, so the
request must succeed and leave neither chain name behind.

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


def update_result(raw):
    b = parse_json(raw)
    if b is None or not isinstance(b.get("result"), bool):
        return None
    return b["result"]


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
PREFIX = f"s2au5_{TS}_"
COL = PREFIX + "col"
A_SINGLE = PREFIX + "a_single"
A_REN0 = PREFIX + "a_ren0"
A_REN1 = PREFIX + "a_ren1"
CH0 = PREFIX + "ch0"
CH1 = PREFIX + "ch1"
A_UNI = PREFIX + "λ别名テスト"
A_LONG = PREFIX + "L" * 128
ALIASES = (A_SINGLE, A_REN0, A_REN1, CH0, CH1, A_UNI, A_LONG)
COLLECTIONS = (COL,)


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


def fire(label, actions):
    """A legal batch: oracle status==200 AND result==true."""
    st, raw = rt.request("POST", "update_aliases", {"actions": actions}, timeout=15)
    print(f"{label}: status={st} raw={raw[:300]}")
    if st == 0 or 500 <= st <= 599:
        alive = liveness_ok()
        if not alive:
            script_error(f"{label}: transport-level failure (status={st}) and /healthz dead; no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"{label}: legal alias batch returned status={st} while /healthz is alive - "
               f"crash-class failure on legal input; raw={raw[:200]}")
    if st != 200:
        defect("Type1_IllegalRejection",
               f"{label}: legal alias batch rejected with status={st}; assertion "
               f"qdrant_behavioral_aliases_update_001: 'valid alias batch returns HTTP 200'; "
               f"raw={raw[:300]}")
    if update_result(raw) is not True:
        defect("Type4_StateLogicViolation",
               f"{label}: 200 envelope must carry result=true per aliases+update "
               f"response_shape (result:boolean), got result={update_result(raw)!r}; raw={raw[:200]}")
    return st, raw


try:
    ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL}: {err}")
    SETUP_OK = True

    # (1) single create_alias
    fire("case1 single create_alias",
         [{"create_alias": {"collection_name": COL, "alias_name": A_SINGLE}}])
    m = scoped_map()
    if m != [(A_SINGLE, COL)]:
        defect("Type4_StateLogicViolation",
               f"case1: after a 200 create the scoped map must be [({A_SINGLE}, {COL})], got {m}")

    # (2) rename_alias minimal body (ONLY old+new - request_required_paths)
    fire("case2 setup create ren0",
         [{"create_alias": {"collection_name": COL, "alias_name": A_REN0}}])
    fire("case2 rename_alias minimal body {old_alias_name,new_alias_name}",
         [{"rename_alias": {"old_alias_name": A_REN0, "new_alias_name": A_REN1}}])
    m = scoped_map()
    if (A_REN1, COL) not in m or (A_REN0, COL) in m:
        defect("Type4_StateLogicViolation",
               f"case2: after the 200 minimal rename the scoped map must contain "
               f"({A_REN1}, {COL}) and not ({A_REN0}, {COL}), got {m}")

    # (3) delete_alias minimal body (ONLY alias_name - request_required_paths)
    fire("case3 delete_alias minimal body {alias_name}",
         [{"delete_alias": {"alias_name": A_REN1}}])
    m = scoped_map()
    if (A_REN1, COL) in m:
        defect("Type4_StateLogicViolation",
               f"case3: after the 200 minimal delete the scoped map must not contain "
               f"{A_REN1}, got {m}")

    # (4) create->rename->delete chain inside ONE atomic batch
    fire("case4 create->rename->delete chain in one batch",
         [{"create_alias": {"collection_name": COL, "alias_name": CH0}},
          {"rename_alias": {"old_alias_name": CH0, "new_alias_name": CH1}},
          {"delete_alias": {"alias_name": CH1}}])
    m = scoped_map()
    leftovers = [p for p in m if p[0] in (CH0, CH1)]
    if leftovers:
        defect("Type4_StateLogicViolation",
               f"case4: the chain batch reported 200 but left state behind: {leftovers} "
               f"(within-batch create->rename->delete must end with no chain alias)")

    # (5) unicode alias name
    fire("case5 create unicode alias",
         [{"create_alias": {"collection_name": COL, "alias_name": A_UNI}}])
    m = scoped_map()
    if (A_UNI, COL) not in m:
        defect("Type4_StateLogicViolation",
               f"case5: after the 200 unicode create the scoped map must contain "
               f"({A_UNI!r}, {COL}), got {m}")
    fire("case5 delete unicode alias",
         [{"delete_alias": {"alias_name": A_UNI}}])

    # (6) 128-char alias name
    fire("case6 create 128-char alias",
         [{"create_alias": {"collection_name": COL, "alias_name": A_LONG}}])
    m = scoped_map()
    if (A_LONG, COL) not in m:
        defect("Type4_StateLogicViolation",
               f"case6: after the 200 long-name create the scoped map must contain the "
               f"128-char alias, got {m}")
    fire("case6 delete 128-char alias",
         [{"delete_alias": {"alias_name": A_LONG}}])

    m = scoped_map()
    print(f"final scoped map: {m}")
    if m != [(A_SINGLE, COL)]:
        defect("Type4_StateLogicViolation",
               f"final scoped map must be exactly [({A_SINGLE}, {COL})] (the one alias this "
               f"script deliberately leaves in place), got {m}")

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
