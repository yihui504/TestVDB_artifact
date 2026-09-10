#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_007
# strategy: count_consistency
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_005
# source_url: https://qdrant.tech/documentation/manage-data/vectors/
# doc_version: current (site latest; no version archive)
"""
Attack: state readback of the Datatype enum on PUT /collections/{name}
  (collections+create). The type constraint pins datatype to
  [float32, uint8, float16, turbo4] and states turbo4 is dense-only. Legs:
  (A) dense vectors {size:8, distance:Dot, datatype:"float16"} -> 200;
      readback result.config.params.vectors.datatype == "float16".
  (B) dense uint8 -> 200; readback datatype == "uint8".
  (C) dense datatype "float64" (out of enum) -> 400/422 AND no residue.
  (D) turbo4 configured on a SPARSE vector (sparse_vectors
      {"text": {"datatype": "turbo4"}}): assertion says turbo4 is valid for
      dense only -> 400/422 AND no residue; if accepted, readback must NOT
      persist turbo4 on the sparse entry (persisted turbo4 = Type4).
  [chunk_collections+create-1of2 coverage: count_consistency (state-equality
  readback) x qdrant_type_collections_create_005]
Oracle: (A)/(B) creates -> 200 and readback vectors.datatype equals the
  requested float16/uint8 (mismatch = Type4_StateLogicViolation);
  (C) "float64" -> 400/422 + describe 404; (D) sparse turbo4 -> 400/422 +
  describe 404 (2xx = Type1_IllegalSuccess; accepted-and-persisted turbo4 =
  Type4; 5xx = Type3 only after /healthz liveness)
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


def read_cfg(name):
    """GET describe -> (status, config_or_None, raw)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        cfg = ((b or {}).get("result") or {}).get("config")
        return s, (cfg if isinstance(cfg, dict) else None), raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr7_" + TS + "_"
    DEFECTS = []
    names = []

    def residue_probe(name, tag):
        gs, _, graw = safe_request("GET", "describe_collection",
                                   path_params={"name": name})
        if gs == 200:
            DEFECTS.append(
                f"({tag}) invalid create left residue: describe -> 200 — "
                f"ghost state — Type4_StateLogicViolation — raw={graw[:200]}"
            )

    try:
        # ---- (A)/(B) dense datatype readback: float16, uint8 ----
        for tag, dt in (("dt_float16", "float16"), ("dt_uint8", "uint8")):
            name = PFX + tag
            names.append(name)
            s, raw = safe_request("PUT", "create_collection",
                                  path_params={"name": name},
                                  body={"vectors": {"size": 8, "distance": "Dot",
                                                    "datatype": dt}})
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
                    f"({tag}) datatype create returned {s} (5xx; service alive "
                    f"per /healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
                )
                continue
            if s not in (200, 201):
                DEFECTS.append(
                    f"({tag}) legal datatype '{dt}' rejected with {s} — "
                    f"raw={raw[:200]}"
                )
                continue
            gs, cfg, graw = read_cfg(name)
            if gs != 200 or cfg is None:
                print(f"SETUP_ERROR ({tag}): readback failed")
                return "SCRIPT_ERROR"
            vec = (cfg.get("params") or {}).get("vectors")
            got = vec.get("datatype") if isinstance(vec, dict) else None
            print(f"[{tag} readback] vectors={json.dumps(vec)[:240] if isinstance(vec, dict) else vec!r}")
            if got is None:
                print(f"OBSERVATION ({tag}): datatype absent from readback — "
                      f"silent-drop at create, recorded")
            elif got != dt:
                DEFECTS.append(
                    f"({tag}) datatype state mismatch: requested {dt!r}, "
                    f"readback={got!r} — Type4_StateLogicViolation"
                )

        # ---- (C) out-of-enum dense datatype float64 ----
        name = PFX + "dt_float64"
        names.append(name)
        s, raw = safe_request("PUT", "create_collection", path_params={"name": name},
                              body={"vectors": {"size": 8, "distance": "Dot",
                                                "datatype": "float64"}})
        print(f"[dt_float64] status={s} raw={raw[:240]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[dt_float64 transport] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
        elif 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[dt_float64 liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(dt_float64) create returned {s} (5xx; 400/422 expected, "
                f"service alive per /healthz) — Type3_RuntimeFailure — "
                f"raw={raw[:200]}"
            )
        elif 200 <= s < 300:
            DEFECTS.append(
                f"(dt_float64) out-of-enum datatype accepted with {s} — "
                f"Type1_IllegalSuccess — raw={raw[:200]}"
            )
        elif s not in (400, 422):
            print(f"OBSERVATION (dt_float64): rejection status {s} outside 400/422 — recorded")
        residue_probe(name, "dt_float64")

        # ---- (D) turbo4 on a sparse vector (dense-only assertion) ----
        name = PFX + "dt_turbo4_sparse"
        names.append(name)
        s, raw = safe_request("PUT", "create_collection", path_params={"name": name},
                              body={"vectors": {"size": 8, "distance": "Dot"},
                                    "sparse_vectors": {"text": {"datatype": "turbo4"}}})
        print(f"[dt_turbo4_sparse] status={s} raw={raw[:240]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[dt_turbo4_sparse transport] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
        elif 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[dt_turbo4_sparse liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(dt_turbo4_sparse) create returned {s} (5xx; service alive "
                f"per /healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
            )
        elif 200 <= s < 300:
            gs, cfg, graw = read_cfg(name)
            print(f"[dt_turbo4_sparse readback] cfg={json.dumps(cfg)[:400] if cfg else graw[:200]}")
            sp = ((cfg or {}).get("params") or {}).get("sparse_vectors") if cfg else None
            if isinstance(sp, dict) and isinstance(sp.get("text"), dict) \
                    and sp["text"].get("datatype") == "turbo4":
                DEFECTS.append(
                    f"(dt_turbo4_sparse) turbo4 persisted on a sparse vector — "
                    f"assertion 'turbo4 is valid for dense vectors only' "
                    f"violated in stored state — Type4_StateLogicViolation — "
                    f"raw={graw[:200]}"
                )
            else:
                print("OBSERVATION (dt_turbo4_sparse): sparse turbo4 accepted "
                      "but not persisted as turbo4 (coerced/dropped) — "
                      "recorded, state consistent with dense-only assertion")
        elif s in (400, 422):
            print("[dt_turbo4_sparse] clean rejection (turbo4 dense-only)")
        else:
            print(f"OBSERVATION (dt_turbo4_sparse): status {s} outside promise set — recorded")
        residue_probe(name, "dt_turbo4_sparse")

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
