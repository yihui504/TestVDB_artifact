#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_001
# strategy: count_consistency
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 (CRUD-then-COUNT / state readback) on PUT /collections/{name}
  (collections+create; URL from raw_knowledge api_endpoints[].url). Sequence:
  (A) create dense vectors config {size:8, distance:"Euclid"} (Euclid is the
  official enum name per the threat model's by-design list) -> expect 200 and
  the persisted config at result.config.params.vectors to read back
  size=8, distance="Euclid" (created state must mirror the request);
  (B) upsert 3 points with wait=true (query param, never body), then
  POST points/count exact=true -> result.count == 3 (invariants
  qdrant_inv_create_queryable_001 + qdrant_inv_count_consistency_001);
  (C) drop -> describe must 404 and the name must be absent from
  list_collections (qdrant_inv_delete_gone_001).
  [chunk_collections+create-1of2 coverage: count_consistency x
   qdrant_type_collections_create_001 (positive config-identity leg)]
Oracle: create -> 200 and readback vectors.size==8 / vectors.distance=="Euclid";
  after wait=true upsert of 3 points -> count exact returns result.count==3;
  after verified drop -> describe 404 and name absent from list_collections
  (mismatched readback/count = Type4_StateLogicViolation; 5xx judged Type3
  only after /healthz confirms liveness)
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
    """All HTTP through the runtime; call form kept stable so inline
    liveness probes (GET healthz) stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def describe_config(name):
    """GET /collections/{name} -> (status, config_dict_or_None, raw)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        cfg = ((b or {}).get("result") or {}).get("config")
        return s, (cfg if isinstance(cfg, dict) else None), raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def count_exact(name):
    """POST points/count {exact:true} -> (status, count_or_None, raw)."""
    s, raw = safe_request("POST", "count", path_params={"name": name},
                          body={"exact": True})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        r = (b or {}).get("result")
        return s, (r.get("count") if isinstance(r, dict) else None), raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def server5xx(context, s, raw):
    """5xx branch: liveness re-check via /healthz before any Type3 claim."""
    hs, hraw = safe_request("GET", "healthz")
    print(f"[liveness {context}] healthz status={hs} raw={str(hraw)[:120]}")
    if hs != 200:
        return "SCRIPT_ERROR"
    print(f"DEFECT: {context} returned {s} (5xx; service alive per /healthz) — "
          f"Type3_RuntimeFailure — raw={raw[:200]}")
    return "DEFECT_FOUND"


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr1_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    try:
        # ---- (A) create with explicit VectorParams, then read back state ----
        body = {"vectors": {"size": 8, "distance": "Euclid"}}
        s, raw = safe_request("PUT", "create_collection",
                              path_params={"name": C}, body=body)
        print(f"[A create] status={s} raw={raw[:300]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[A transport] healthz status={hs} raw={str(hraw)[:120]}")
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            return server5xx("(A) create", s, raw)
        if s not in (200, 201):
            print(f"SETUP_ERROR: legal create rejected with {s} — cannot judge state")
            return "SCRIPT_ERROR"

        ds, cfg, draw = describe_config(C)
        print(f"[A readback] status={ds} config={json.dumps(cfg)[:400] if cfg else draw[:200]}")
        if ds != 200 or cfg is None:
            print("SETUP_ERROR: describe after successful create failed — cannot read state")
            return "SCRIPT_ERROR"
        vec = (cfg.get("params") or {}).get("vectors")
        if not isinstance(vec, dict):
            print(f"OBSERVATION (A): params.vectors readback is not a map: {vec!r}")
        else:
            if vec.get("size") != 8:
                DEFECTS.append(
                    f"(A) created state mismatch: requested vectors.size=8, "
                    f"readback={vec.get('size')!r} — Type4_StateLogicViolation"
                )
            if vec.get("distance") != "Euclid":
                DEFECTS.append(
                    f"(A) created state mismatch: requested vectors.distance="
                    f"'Euclid' (official enum), readback={vec.get('distance')!r} — "
                    f"Type4_StateLogicViolation"
                )

        # ---- (B) insert 3 points (wait=true query param) then count == 3 ----
        pts = [{"id": i, "vector": [0.1] * 8} for i in range(3)]
        us, uraw = safe_request("PUT", "upsert_points", path_params={"name": C},
                                body={"points": pts}, query_params={"wait": "true"})
        print(f"[B upsert] status={us} raw={uraw[:200]}")
        if us == 0 or 500 <= us <= 599:
            return server5xx("(B) upsert wait=true", us, uraw)
        if us not in (200, 201):
            print(f"SETUP_ERROR: upsert returned {us} — cannot judge count")
            return "SCRIPT_ERROR"

        cs, cnt, craw = count_exact(C)
        print(f"[B count] status={cs} count={cnt} raw={craw[:200]}")
        if cs == 0 or 500 <= cs <= 599:
            return server5xx("(B) count exact", cs, craw)
        if cs != 200 or cnt is None:
            print("SETUP_ERROR: count exact failed — cannot judge invariant")
            return "SCRIPT_ERROR"
        if cnt != 3:
            DEFECTS.append(
                f"(B) count inconsistency: inserted 3 points with wait=true, "
                f"count exact returned {cnt!r} (expected 3) — "
                f"Type4_StateLogicViolation (qdrant_inv_count_consistency_001)"
            )

        # ---- (C) drop -> describe 404 + name absent from list ----
        ds2, draw2 = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[C drop] status={ds2} raw={draw2[:200]}")
        if ds2 not in (200, 201, 404):
            return server5xx("(C) drop", ds2, draw2)
        gs, graw = describe_config(C)
        print(f"[C describe-after-drop] status={gs} raw={graw[:200]}")
        if gs != 404:
            DEFECTS.append(
                f"(C) describe after verified drop returned {gs} (expected 404) — "
                f"ghost collection state — Type4_StateLogicViolation "
                f"(qdrant_inv_delete_gone_001) — raw={graw[:200]}"
            )
        ls, lraw = safe_request("GET", "list_collections")
        if ls == 200 and C in (lraw or ""):
            DEFECTS.append(
                f"(C) dropped collection '{C}' still present in list_collections — "
                f"stale list state — Type4_StateLogicViolation"
            )

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
