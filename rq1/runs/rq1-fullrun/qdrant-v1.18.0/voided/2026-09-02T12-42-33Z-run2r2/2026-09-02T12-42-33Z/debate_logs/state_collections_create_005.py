#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_005
# strategy: count_consistency
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: state readback of sharding_method on PUT /collections/{name}
  (collections+create). The type constraint pins the domain to the versioned
  OpenAPI ShardingMethod enum [auto, custom] (snake_case wire values) and
  notes the concept-doc prose variant 'hash_slot' is NOT part of the v1.18.0
  spec. Legs:
  (A) create sharding_method="custom" + shard_number=3 -> 200; readback
  result.config.params.sharding_method == "custom" AND
  result.config.params.shard_number == 3 (created state mirrors the request;
  spec wins over any doc paraphrase per D3b rule 2).
  (B) create sharding_method="hash_slot" (out-of-enum prose variant) ->
  4xx rejection AND no residue (describe 404, name absent from list).
  2xx acceptance = Type1_IllegalSuccess (value outside the versioned enum
  admitted into state).
  [chunk_collections+create-1of2 coverage: count_consistency (state-equality
  readback) x qdrant_type_collections_create_003 (+ enum negative no-residue)]
Oracle: (A) create -> 200 and readback params.sharding_method=="custom" and
  params.shard_number==3 (mismatch = Type4_StateLogicViolation);
  (B) "hash_slot" -> 400/422 and describe -> 404 (2xx = Type1; residue = Type4;
  5xx = Type3 only after /healthz liveness)
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


def read_params(name):
    """GET describe -> (status, params_dict_or_None, raw)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        cfg = ((b or {}).get("result") or {}).get("config")
        p = (cfg.get("params") or {}) if isinstance(cfg, dict) else None
        return s, (p if isinstance(p, dict) else None), raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def liveness_ok(tag):
    hs, hraw = safe_request("GET", "healthz")
    print(f"[{tag} liveness] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr5_" + TS + "_"
    CA = PFX + "custom"
    CB = PFX + "hashslot"
    DEFECTS = []

    try:
        # ---- (A) custom sharding: create + readback state ----
        sA, rA = safe_request("PUT", "create_collection", path_params={"name": CA},
                              body={"vectors": {"size": 4, "distance": "Cosine"},
                                    "sharding_method": "custom",
                                    "shard_number": 3})
        print(f"[A create custom] status={sA} raw={rA[:300]}")
        if sA == 0:
            if not liveness_ok("A"):
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on (A); liveness ok — skipped")
        elif 500 <= sA <= 599:
            if not liveness_ok("A"):
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(A) custom-sharding create returned {sA} (5xx; service alive "
                f"per /healthz) — Type3_RuntimeFailure — raw={rA[:200]}"
            )
        elif sA not in (200, 201):
            DEFECTS.append(
                f"(A) sharding_method='custom' (versioned enum value) rejected "
                f"with {sA} — legal input wrongly rejected — raw={rA[:200]}"
            )
        else:
            gs, p, graw = read_params(CA)
            print(f"[A readback] status={gs} params={json.dumps(p)[:400] if p else graw[:200]}")
            if gs != 200 or p is None:
                print("SETUP_ERROR: readback failed after successful create")
                return "SCRIPT_ERROR"
            sm = p.get("sharding_method")
            sn = p.get("shard_number")
            if sm is None:
                print("OBSERVATION (A): sharding_method absent from readback — "
                      "silent-drop at create, recorded")
            elif sm != "custom":
                DEFECTS.append(
                    f"(A) sharding state mismatch: requested 'custom', "
                    f"readback={sm!r} — Type4_StateLogicViolation"
                )
            if sn is not None and sn != 3:
                DEFECTS.append(
                    f"(A) shard_number state mismatch: requested 3, "
                    f"readback={sn!r} — Type4_StateLogicViolation"
                )

        # ---- (B) out-of-enum prose variant 'hash_slot' ----
        sB, rB = safe_request("PUT", "create_collection", path_params={"name": CB},
                              body={"vectors": {"size": 4, "distance": "Cosine"},
                                    "sharding_method": "hash_slot"})
        print(f"[B create hash_slot] status={sB} raw={rB[:300]}")
        if sB == 0:
            if not liveness_ok("B"):
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on (B); liveness ok — skipped")
        elif 500 <= sB <= 599:
            if not liveness_ok("B"):
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(B) hash_slot create returned {sB} (5xx; 400/422 expected, "
                f"service alive per /healthz) — Type3_RuntimeFailure — "
                f"raw={rB[:200]}"
            )
        elif 200 <= sB < 300:
            DEFECTS.append(
                f"(B) sharding_method='hash_slot' accepted with {sB} — value "
                f"outside the versioned ShardingMethod enum [auto, custom] "
                f"admitted — Type1_IllegalSuccess — raw={rB[:200]}"
            )
        elif sB not in (400, 422):
            print(f"OBSERVATION (B): rejection status {sB} outside 400/422 — recorded")
        # no-residue probe regardless of disposition
        gsB, pB, grawB = safe_request("GET", "describe_collection", path_params={"name": CB})
        if gsB == 200:
            DEFECTS.append(
                f"(B) invalid-sharding create left residue: describe -> 200 — "
                f"ghost state — Type4_StateLogicViolation — raw={grawB[:200]}"
            )
        ls, lraw = safe_request("GET", "list_collections")
        if ls == 200 and CB in (lraw or ""):
            DEFECTS.append(
                f"(B) '{CB}' present in list_collections after rejected create — "
                f"stale list state — Type4_StateLogicViolation"
            )

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for n in (CA, CB):
            try:
                rt.drop_collection(n)
            except Exception:
                pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
