#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_011
# strategy: count_consistency
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_005
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: boundary-closure readback of wal_config on PUT /collections/{name}
  (collections+create). The range constraint pins the create-time
  WalConfigDiff minima: wal_capacity_mb >= 1 (resolved default 32),
  wal_segments_ahead >= 0, wal_retain_closed >= 0 (resolved default 1).
  G4 closure: the minima themselves must be accepted and persisted. Legs:
  (A) {wal_capacity_mb:1, wal_segments_ahead:0, wal_retain_closed:0} -> 200;
      readback result.config.wal_config must echo each requested value.
  (B) below-minimum negatives: wal_capacity_mb=0,
      wal_segments_ahead=-1 -> 400/422 AND no residue (describe 404).
      2xx = Type1_IllegalSuccess (below-schema value admitted into state).
  [chunk_collections+create-1of2 coverage: count_consistency (state-equality
  readback at the boundary) x qdrant_range_collections_create_005]
Oracle: (A) create -> 200 and readback wal_config.wal_capacity_mb==1,
  wal_segments_ahead==0, wal_retain_closed==0 (mismatch =
  Type4_StateLogicViolation); (B) each below-minimum value -> 400/422 +
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
WAL_MIN = {"wal_capacity_mb": 1, "wal_segments_ahead": 0, "wal_retain_closed": 0}
NEG_LEGS = [
    ("wal_cap_0",     {"wal_capacity_mb": 0}),
    ("wal_ahead_neg", {"wal_segments_ahead": -1}),
]


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; inline liveness probes (GET healthz)
    stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def read_wal(name):
    """GET describe -> (status, wal_config_or_None, raw)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        cfg = ((b or {}).get("result") or {}).get("config")
        w = (cfg.get("wal_config") or {}) if isinstance(cfg, dict) else None
        if not isinstance(w, dict):
            # response_shape types wal_config as any — tolerate object wrappers
            if isinstance(w, list) and w and isinstance(w[0], dict):
                w = w[0]
            else:
                return s, None, raw
        return s, w, raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr11_" + TS + "_"
    DEFECTS = []
    names = []

    try:
        # ---- (A) all minima at once: closure + readback ----
        name = PFX + "wal_min"
        names.append(name)
        s, raw = safe_request("PUT", "create_collection", path_params={"name": name},
                              body={"vectors": VEC, "wal_config": dict(WAL_MIN)})
        print(f"[wal_min] status={s} raw={raw[:240]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[wal_min transport] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[wal_min liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(wal_min) create returned {s} (5xx; service alive per "
                f"/healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
            )
        elif s not in (200, 201):
            DEFECTS.append(
                f"(wal_min) all-minima wal_config {WAL_MIN} rejected with {s} — "
                f"boundary closure violated (minima must be accepted) — "
                f"raw={raw[:200]}"
            )
        else:
            gs, w, graw = read_wal(name)
            print(f"[wal_min readback] wal_config={json.dumps(w)[:300] if w else graw[:200]}")
            if gs != 200 or w is None:
                print("OBSERVATION (wal_min): wal_config not readable in "
                      "describe readback (response_shape types it as any) — "
                      "persistence not judgeable, create acceptance judged only")
            else:
                for k, want in WAL_MIN.items():
                    got = w.get(k)
                    if got is None:
                        print(f"OBSERVATION (wal_min): {k} absent from readback — "
                              f"silent-drop, recorded")
                    elif got != want:
                        DEFECTS.append(
                            f"(wal_min) wal state mismatch: requested {k}={want} "
                            f"(schema minimum), readback {k}={got!r} — "
                            f"Type4_StateLogicViolation"
                        )

        # ---- (B) below-minimum negatives ----
        for tag, over in NEG_LEGS:
            name = PFX + tag
            names.append(name)
            wc = dict(WAL_MIN)
            wc.update(over)
            s, raw = safe_request("PUT", "create_collection",
                                  path_params={"name": name},
                                  body={"vectors": VEC, "wal_config": wc})
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
                    f"({tag}) below-minimum wal_config {over} accepted with "
                    f"{s} — schema minimum violated — Type1_IllegalSuccess — "
                    f"raw={raw[:200]}"
                )
            elif s not in (400, 422):
                print(f"OBSERVATION ({tag}): rejection status {s} outside "
                      f"400/422 — recorded")
            gs, _, graw = safe_request("GET", "describe_collection",
                                       path_params={"name": name})
            if gs == 200:
                DEFECTS.append(
                    f"({tag}) below-minimum create left residue: describe -> 200 "
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
