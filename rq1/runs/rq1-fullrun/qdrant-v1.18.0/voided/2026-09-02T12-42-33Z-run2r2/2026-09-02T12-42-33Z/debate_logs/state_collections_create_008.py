#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_008
# strategy: count_consistency
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_006
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: state readback of the 1.18 memory-placement enum on PUT
  /collections/{name} (collections+create). The type constraint pins
  memory to [cold, cached, pinned] and states pinned is NOT supported for
  dense vector storage (memory replaces the deprecated on_disk/always_ram
  booleans). Legs:
  (A) vectors {size:4, Cosine, memory:"cached"} -> 200; readback
      result.config.params.vectors.memory == "cached".
  (B) memory:"cold" -> 200; readback "cold".
  (C) memory:"hot" (out of enum) -> 400/422 AND no residue (describe 404).
  (D) memory:"pinned" on a DENSE vector: the constraint's own assertion
      says pinned is unsupported there -> 400/422 AND no residue; if
      accepted, readback must NOT persist "pinned" on the dense config
      (persisted pinned = Type4 — unsupported placement admitted into state).
  [chunk_collections+create-1of2 coverage: count_consistency (state-equality
  readback) x qdrant_type_collections_create_006]
Oracle: (A)/(B) creates -> 200 and readback vectors.memory equals the
  requested cached/cold (mismatch = Type4_StateLogicViolation);
  (C) "hot" -> 400/422 + describe 404; (D) dense "pinned" -> 400/422 +
  describe 404 (2xx = Type1_IllegalSuccess; accepted-and-persisted pinned =
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


def read_vectors(name):
    """GET describe -> (status, vectors_dict_or_None, raw)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        cfg = ((b or {}).get("result") or {}).get("config")
        vec = ((cfg or {}).get("params") or {}).get("vectors") if isinstance(cfg, dict) else None
        return s, (vec if isinstance(vec, dict) else None), raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr8_" + TS + "_"
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
        # ---- (A)/(B) in-enum placements: cached, cold ----
        for tag, mem in (("mem_cached", "cached"), ("mem_cold", "cold")):
            name = PFX + tag
            names.append(name)
            s, raw = safe_request("PUT", "create_collection",
                                  path_params={"name": name},
                                  body={"vectors": {"size": 4, "distance": "Cosine",
                                                    "memory": mem}})
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
                    f"({tag}) memory create returned {s} (5xx; service alive "
                    f"per /healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
                )
                continue
            if s not in (200, 201):
                print(f"OBSERVATION ({tag}): in-enum memory '{mem}' rejected "
                      f"with {s} — legal input per constraint 006 — recorded — "
                      f"raw={raw[:200]}")
                continue
            gs, vec, graw = read_vectors(name)
            print(f"[{tag} readback] vectors={json.dumps(vec)[:240] if isinstance(vec, dict) else vec!r}")
            if gs != 200 or vec is None:
                print(f"SETUP_ERROR ({tag}): readback failed")
                return "SCRIPT_ERROR"
            got = vec.get("memory")
            if got is None:
                print(f"OBSERVATION ({tag}): memory absent from readback — "
                      f"silent-drop at create, recorded")
            elif got != mem:
                DEFECTS.append(
                    f"({tag}) memory state mismatch: requested {mem!r}, "
                    f"readback={got!r} — Type4_StateLogicViolation"
                )

        # ---- (C) out-of-enum "hot" ----
        name = PFX + "mem_hot"
        names.append(name)
        s, raw = safe_request("PUT", "create_collection", path_params={"name": name},
                              body={"vectors": {"size": 4, "distance": "Cosine",
                                                "memory": "hot"}})
        print(f"[mem_hot] status={s} raw={raw[:240]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[mem_hot transport] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
        elif 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[mem_hot liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(mem_hot) create returned {s} (5xx; 400/422 expected, service "
                f"alive per /healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
            )
        elif 200 <= s < 300:
            DEFECTS.append(
                f"(mem_hot) out-of-enum memory placement accepted with {s} — "
                f"Type1_IllegalSuccess — raw={raw[:200]}"
            )
        elif s not in (400, 422):
            print("OBSERVATION (mem_hot): rejection status outside 400/422 — recorded")
        residue_probe(name, "mem_hot")

        # ---- (D) pinned on dense (assertion: unsupported there) ----
        name = PFX + "mem_pinned_dense"
        names.append(name)
        s, raw = safe_request("PUT", "create_collection", path_params={"name": name},
                              body={"vectors": {"size": 4, "distance": "Cosine",
                                                "memory": "pinned"}})
        print(f"[mem_pinned_dense] status={s} raw={raw[:240]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[mem_pinned_dense transport] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
        elif 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[mem_pinned_dense liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(mem_pinned_dense) create returned {s} (5xx; service alive "
                f"per /healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
            )
        elif 200 <= s < 300:
            gs, vec, graw = read_vectors(name)
            print(f"[mem_pinned_dense readback] vectors={json.dumps(vec)[:240] if isinstance(vec, dict) else vec!r}")
            if gs == 200 and isinstance(vec, dict) and vec.get("memory") == "pinned":
                DEFECTS.append(
                    f"(mem_pinned_dense) pinned persisted on dense vector "
                    f"storage — assertion 'pinned is not supported for dense "
                    f"vector storage' violated in stored state — "
                    f"Type4_StateLogicViolation — raw={graw[:200]}"
                )
            else:
                print("OBSERVATION (mem_pinned_dense): pinned accepted but not "
                      "persisted as pinned (coerced/dropped) — recorded")
        elif s in (400, 422):
            print("[mem_pinned_dense] clean rejection (pinned unsupported for dense)")
        else:
            print("OBSERVATION (mem_pinned_dense): status outside promise set — recorded")
        residue_probe(name, "mem_pinned_dense")

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
