#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_012
# strategy: count_consistency
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_006
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: boundary-closure readback of strict_mode_config on PUT
  /collections/{name} (collections+create). The range constraint pins
  strict_mode_config.max_resident_memory_percent to the closed interval
  [1, 100] when set (field deprecated in 1.18, removal scheduled 1.21 —
  so it must still be settable and validated in 1.18). G4 closure: the
  endpoints 1 and 100 themselves must be accepted and persisted. Legs:
  (A) {enabled:true, max_resident_memory_percent:1} -> 200; readback
      result.config.strict_mode_config.max_resident_memory_percent == 1.
  (B) max_resident_memory_percent:100 -> 200; readback 100.
  (C) out-of-interval negatives: 0 and 101 -> 400/422 AND no residue
      (describe 404). 2xx = Type1_IllegalSuccess.
  [chunk_collections+create-1of2 coverage: count_consistency (state-equality
  readback at the boundary) x qdrant_range_collections_create_006]
Oracle: (A)/(B) creates -> 200 and readback strict_mode_config.
  max_resident_memory_percent equals 1 / 100 (mismatch =
  Type4_StateLogicViolation); (C) 0 and 101 -> 400/422 + describe 404
  (2xx = Type1; residue = Type4; 5xx = Type3 only after /healthz liveness)
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
KEY = "max_resident_memory_percent"
ACCEPT_LEGS = [("sm_pct_1", 1), ("sm_pct_100", 100)]
NEG_LEGS = [("sm_pct_0", 0), ("sm_pct_101", 101)]


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; inline liveness probes (GET healthz)
    stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def read_strict(name):
    """GET describe -> (status, strict_mode_config_or_None, raw)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        cfg = ((b or {}).get("result") or {}).get("config")
        sm = (cfg.get("strict_mode_config") or {}) if isinstance(cfg, dict) else None
        return s, (sm if isinstance(sm, dict) else None), raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr12_" + TS + "_"
    DEFECTS = []
    names = []

    try:
        # ---- (A)/(B) closed-interval endpoints 1 and 100 ----
        for tag, pct in ACCEPT_LEGS:
            name = PFX + tag
            names.append(name)
            s, raw = safe_request("PUT", "create_collection",
                                  path_params={"name": name},
                                  body={"vectors": VEC,
                                        "strict_mode_config": {"enabled": True,
                                                               KEY: pct}})
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
                    f"({tag}) in-interval {KEY}={pct} rejected with {s} — "
                    f"boundary closure violated (deprecation is scheduled for "
                    f"1.21, not 1.18) — raw={raw[:200]}"
                )
                continue
            gs, sm, graw = read_strict(name)
            print(f"[{tag} readback] strict_mode_config={json.dumps(sm)[:300] if sm else graw[:200]}")
            if gs != 200 or sm is None:
                print(f"OBSERVATION ({tag}): strict_mode_config not present in "
                      f"readback — persistence not judgeable")
                continue
            got = sm.get(KEY)
            if got is None:
                print(f"OBSERVATION ({tag}): {KEY} absent from readback — "
                      f"silent-drop, recorded")
            elif got != pct:
                DEFECTS.append(
                    f"({tag}) strict-mode state mismatch: requested {KEY}={pct}, "
                    f"readback={got!r} — Type4_StateLogicViolation"
                )

        # ---- (C) out-of-interval 0 and 101 ----
        for tag, pct in NEG_LEGS:
            name = PFX + tag
            names.append(name)
            s, raw = safe_request("PUT", "create_collection",
                                  path_params={"name": name},
                                  body={"vectors": VEC,
                                        "strict_mode_config": {"enabled": True,
                                                               KEY: pct}})
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
                    f"({tag}) create returned {s} (5xx; 400/422 expected, "
                    f"service alive per /healthz) — Type3_RuntimeFailure — "
                    f"raw={raw[:200]}"
                )
                continue
            if 200 <= s < 300:
                DEFECTS.append(
                    f"({tag}) out-of-interval {KEY}={pct} accepted with {s} — "
                    f"bound [1,100] violated — Type1_IllegalSuccess — "
                    f"raw={raw[:200]}"
                )
            elif s not in (400, 422):
                print(f"OBSERVATION ({tag}): rejection status {s} outside "
                      f"400/422 — recorded")
            gs, _, graw = safe_request("GET", "describe_collection",
                                       path_params={"name": name})
            if gs == 200:
                DEFECTS.append(
                    f"({tag}) out-of-interval create left residue: describe -> "
                    f"200 — ghost state — Type4_StateLogicViolation — "
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
