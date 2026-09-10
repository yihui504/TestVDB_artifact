#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_015
# strategy: resource_bound_state_survival
# endpoint: collections+create
# constraint_ids: qdrant_resource_shard_number_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: G4 both-direction probe of the resource_bound constraint on
  PUT /collections/{name} (collections+create; URL from raw_knowledge
  api_endpoints[].url). Positive: shard_number=1 (documented minimum) must
  create 200 and persist (describe result.config.params.shard_number == 1)
  and leave the collection queryable (upsert+count==1). Negative: a
  spec-legal but resource-extreme shard_number (4294967295 = uint32 max;
  the v1.18.0 spec documents minimum 1 and no maximum) must end in one of
  the three graceful outcomes (completed / rejected 4xx / documented service
  error) with the service still alive afterwards: /healthz 200 and a fresh
  control create still succeeding; a rejected create must leave no ghost
  state (describe 404, name absent from list_collections).
  [chunk_collections+create-2of2 coverage: resource_bound_survival x
   qdrant_resource_shard_number_001 (min-face readback + extreme-face
   graceful-degradation + post-attack liveness)]
Oracle: shard_number=1 -> 200 and describe params.shard_number==1, count==1;
  shard_number=4294967295 -> any of 200 (readback must then equal 4294967295)
  / 4xx (describe must be 404, name absent from list) / documented 5xx with
  /healthz still 200; /healthz failing, or the control create failing after
  the extreme request, = Type3_RuntimeFailure; ghost state after a 4xx
  rejection or mismatched readback after a 200 = Type4_StateLogicViolation.
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


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)

def describe_params(name):
    """GET /collections/{name} -> (status, params_dict_or_None, raw)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        cfg = ((b or {}).get("result") or {}).get("config")
        prm = (cfg or {}).get("params") if isinstance(cfg, dict) else None
        return s, (prm if isinstance(prm, dict) else None), raw
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


def name_in_list(name):
    """GET /collections -> membership of a unique-prefixed name (substring
    on raw text; parse-tolerant because list envelope shapes vary)."""
    s, raw = safe_request("GET", "list_collections")
    return s, (s == 200 and name in (raw or "")), raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scc2a_" + TS + "_"
    C_MIN = PFX + "shmin"
    C_EXT = PFX + "shext"
    C_CTL = PFX + "shctl"
    CREATED = [C_MIN, C_EXT, C_CTL]
    DEFECTS = []

    try:
        # ---- (A) positive: documented minimum shard_number=1 ----
        body_min = {"vectors": {"size": 4, "distance": "Euclid"},
                    "shard_number": 1}
        s, raw = safe_request("PUT", "create_collection",
                              path_params={"name": C_MIN}, body=body_min)
        print(f"[A create shard=1] status={s} raw={raw[:300]}")
        if s == 0:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness A-transport] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                print("DEFECT: (A) create(shard=1) transport-failed and /healthz "
                      "is not 200 — service down on spec-legal minimum input — "
                      "Type3_RuntimeFailure (qdrant_resource_shard_number_001)")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness A-5xx] healthz status={_hs} raw={str(_hraw)[:120]}")
            hs = _hs
            if hs != 200:
                DEFECTS.append(f"(A) create(shard=1) returned {s} and /healthz={hs} "
                               f"— service down on spec-legal minimum input — "
                               f"Type3_RuntimeFailure")
                for d in DEFECTS:
                    print(f"DEFECT: {d}")
                return "DEFECT_FOUND"
            print(f"DEFECT: (A) create(shard=1) returned {s} with service alive — "
                  f"Type3_RuntimeFailure — raw={raw[:200]}")
            return "DEFECT_FOUND"
        if s not in (200, 201):
            print(f"SETUP_ERROR: legal create shard_number=1 rejected with {s} — "
                  f"cannot judge resource_bound face")
            return "SCRIPT_ERROR"

        ds, prm, draw = describe_params(C_MIN)
        print(f"[A readback] status={ds} params={json.dumps(prm)[:300] if prm else draw[:200]}")
        if ds != 200 or prm is None:
            print("SETUP_ERROR: describe after successful create failed — cannot read state")
            return "SCRIPT_ERROR"
        got = prm.get("shard_number")
        if got != 1:
            DEFECTS.append(f"(A) shard_number readback mismatch: requested 1, "
                           f"stored={got!r} — Type4_StateLogicViolation")
        us, uraw = safe_request("PUT", "upsert_points", path_params={"name": C_MIN},
                                body={"points": [{"id": 1, "vector": [0.5] * 4}]},
                                query_params={"wait": "true"})
        print(f"[A upsert] status={us} raw={uraw[:160]}")
        if us not in (200, 201):
            print(f"SETUP_ERROR: upsert on shard=1 collection returned {us}")
            return "SCRIPT_ERROR"
        cs, cnt, craw = count_exact(C_MIN)
        print(f"[A count] status={cs} count={cnt} raw={craw[:160]}")
        if cs == 200 and cnt != 1:
            DEFECTS.append(f"(A) count after 1 wait=true upsert = {cnt!r} (expected 1) — "
                           f"Type4_StateLogicViolation (qdrant_inv_create_queryable_001)")

        # ---- (B) negative: spec-legal resource-extreme shard_number ----
        body_ext = {"vectors": {"size": 4, "distance": "Euclid"},
                    "shard_number": 4294967295}
        s2, raw2 = safe_request("PUT", "create_collection",
                                path_params={"name": C_EXT}, body=body_ext,
                                query_params={"timeout": 20}, timeout=90)
        print(f"[B create shard=4294967295] status={s2} raw={raw2[:300]}")

        if s2 == 0:
            # transport failure: service death IS the defect for this constraint
            time.sleep(2)
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness B-transport] healthz status={_hs} raw={str(_hraw)[:120]}")
            hs = _hs
            if hs != 200:
                _hs, _hraw = safe_request("GET", "healthz", timeout=10)
                print(f"[liveness B-transport-retry] healthz status={_hs} raw={str(_hraw)[:120]}")
                hs2 = _hs
                if hs2 != 200:
                    print("DEFECT: (B) spec-legal shard_number=4294967295 killed the "
                          "service (transport failure + /healthz not 200) — "
                          "Type3_RuntimeFailure (qdrant_resource_shard_number_001)")
                    return "DEFECT_FOUND"
            # alive but no response: measured-only — did it complete or leave residue?
            gs, _, grow = safe_request("GET", "describe_collection",
                                       path_params={"name": C_EXT})
            print(f"[B post-transport describe] status={gs} raw={grow[:200]}")
            print("OBSERVATION (B): create transport-failed while service alive; "
                  f"describe status={gs} (no defect claim without service failure)")
        elif 500 <= s2 <= 599:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness B-5xx] healthz status={_hs} raw={str(_hraw)[:120]}")
            hs = _hs
            if hs != 200:
                print(f"DEFECT: (B) shard_number=4294967295 produced {s2} and /healthz="
                      f"{hs} — service died on spec-legal input — Type3_RuntimeFailure")
                return "DEFECT_FOUND"
            # documented service error is an allowed graceful outcome; still no ghost
            gs, _, grow = safe_request("GET", "describe_collection",
                                       path_params={"name": C_EXT})
            print(f"[B post-5xx describe] status={gs} raw={grow[:200]}")
            print(f"OBSERVATION (B): extreme shard create failed with {s2} "
                  "(allowed 'documented service error' branch) with service alive")
        elif s2 in (200, 201):
            gs, prm2, grow = describe_params(C_EXT)
            print(f"[B readback] status={gs} params={json.dumps(prm2)[:300] if prm2 else grow[:200]}")
            if gs != 200 or prm2 is None:
                DEFECTS.append(f"(B) extreme create returned 200 but describe={gs} — "
                               f"promised state absent — Type4_StateLogicViolation")
            elif prm2.get("shard_number") != 4294967295:
                DEFECTS.append(f"(B) shard_number readback mismatch: requested "
                               f"4294967295, stored={prm2.get('shard_number')!r} — "
                               f"Type4_StateLogicViolation")
        elif s2 == 408:
            # server-side operation timeout: creation may still be completing
            # in the background — measured-only, no ghost claim (G8 isolation)
            gs, _, grow = safe_request("GET", "describe_collection",
                                       path_params={"name": C_EXT})
            print(f"[B post-408 describe] status={gs} raw={grow[:200]}")
            print("OBSERVATION (B): extreme shard create returned 408 "
                  "(operation timeout) — not a definitive rejection; no ghost claim")
        else:
            # definitive 4xx rejection — the clean graceful outcome; no residue
            gs, _, grow = safe_request("GET", "describe_collection",
                                       path_params={"name": C_EXT})
            print(f"[B post-reject describe] status={gs} raw={grow[:200]}")
            if gs != 404:
                DEFECTS.append(f"(B) create rejected with {s2} but describe returned "
                               f"{gs} (expected 404) — ghost collection state — "
                               f"Type4_StateLogicViolation")
            ls, present, lraw = name_in_list(C_EXT)
            if ls == 200 and present:
                DEFECTS.append(f"(B) rejected collection '{C_EXT}' still present in "
                               f"list_collections — stale list state — "
                               f"Type4_StateLogicViolation")

        # ---- (C) post-attack liveness + usability control ----
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[liveness C-control] healthz status={_hs} raw={str(_hraw)[:120]}")
        hs = _hs
        if hs != 200:
            print(f"DEFECT: (C) /healthz={hs} after spec-legal shard_number request — "
                  f"service death — Type3_RuntimeFailure (qdrant_resource_shard_number_001)")
            return "DEFECT_FOUND"
        sc, craw = safe_request("PUT", "create_collection", path_params={"name": C_CTL},
                                body={"vectors": {"size": 4, "distance": "Euclid"}})
        print(f"[C control create] status={sc} raw={craw[:200]}")
        if sc not in (200, 201):
            print(f"DEFECT: (C) control create failed with {sc} while /healthz=200 — "
                  f"service unusable after spec-legal shard_number request — "
                  f"Type3_RuntimeFailure — raw={craw[:200]}")
            return "DEFECT_FOUND"

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for n in CREATED:
            try:
                rt.drop_collection(n)
            except Exception:
                pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
