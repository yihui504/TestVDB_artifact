#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_aliases_list_002
# strategy: metamorphic
# endpoint: aliases+list
# constraint_ids: qdrant_behavioral_aliases_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collections-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - behavioral-consistency detection between listing and routing faces)
"""
Attack: metamorphic x qdrant_behavioral_aliases_list_001 (chunk_aliases+list; strategy 6, listing-vs-resolution consistency face)
Oracle: for every prefix-scoped entry in GET /aliases, querying the collection endpoint BY the entry's alias_name returns HTTP 200 and the vector size of the collection it actually routes to equals the size of the collection named in the entry's collection_name (C1=4-dim, C2=8-dim); a listing entry whose alias resolves to 404, or routes to a collection whose dim contradicts the entry, is a violation

Metamorphic relation (follow-up relation, same input state read through two
faces of the same store):
  face A - GET /aliases advertises the alias map as
           {alias_name -> collection_name} pairs (assertion
           qdrant_behavioral_aliases_list_001: "returns 200 with a list of
           {alias, collection_name} across all collections");
  face B - the collection read path resolves any accepted collection name,
           including alias names, to the live collection.
  Invariant: for every advertised pair, resolving by alias_name must land on
  exactly the collection the listing names. The two collections carry
  different vector sizes (4 vs 8) so a wrong routing target is observable
  in the response itself, not just by name echo.

Why this mutation point (G6): the listing face is a pure map scan (R1 chain
evidence: alias_mapping.rs map read with no re-validation), while the
resolution face goes through collection lookup - a listing that advertises
a stale or dead mapping is invisible to face A alone and only the follow-up
read exposes the drift.

Global-face sibling tolerance (reflection R1): only prefix-scoped entries
are resolved and compared; sibling entries are ignored.

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


def vector_size_of(raw):
    """First vector size from a describe_collection body (unnamed {size,...}
    or named map {name: {size,...}}); None when not found."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    res = b.get("result") if isinstance(b, dict) else None
    vec = None
    if isinstance(res, dict):
        vec = ((res.get("config") or {}).get("params") or {}).get("vectors")
    if isinstance(vec, dict) and isinstance(vec.get("size"), int):
        return vec["size"]
    if isinstance(vec, dict):
        for v in vec.values():
            if isinstance(v, dict) and isinstance(v.get("size"), int):
                return v["size"]
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
PREFIX = f"s2al2_{TS}_"
C1 = PREFIX + "c1"   # 4-dim
C2 = PREFIX + "c2"   # 8-dim
A1 = PREFIX + "a1"   # -> C1
A3 = PREFIX + "a3"   # -> C2
COLLECTION_DIMS = {C1: 4, C2: 8}
ALIASES = (A1, A3)


def cleanup():
    for al in ALIASES:
        try:
            rt.request("POST", "update_aliases",
                       {"actions": [{"delete_alias": {"alias_name": al}}]}, timeout=15)
        except Exception:
            pass
    for name in COLLECTION_DIMS:
        try:
            rt.drop_collection(name)
        except Exception:
            pass


try:
    # ---- setup: two collections with distinct dims + one alias each ----
    for name, dim in COLLECTION_DIMS.items():
        ok, err = rt.setup_default(name, dim=dim, metric="Cosine")
        if not ok:
            script_error(f"setup failed creating {name} (dim={dim}): {err}")
    s, raw = rt.request("POST", "update_aliases", {"actions": [
        {"create_alias": {"collection_name": C1, "alias_name": A1}},
        {"create_alias": {"collection_name": C2, "alias_name": A3}},
    ]})
    print(f"setup create_alias batch: status={s} raw={raw[:200]}")
    if s == 0 or 500 <= s <= 599:
        alive = liveness_ok()
        script_error(f"alias registration unavailable (status={s}, server alive={alive}); no defect conclusion")
    if s not in (200, 201):
        script_error(f"setup create_alias failed: {s} {raw[:300]}")
    SETUP_OK = True

    # sanity baseline: each collection resolves by its own name to its dim
    for name, dim in COLLECTION_DIMS.items():
        ds, draw = rt.request("GET", "describe_collection", path_params={"name": name})
        print(f"baseline describe {name}: status={ds} size={vector_size_of(draw)}")
        if ds != 200 or vector_size_of(draw) != dim:
            script_error(f"baseline resolution of {name} disagrees with fixture (status={ds}, size={vector_size_of(draw)}, expected {dim})")

    # ---- attack face A: the advertised map ----
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

    scoped = [it for it in entries if isinstance(it, dict)
              and str(it.get("alias_name", "")).startswith(PREFIX)]
    got_pairs = sorted((it.get("alias_name"), it.get("collection_name")) for it in scoped)
    expected_pairs = sorted([(A1, C1), (A3, C2)])
    print(f"prefix-scope advertised map: {got_pairs}")
    if got_pairs != expected_pairs:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"face A advertised map is {got_pairs}, expected exactly {expected_pairs}")
        sys.exit(1)

    # ---- attack face B: live resolution of each advertised alias ----
    for it in scoped:
        alias = it.get("alias_name")
        advertised = it.get("collection_name")
        ds, draw = rt.request("GET", "describe_collection", path_params={"name": alias})
        size = vector_size_of(draw)
        print(f"resolve alias {alias} (advertised -> {advertised}): status={ds} size={size} raw={draw[:200]}")
        if ds == 0 or 500 <= ds <= 599:
            alive = liveness_ok()
            script_error(f"resolution of alias {alias} unavailable (status={ds}, server alive={alive}); no defect conclusion")
        if ds != 200:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"GET /aliases advertises {alias} -> {advertised} but resolving by that alias_name "
                  f"returns status={ds} raw={draw[:200]} (advertised-but-dead alias: listing/routing contradiction)")
            sys.exit(1)
        expected_dim = COLLECTION_DIMS.get(advertised)
        if expected_dim is None:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"entry {it!r} advertises collection {advertised!r} which is not one of this "
                  f"script's collections; phantom owner in prefix scope")
            sys.exit(1)
        if size != expected_dim:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"listing says {alias} -> {advertised} (dim {expected_dim}) but the alias actually "
                  f"routes to a {size}-dim collection (stale or wrong advertisement)")
            sys.exit(1)

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
