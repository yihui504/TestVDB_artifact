#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_002
# strategy: delete_consistency
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 2 variant (no-residue-after-rejected-create) on PUT
  /collections/{name} (collections+create). The type constraint promises
  vectors.distance IN {Cosine, Euclid, Dot, Manhattan} and
  VectorParams.required = [size, distance], size an unsigned integer. A create
  that violates the type contract must be rejected AND must leave zero
  persisted state. Legs, each followed by a full no-residue probe:
  (A) vectors={size:4, distance:"cosine"} — invalid enum (wrong case);
  (B) vectors={distance:"Cosine"} — required size missing;
  (C) vectors={size:"eight", distance:"Cosine"} — size not a uint.
  No-residue probe = GET describe -> exactly 404 AND name absent from the
  list_collections raw text (ghost state = Type4).
  [chunk_collections+create-1of2 coverage: delete_consistency x
   qdrant_type_collections_create_001 (negative enum/required/uint legs)]
Oracle: each invalid create -> 400/422 rejection (2xx = Type1_IllegalSuccess
  plus ghost-state check; 5xx = Type3 only after /healthz liveness); after
  every rejection describe -> 404 and name absent from list_collections
  (residue = Type4_StateLogicViolation)
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


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; inline liveness probes (GET healthz)
    stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def no_residue_probe(name, defects, tag):
    """After a rejected create: describe must 404 and the name must be
    absent from the list_collections raw text. Residue = Type4."""
    gs, graw = safe_request("GET", "describe_collection", path_params={"name": name})
    print(f"[{tag} residue-describe] status={gs} raw={graw[:160]}")
    if gs == 0 or 500 <= gs <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[{tag} liveness] healthz status={hs} raw={str(hraw)[:120]}")
        return "SCRIPT_ERROR" if hs != 200 else "SKIP"
    if gs == 200:
        defects.append(
            f"({tag}) rejected create left residue: describe({name}) -> 200 "
            f"(expected 404) — ghost collection state — "
            f"Type4_StateLogicViolation — raw={graw[:200]}"
        )
    ls, lraw = safe_request("GET", "list_collections")
    if ls == 200 and name in (lraw or ""):
        defects.append(
            f"({tag}) rejected create left residue: '{name}' present in "
            f"list_collections — stale list state — Type4_StateLogicViolation"
        )
    return "OK"


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr2_" + TS + "_"
    DEFECTS = []
    LEGS = [
        ("A-bad-enum", {"vectors": {"size": 4, "distance": "cosine"}}),
        ("B-missing-size", {"vectors": {"distance": "Cosine"}}),
        ("C-size-not-uint", {"vectors": {"size": "eight", "distance": "Cosine"}}),
    ]

    try:
        for tag, body in LEGS:
            name = PFX + tag.lower().replace("-", "_")
            s, raw = safe_request("PUT", "create_collection",
                                  path_params={"name": name}, body=body)
            print(f"[{tag} create] status={s} raw={raw[:300]}")
            if s == 0:
                hs, hraw = safe_request("GET", "healthz")
                print(f"[{tag} transport] healthz status={hs} raw={str(hraw)[:120]}")
                if hs != 200:
                    return "SCRIPT_ERROR"
                print(f"ENV_ISSUE: transport failure on {tag}; liveness ok — skipped")
                continue
            if 500 <= s <= 599:
                hs, hraw = safe_request("GET", "healthz")
                print(f"[{tag} liveness] healthz status={hs} raw={str(hraw)[:120]}")
                if hs != 200:
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"({tag}) invalid create returned {s} (5xx; 400/422 expected, "
                    f"service alive per /healthz) — Type3_RuntimeFailure — "
                    f"raw={raw[:200]}"
                )
                continue
            if 200 <= s < 300:
                DEFECTS.append(
                    f"({tag}) invalid vectors config accepted with {s} "
                    f"(2xx) — violates distance enum / VectorParams.required / "
                    f"uint size — Type1_IllegalSuccess — raw={raw[:200]}"
                )
            elif s not in (400, 422):
                print(f"OBSERVATION ({tag}): rejection status {s} outside the "
                      f"documented 400/422 set — recorded, residue still probed")
            # no-residue probe applies to every disposition (also 2xx ghosts)
            pr = no_residue_probe(name, DEFECTS, tag)
            if pr == "SCRIPT_ERROR":
                return "SCRIPT_ERROR"

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        # cleanup drops everything this script may have created, even ghosts
        for tag, _ in LEGS:
            try:
                rt.drop_collection(PFX + tag.lower().replace("-", "_"))
            except Exception:
                pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
