#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_006
# strategy: count_consistency
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_004, qdrant_range_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: state readback of quantization_config on PUT /collections/{name}
  (collections+create), covering the type domain (constraint 004) and the
  quantile range [0.5, 1.0] (constraint range_003) in one sweep.
  Legs (data-driven, each create gets its own collection, all dropped in
  finally):
  (A) scalar {type:"int8", quantile:0.99} -> 200; readback
      result.config.quantization_config.scalar.type=="int8" and quantile==0.99.
  (B) boundary closure (G4): quantile 0.5 and 1.0 (the closed endpoints
      themselves) -> 200 each.
  (C) range negatives: quantile 0.49 and 1.01 -> 400/422 AND no residue
      (describe 404). 2xx = Type1_IllegalSuccess.
  (D) enum negatives: product compression "x3", binary encoding "three_bits"
      -> 400/422 AND no residue.
  [chunk_collections+create-1of2 coverage: count_consistency (state-equality
  readback) x qdrant_type_collections_create_004 + qdrant_range_collections_create_003]
Oracle: (A) scalar create -> HTTP 200/201 and the describe readback shape
  result.config.quantization_config.scalar carries type=="int8" and
  quantile==0.99 (readback value != requested value =
  Type4_StateLogicViolation); (B) quantile=0.5 and quantile=1.0 creates ->
  HTTP 200/201 each; (C) quantile 0.49 / 1.01, product compression "x3",
  binary encoding "three_bits" -> HTTP 400 or 422 with describe -> 404;
  any 2xx on a (C)/(D) body = Type1_IllegalSuccess; residue (describe ->
  200 after rejection) = Type4_StateLogicViolation; 5xx = Type3 only after
  GET /healthz -> 200
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
# (tag, quantization_config, expect) — expect: "accept" or "reject"
LEGS = [
    ("scalar_ok",   {"scalar": {"type": "int8", "quantile": 0.99}}, "accept"),
    ("quant_lo",    {"scalar": {"type": "int8", "quantile": 0.5}},  "accept"),
    ("quant_hi",    {"scalar": {"type": "int8", "quantile": 1.0}},  "accept"),
    ("quant_under", {"scalar": {"type": "int8", "quantile": 0.49}}, "reject"),
    ("quant_over",  {"scalar": {"type": "int8", "quantile": 1.01}}, "reject"),
    ("prod_bad",    {"product": {"compression": "x3"}},             "reject"),
    ("bin_bad",     {"binary": {"encoding": "three_bits"}},         "reject"),
]


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; inline liveness probes (GET healthz)
    stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def read_quant(name):
    """GET describe -> (status, quantization_config_or_None, raw)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        cfg = ((b or {}).get("result") or {}).get("config")
        q = (cfg.get("quantization_config") or {}) if isinstance(cfg, dict) else None
        return s, (q if isinstance(q, dict) else None), raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr6_" + TS + "_"
    DEFECTS = []
    names = []

    try:
        for tag, qc, expect in LEGS:
            name = PFX + tag
            names.append(name)
            body = {"vectors": VEC, "quantization_config": qc}
            s, raw = safe_request("PUT", "create_collection",
                                  path_params={"name": name}, body=body)
            print(f"[{tag}] expect={expect} status={s} raw={raw[:240]}")
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
            accepted = 200 <= s < 300
            if expect == "accept":
                if not accepted:
                    DEFECTS.append(
                        f"({tag}) legal quantization config {qc} rejected with "
                        f"{s} — boundary/domain value wrongly refused — "
                        f"raw={raw[:200]}"
                    )
                else:
                    gs, q, graw = read_quant(name)
                    if gs != 200 or q is None:
                        print(f"SETUP_ERROR ({tag}): readback failed")
                        return "SCRIPT_ERROR"
                    sc = q.get("scalar") if isinstance(q.get("scalar"), dict) else None
                    print(f"[{tag} readback] quantization={json.dumps(q)[:300]}")
                    if sc is None:
                        DEFECTS.append(
                            f"({tag}) quantization state lost after successful "
                            f"create: readback={q!r} — Type4_StateLogicViolation"
                        )
                        continue
                    want_q = qc["scalar"].get("quantile")
                    if sc.get("type") != "int8":
                        DEFECTS.append(
                            f"({tag}) quantization state mismatch: requested "
                            f"scalar.type='int8', readback={sc.get('type')!r} — "
                            f"Type4_StateLogicViolation"
                        )
                    got_q = sc.get("quantile")
                    if want_q is not None and (
                            got_q is None or abs(float(got_q) - float(want_q)) > 1e-9):
                        DEFECTS.append(
                            f"({tag}) quantile state mismatch: requested "
                            f"{want_q}, readback={got_q!r} — "
                            f"Type4_StateLogicViolation (range_003)"
                        )
            else:  # expect reject
                if accepted:
                    DEFECTS.append(
                        f"({tag}) invalid quantization config {qc} accepted with "
                        f"{s} — quantile outside [0.5,1.0] or compression/encoding "
                        f"outside enum — Type1_IllegalSuccess — raw={raw[:200]}"
                    )
                elif s not in (400, 422):
                    print(f"OBSERVATION ({tag}): rejection status {s} outside "
                          f"400/422 — recorded")
                # no-residue probe regardless of disposition
                gs, _, graw = safe_request("GET", "describe_collection",
                                           path_params={"name": name})
                if gs == 200:
                    DEFECTS.append(
                        f"({tag}) invalid quantization create left residue: "
                        f"describe -> 200 — ghost state — "
                        f"Type4_StateLogicViolation — raw={graw[:200]}"
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
