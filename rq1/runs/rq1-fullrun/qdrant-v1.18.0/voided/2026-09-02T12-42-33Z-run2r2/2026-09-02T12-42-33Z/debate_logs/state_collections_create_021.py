#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_021
# strategy: create_visibility_contract
# endpoint: collections+create
# constraint_ids: qdrant_bc_create_visibility_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: unknown
"""
Attack: behavioral-contract visibility sweep for create on
  PUT /collections/{name} (collections+create; URL from raw_knowledge
  api_endpoints[].url). The contract promises: a successfully created
  collection is IMMEDIATELY (no sleep, create is synchronous) listable,
  gettable and reported as existing. Sequence: (pre) describe -> 404
  (absent before); (A) valid create -> 200; (B) immediately GET
  /collections -> the name must be present; (C) immediately GET
  /collections/{name} -> 200 with a result object carrying config and a
  string status (yellow/grey allowed while indexing per the contract —
  the color itself is not judged); the contract's exists leg
  (GET /collections/{c}/exists, result.exists=true) is PROXIED by the
  describe 200 of leg (C) because the runtime PATHS whitelist exposes no
  exists path_key (SKIPPED direct exists probe: path_key whitelist —
  inventing keys is forbidden; describe 200/404 is the equivalent
  existence signal); (D) inverse check after drop: name absent from list
  and describe 404 (same visibility surface, opposite state).
  [chunk_collections+create-2of2 coverage: create_visibility_contract x
   qdrant_bc_create_visibility_001 (immediate list+get visibility +
   post-drop invisibility)]
Oracle: after a 200 create with NO intervening sleep -> name present in
  GET /collections (200), describe 200 with result.config present and
  result.status a string; absence from list or describe 404 right after a
  200 create = Type4_StateLogicViolation; after drop -> describe 404 and
  name absent from list (residue = Type4). 5xx judged Type3 only after
  /healthz confirms liveness.
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

def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
        return b if isinstance(b, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scc2g_" + TS + "_"
    C = PFX + "vis"
    DEFECTS = []

    try:
        # ---- (pre) absent before create ----
        ps, praw = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[pre describe] status={ps} raw={praw[:160]}")
        if ps == 200:
            print("SETUP_ERROR: unique-prefixed name already exists — environment not clean")
            return "SCRIPT_ERROR"

        # ---- (A) create ----
        s, raw = safe_request("PUT", "create_collection", path_params={"name": C},
                              body={"vectors": {"size": 4, "distance": "Euclid"}})
        print(f"[A create] status={s} raw={raw[:200]}")
        if s == 0:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness A-transport] healthz status={_hs} raw={str(_hraw)[:120]}")
            return "SCRIPT_ERROR"
        if 500 <= s <= 599 or s not in (200, 201):
            print(f"SETUP_ERROR: create returned {s} — cannot judge visibility contract")
            return "SCRIPT_ERROR"

        # ---- (B) immediately listable (no sleep) ----
        ls, lraw = safe_request("GET", "list_collections")
        present = (ls == 200 and C in (lraw or ""))
        print(f"[B list] status={ls} present={present} raw={lraw[:200]}")
        if ls == 0 or 500 <= ls <= 599:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness B-list] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                return "SCRIPT_ERROR"
            print(f"DEFECT: (B) list_collections returned {ls} right after a 200 "
                  f"create with service alive — Type3_RuntimeFailure — "
                  f"raw={lraw[:200]}")
            return "DEFECT_FOUND"
        if ls != 200:
            print(f"SETUP_ERROR: list_collections returned {ls}")
            return "SCRIPT_ERROR"
        if not present:
            DEFECTS.append(f"(B) collection missing from list_collections "
                           f"immediately after a 200 create — contract promises "
                           f"immediate listability — Type4_StateLogicViolation "
                           f"(qdrant_bc_create_visibility_001)")

        # ---- (C) immediately gettable (+ exists proxied by describe) ----
        # SKIPPED: direct GET /collections/{c}/exists probe — path_key whitelist
        # (rt.PATHS has no exists key; describe 200/404 is the existence signal).
        gs, graw = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[C describe] status={gs} raw={graw[:300]}")
        if gs == 0 or 500 <= gs <= 599:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness C-describe] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                return "SCRIPT_ERROR"
            print(f"DEFECT: (C) describe returned {gs} right after a 200 create "
                  f"with service alive — Type3_RuntimeFailure — raw={graw[:200]}")
            return "DEFECT_FOUND"
        gbody = parse_json(graw)
        res = (gbody or {}).get("result") if gbody else None
        if gs != 200 or not isinstance(res, dict):
            DEFECTS.append(f"(C) describe returned {gs}/result={type(res).__name__} "
                           f"immediately after a 200 create — contract promises "
                           f"immediate gettability (and exists=true) — "
                           f"Type4_StateLogicViolation "
                           f"(qdrant_bc_create_visibility_001)")
        else:
            if not isinstance(res.get("config"), dict):
                DEFECTS.append(f"(C) describe result lacks config object immediately "
                               f"after 200 create — incomplete created state — "
                               f"Type4_StateLogicViolation")
            st = res.get("status")
            print(f"[C status-color] result.status={st!r} (yellow/grey allowed "
                  f"while indexing per contract; not judged)")
            if st is not None and not isinstance(st, str):
                DEFECTS.append(f"(C) describe result.status={st!r} is not a string "
                               f"(response_shape result.status:string) — "
                               f"Type4_StateLogicViolation")

        # ---- (D) inverse: after drop the name must vanish from the same faces ----
        dls, dlraw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[D drop] status={dls} raw={dlraw[:160]}")
        if dls not in (200, 201, 404):
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness D-drop] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                return "SCRIPT_ERROR"
            print(f"DEFECT: (D) drop returned {dls} with service alive — "
                  f"Type3_RuntimeFailure — raw={dlraw[:200]}")
            return "DEFECT_FOUND"
        ls2, lraw2 = safe_request("GET", "list_collections")
        present2 = (ls2 == 200 and C in (lraw2 or ""))
        print(f"[D list] status={ls2} present={present2}")
        if ls2 == 200 and present2:
            DEFECTS.append(f"(D) dropped collection still present in "
                           f"list_collections — stale visibility — "
                           f"Type4_StateLogicViolation")
        gs2, graw2 = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[D describe-after-drop] status={gs2} raw={graw2[:160]}")
        if gs2 != 404:
            DEFECTS.append(f"(D) describe after verified drop returned {gs2} "
                           f"(expected 404) — ghost collection state — "
                           f"Type4_StateLogicViolation")

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
