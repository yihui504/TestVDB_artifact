#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_aliases_update_001
# strategy: behavioral_contract
# endpoint: aliases+update
# constraint_ids: qdrant_bc_alias_switch_atomic_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - behavioral-contract verification of the atomic alias switch)
"""
Attack: behavioral_contract x qdrant_bc_alias_switch_atomic_001 (chunk_aliases+update; strategy 1, sequential atomic-switch face)
Oracle: the one-request switch [delete_alias live + create_alias live->CB] returns HTTP 200 with result=true (aliases+update response_shape declares result:boolean), and afterwards (a) count through 'live' = 5, (b) scroll through 'live' returns exactly ids {101..105} (CB's fixture), (c) direct scroll of CA still returns exactly {1..5} (the switch moves the alias, not the data), (d) the scoped alias map advertises exactly (live -> CB); a rejected legal switch is Type1_IllegalRejection, a wrong routing/readback is Type4_StateLogicViolation

Behavioral contract qdrant_bc_alias_switch_atomic_001 (evidence_tier=explicit):
  scenario: "create collections A and B with alias 'live' on A -> POST
  /collections/aliases with rename of 'live' from A to B -> reads through
  alias 'live'"
  expected_behavior: "after a 200 the alias resolves to the new target;
  during and after the atomic batch no collection modification can
  interleave between alias operations (alias changes are ATOMIC per the
  spec description)"
  (source: v-1-18-x api-reference aliases/update-aliases).

This script exercises the SEQUENTIAL face of the contract verbatim:
two collections with disjoint id fixtures (CA: 1-5, CB: 101-105), alias
'live' initially on CA, one atomic two-action batch that re-points 'live'
to CB (delete+create in one request is the switch encoding), then the
post-200 state is read through the alias itself (count + scroll), through
the old collection directly (data must be untouched), and through the
global alias listing. The concurrent no-intermediate-state face is
covered by semantic_aliases_update_003.

Global-face sibling tolerance (reflection R1): only entries under this
script's unique prefix are asserted; sibling scripts may legitimately add
their own entries to the same global listing.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP
via rt.request path_key (update_aliases / list_aliases / create points via
upsert_points path_key / scroll / count / create_collection via
setup_default / drop_collection / healthz); literal paths forbidden.
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


def scroll_ids(raw):
    """ids from a scroll body (result.points[].id); None when the shape is absent."""
    b = parse_json(raw)
    if b is None:
        return None
    res = b.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("points"), list):
        return None
    return [p.get("id") for p in res["points"] if isinstance(p, dict)]


def count_value(raw):
    """exact count from a count body (result.count int); None when absent."""
    b = parse_json(raw)
    if b is None:
        return None
    res = b.get("result")
    if isinstance(res, dict) and isinstance(res.get("count"), int):
        return res["count"]
    return None


def update_result(raw):
    """aliases+update success envelope: contract response_shape result=boolean."""
    b = parse_json(raw)
    if b is None or "result" not in b:
        return "missing"
    return b.get("result")


def alias_entries(raw):
    """result.aliases array per contract response_shape (bare result list tolerated)."""
    b = parse_json(raw)
    if b is None:
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


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


TS = str(int(time.time()))
PREFIX = f"s2au1_{TS}_"
CA = PREFIX + "ca"      # fixture A: ids 1..5
CB = PREFIX + "cb"      # fixture B: ids 101..105
LIVE = PREFIX + "live"  # the switched alias
IDS_A = list(range(1, 6))
IDS_B = list(range(101, 106))
COLLECTIONS = (CA, CB)
ALIASES = (LIVE,)


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
    # ---- setup: two collections with disjoint fixtures ----
    for name in COLLECTIONS:
        ok, err = rt.setup_default(name, dim=4, metric="Cosine")
        if not ok:
            script_error(f"setup failed creating {name}: {err}")
    for name, ids in ((CA, IDS_A), (CB, IDS_B)):
        pts = [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in ids]
        s, raw = rt.request("PUT", "upsert_points", {"points": pts},
                            path_params={"name": name})
        print(f"setup upsert {name}: status={s} raw={raw[:160]}")
        if s not in (200, 201):
            script_error(f"setup upsert into {name} failed: {s} {raw[:200]}")
    # wait until both fixtures are countable (avoid read-back race in setup)
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
    SETUP_OK = True

    # ---- arrange alias 'live' on CA (the contract's starting state) ----
    s, raw = rt.request("POST", "update_aliases", {"actions": [
        {"create_alias": {"collection_name": CA, "alias_name": LIVE}},
    ]})
    print(f"arrange live->CA: status={s} raw={raw[:200]}")
    if s == 0 or 500 <= s <= 599:
        alive = liveness_ok()
        script_error(f"alias registration unavailable (status={s}, server alive={alive}); no defect conclusion")
    if s != 200:
        defect("Type1_IllegalRejection",
               f"legal create_alias batch rejected: status={s} raw={raw[:300]} "
               f"(assertion qdrant_behavioral_aliases_update_001: valid alias batch returns HTTP 200)")
    if update_result(raw) is not True:
        defect("Type4_StateLogicViolation",
               f"200 switch envelope must carry result=true per aliases+update response_shape "
               f"(result:boolean), got result={update_result(raw)!r} raw={raw[:200]}")

    # baseline: reads through 'live' see CA's fixture
    bs, braw = rt.request("POST", "scroll",
                          {"limit": 10, "with_payload": False, "with_vector": False},
                          path_params={"name": LIVE}, timeout=10)
    base_ids = scroll_ids(braw)
    print(f"baseline scroll via {LIVE}: status={bs} ids={base_ids}")
    if bs != 200 or base_ids is None or set(base_ids) != set(IDS_A):
        script_error(f"baseline through live is not CA's fixture (status={bs}, ids={base_ids})")

    # ---- attack: the atomic switch batch (delete + create in ONE request) ----
    st, sraw = rt.request("POST", "update_aliases", {"actions": [
        {"delete_alias": {"alias_name": LIVE}},
        {"create_alias": {"collection_name": CB, "alias_name": LIVE}},
    ]}, timeout=15)
    print(f"attack switch batch [delete live + create live->CB]: status={st} raw={sraw[:300]}")
    v = rt.judge_200(st, sraw, setup_ok=SETUP_OK)
    if v == "SCRIPT_ERROR":
        alive = liveness_ok()
        script_error(f"switch request unavailable (status={st}, server alive={alive}); no defect conclusion")
    if v == "DEFECT_FOUND":
        defect("Type1_IllegalRejection",
               f"legal atomic switch batch rejected: status={st} raw={sraw[:300]} "
               f"(behavioral contract qdrant_bc_alias_switch_atomic_001 expects the batch to succeed)")
    if update_result(sraw) is not True:
        defect("Type4_StateLogicViolation",
               f"200 switch envelope must carry result=true per aliases+update response_shape "
               f"(result:boolean), got result={update_result(sraw)!r} raw={sraw[:200]}")

    # (a) count through the alias after the switch
    cs, craw = rt.request("POST", "count", {"exact": True},
                          path_params={"name": LIVE}, timeout=10)
    got_count = count_value(craw)
    print(f"count via {LIVE} after switch: status={cs} count={got_count} raw={craw[:160]}")
    if cs != 200 or got_count != 5:
        defect("Type4_StateLogicViolation",
               f"after the 200 switch, count through 'live' must be 5 (CB's fixture size); "
               f"got status={cs} count={got_count} raw={craw[:200]}")

    # (b) reads through the alias resolve to CB's fixture
    ss, sraw2 = rt.request("POST", "scroll",
                           {"limit": 10, "with_payload": False, "with_vector": False},
                           path_params={"name": LIVE}, timeout=10)
    got_ids = scroll_ids(sraw2)
    print(f"scroll via {LIVE} after switch: status={ss} ids={got_ids}")
    if ss != 200 or got_ids is None or set(got_ids) != set(IDS_B):
        defect("Type4_StateLogicViolation",
               f"after the 200 switch 'live' must resolve to CB's ids {IDS_B}; "
               f"got status={ss} ids={got_ids} (wrong routing target or unshaped body)")

    # (c) the switch must not move data: CA still returns its own fixture directly
    ds, draw = rt.request("POST", "scroll",
                          {"limit": 10, "with_payload": False, "with_vector": False},
                          path_params={"name": CA}, timeout=10)
    ca_ids = scroll_ids(draw)
    print(f"direct scroll of {CA} after switch: status={ds} ids={ca_ids}")
    if ds != 200 or ca_ids is None or set(ca_ids) != set(IDS_A):
        defect("Type4_StateLogicViolation",
               f"the alias switch must not modify collections; direct scroll of CA must still "
               f"return {IDS_A}, got status={ds} ids={ca_ids}")

    # (d) the global listing advertises the new mapping (prefix-scoped)
    ls, lraw = rt.request("GET", "list_aliases", timeout=10)
    entries = alias_entries(lraw)
    print(f"list_aliases after switch: status={ls} raw={lraw[:300]}")
    if ls != 200 or entries is None:
        defect("Type4_StateLogicViolation",
               f"GET /aliases must return 200 with result.aliases array, got status={ls} raw={lraw[:200]}")
    scoped = sorted((it.get("alias_name"), it.get("collection_name")) for it in entries
                    if isinstance(it, dict) and str(it.get("alias_name", "")).startswith(PREFIX))
    print(f"prefix-scope advertised map: {scoped}")
    if scoped != [(LIVE, CB)]:
        defect("Type4_StateLogicViolation",
               f"after the 200 switch the scoped alias map must advertise exactly "
               f"[({LIVE}, {CB})], got {scoped}")

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
