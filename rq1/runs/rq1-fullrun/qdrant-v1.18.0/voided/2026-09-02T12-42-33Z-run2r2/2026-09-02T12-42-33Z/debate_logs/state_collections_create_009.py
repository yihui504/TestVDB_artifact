#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_009
# strategy: count_consistency
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: boundary-closure readback of hnsw_config on PUT /collections/{name}
  (collections+create). The range constraint pins the create-time
  HnswConfigDiff minima: m >= 0, ef_construct >= 4, full_scan_threshold >= 10
  (KB), max_indexing_threads >= 0, payload_m >= 0. G4 boundary closure: the
  minimum values THEMSELVES must be accepted and persisted. Legs:
  (A) all minima at once: {m:0, ef_construct:4, full_scan_threshold:10,
      max_indexing_threads:0, payload_m:0} -> 200; readback
      result.config.hnsw_config must echo each requested value (created state
      mirrors the request — a resolved default instead of the requested
      minimum is a state mismatch).
  (B) below-minimum negatives (each own collection): ef_construct=3,
      full_scan_threshold=9, m=-1 -> 400/422 AND no residue (describe 404).
      2xx = Type1_IllegalSuccess (below-schema value admitted into state).
  [chunk_collections+create-1of2 coverage: count_consistency (state-equality
  readback at the boundary) x qdrant_range_collections_create_002]
Oracle: (A) create -> 200 and readback hnsw_config.m==0, ef_construct==4,
  full_scan_threshold==10, max_indexing_threads==0, payload_m==0
  (any mismatch = Type4_StateLogicViolation); (B) each below-minimum value
  -> 400/422 + describe 404 (2xx = Type1; residue = Type4; 5xx = Type3 only
  after /healthz liveness)
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
HNSW_MIN = {"m": 0, "ef_construct": 4, "full_scan_threshold": 10,
            "max_indexing_threads": 0, "payload_m": 0}
# (tag, hnsw_config field overrides, expect)
NEG_LEGS = [
    ("hnsw_efc_3",   {"ef_construct": 3}),
    ("hnsw_fst_9",   {"full_scan_threshold": 9}),
    ("hnsw_m_neg1",  {"m": -1}),
]


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; inline liveness probes (GET healthz)
    stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def read_hnsw(name):
    """GET describe -> (status, hnsw_config_or_None, raw)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        cfg = ((b or {}).get("result") or {}).get("config")
        h = (cfg.get("hnsw_config") or {}) if isinstance(cfg, dict) else None
        return s, (h if isinstance(h, dict) else None), raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr9_" + TS + "_"
    DEFECTS = []
    names = []

    try:
        # ---- (A) all minima at once: closure + readback ----
        name = PFX + "hnsw_min"
        names.append(name)
        s, raw = safe_request("PUT", "create_collection", path_params={"name": name},
                              body={"vectors": VEC, "hnsw_config": dict(HNSW_MIN)})
        print(f"[hnsw_min] status={s} raw={raw[:240]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[hnsw_min transport] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[hnsw_min liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(hnsw_min) create returned {s} (5xx; service alive per "
                f"/healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
            )
        elif s not in (200, 201):
            DEFECTS.append(
                f"(hnsw_min) all-minima hnsw_config {HNSW_MIN} rejected with "
                f"{s} — boundary closure violated (minima must be accepted) — "
                f"raw={raw[:200]}"
            )
        else:
            gs, h, graw = read_hnsw(name)
            print(f"[hnsw_min readback] hnsw_config={json.dumps(h)[:300] if h else graw[:200]}")
            if gs != 200 or h is None:
                print("SETUP_ERROR: readback failed after successful create")
                return "SCRIPT_ERROR"
            for k, want in HNSW_MIN.items():
                got = h.get(k)
                if got is None:
                    print(f"OBSERVATION (hnsw_min): {k} absent from readback — "
                          f"silent-drop, recorded")
                elif got != want:
                    DEFECTS.append(
                        f"(hnsw_min) hnsw state mismatch: requested {k}={want} "
                        f"(schema minimum), readback {k}={got!r} — "
                        f"Type4_StateLogicViolation"
                    )

        # ---- (B) below-minimum negatives ----
        for tag, over in NEG_LEGS:
            name = PFX + tag
            names.append(name)
            hc = dict(HNSW_MIN)
            hc.update(over)
            s, raw = safe_request("PUT", "create_collection",
                                  path_params={"name": name},
                                  body={"vectors": VEC, "hnsw_config": hc})
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
                    f"({tag}) below-minimum hnsw_config {over} accepted with "
                    f"{s} — schema minimum violated — Type1_IllegalSuccess — "
                    f"raw={raw[:200]}"
                )
            elif s not in (400, 422):
                print(f"OBSERVATION ({tag}): rejection status {s} outside "
                      f"400/422 — recorded")
            # no-residue probe regardless of disposition
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
