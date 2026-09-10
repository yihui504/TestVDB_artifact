#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_010
# strategy: count_consistency
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_004
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: boundary-closure readback of optimizers_config on PUT
  /collections/{name} (collections+create). The range constraint pins the
  create-time OptimizersConfigDiff bounds: deleted_threshold in [0, 1],
  vacuum_min_vector_number >= 100, max_segment_size >= 1 (KB),
  memmap_threshold >= 0, indexing_threshold >= 0 (KB). G4 closure: the bound
  values themselves must be accepted and persisted. Legs:
  (A) {deleted_threshold:0.0, vacuum_min_vector_number:100, max_segment_size:1,
      memmap_threshold:0, indexing_threshold:0} -> 200; readback
      result.config.optimizer_config (note: readback key is optimizer_config
      per the endpoint response_shape) must echo each value.
  (B) deleted_threshold:1.0 (closed upper endpoint) -> 200; readback 1.0.
  (C) below-bound negatives: vacuum_min_vector_number=99,
      deleted_threshold=1.01, deleted_threshold=-0.01 -> 400/422 AND no
      residue (describe 404). 2xx = Type1_IllegalSuccess.
  [chunk_collections+create-1of2 coverage: count_consistency (state-equality
  readback at the boundary) x qdrant_range_collections_create_004]
Oracle: (A)/(B) creates -> 200 and readback optimizer_config echoes the
  requested bound values (float compare tolerance 1e-9; mismatch =
  Type4_StateLogicViolation); (C) each out-of-bound value -> 400/422 +
  describe 404 (2xx = Type1; residue = Type4; 5xx = Type3 only after
  /healthz liveness)
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

VEC = {"size": 4, "distance": "Cosine"}
OPT_LO = {"deleted_threshold": 0.0, "vacuum_min_vector_number": 100,
          "max_segment_size": 1, "memmap_threshold": 0, "indexing_threshold": 0}
OPT_HI = {"deleted_threshold": 1.0}
NEG_LEGS = [
    ("opt_vacuum_99",   {"vacuum_min_vector_number": 99}),
    ("opt_dt_over",     {"deleted_threshold": 1.01}),
    ("opt_dt_under",    {"deleted_threshold": -0.01}),
]
FLOAT_KEYS = {"deleted_threshold"}


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; inline liveness probes (GET healthz)
    stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def read_opt(name):
    """GET describe -> (status, optimizer_config_or_None, raw)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        cfg = ((b or {}).get("result") or {}).get("config")
        o = (cfg.get("optimizer_config") or {}) if isinstance(cfg, dict) else None
        return s, (o if isinstance(o, dict) else None), raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw



def check_echo(tag, name, wanted):
    """Readback-equality check for an accepted optimizers leg."""
    gs, o, graw = read_opt(name)
    print(f"[{tag} readback] optimizer_config={json.dumps(o)[:300] if o else graw[:200]}")
    if gs != 200 or o is None:
        print(f"SETUP_ERROR ({tag}): readback failed")
        return "SCRIPT_ERROR"
    defects = []
    for k, want in wanted.items():
        got = o.get(k)
        if got is None:
            print(f"OBSERVATION ({tag}): {k} absent from readback — silent-drop, recorded")
            continue
        if k in FLOAT_KEYS:
            if abs(float(got) - float(want)) > 1e-9:
                defects.append(
                    f"({tag}) optimizer state mismatch: requested {k}={want}, "
                    f"readback {k}={got!r} — Type4_StateLogicViolation"
                )
        elif got != want:
            defects.append(
                f"({tag}) optimizer state mismatch: requested {k}={want}, "
                f"readback {k}={got!r} — Type4_StateLogicViolation"
            )
    return defects


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr10_" + TS + "_"
    DEFECTS = []
    names = []

    try:
        # ---- (A)/(B) accepted bound values + readback echo ----
        for tag, cfg_over in (("opt_bounds_lo", OPT_LO), ("opt_dt_hi", OPT_HI)):
            name = PFX + tag
            names.append(name)
            oc = dict(OPT_LO)
            oc.update(cfg_over)
            s, raw = safe_request("PUT", "create_collection",
                                  path_params={"name": name},
                                  body={"vectors": VEC, "optimizers_config": oc})
            print(f"[{tag}] status={s} raw={raw[:240]}")
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
                    f"({tag}) create returned {s} (5xx; service alive per "
                    f"/healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
                )
                continue
            if s not in (200, 201):
                DEFECTS.append(
                    f"({tag}) in-bound optimizers_config {cfg_over} rejected "
                    f"with {s} — boundary closure violated — raw={raw[:200]}"
                )
                continue
            res = check_echo(tag, name, cfg_over)
            if res == "SCRIPT_ERROR":
                return "SCRIPT_ERROR"
            DEFECTS.extend(res)

        # ---- (C) out-of-bound negatives ----
        for tag, over in NEG_LEGS:
            name = PFX + tag
            names.append(name)
            oc = dict(OPT_LO)
            oc.update(over)
            s, raw = safe_request("PUT", "create_collection",
                                  path_params={"name": name},
                                  body={"vectors": VEC, "optimizers_config": oc})
            print(f"[{tag}] override={over} status={s} raw={raw[:240]}")
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
                    f"({tag}) create returned {s} (5xx; 400/422 expected, "
                    f"service alive per /healthz) — Type3_RuntimeFailure — "
                    f"raw={raw[:200]}"
                )
                continue
            if 200 <= s < 300:
                DEFECTS.append(
                    f"({tag}) out-of-bound optimizers_config {over} accepted "
                    f"with {s} — Type1_IllegalSuccess — raw={raw[:200]}"
                )
            elif s not in (400, 422):
                print(f"OBSERVATION ({tag}): rejection status {s} outside "
                      f"400/422 — recorded")
            gs, _, graw = safe_request("GET", "describe_collection",
                                       path_params={"name": name})
            if gs == 200:
                DEFECTS.append(
                    f"({tag}) out-of-bound create left residue: describe -> 200 "
                    f"— ghost state — Type4_StateLogicViolation — "
                    f"raw={graw[:200]}"
                )

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for n in names:
            try:
                rt.drop_collection(n)
            except Exception:
                pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
