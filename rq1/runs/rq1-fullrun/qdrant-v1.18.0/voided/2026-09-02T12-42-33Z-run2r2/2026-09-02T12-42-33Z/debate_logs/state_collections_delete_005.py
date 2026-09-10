#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_delete_005
# strategy: delete_consistency
# endpoint: collections+delete
# constraint_ids: qdrant_behavioral_collections_delete_001, qdrant_bc_delete_invisibility_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: unknown
"""
Attack: alias interplay with collection delete (collections+delete;
  URLs from raw_knowledge api_endpoints[].url). The chunk's assertion
  keys status to state ("DELETE existing -> 200; non-existent -> 404,
  NOT 200") and the behavioral contract keys deletion to invisibility
  ("disappears from listing and direct access returns 404"). Aliases
  add a second name that resolves to the same state, so both promises
  are attacked through them:
  LEG 1 (ghost via dangling alias after delete-by-name): create C1 +
  alias A1->C1 -> DELETE /collections/{C1} -> 200 -> then access via
  GET /collections/{A1} must NOT serve the deleted collection: a 200
  there means a confirmed-deleted collection is still directly
  reachable (ghost data through the alias) = Type4 under
  bc_delete_invisibility; also the name C1 must be absent from
  GET /collections.
  LEG 2 (delete-by-alias status/state reconciliation): create C2 +
  alias A2->C2 -> DELETE /collections/{A2} -> whatever status the
  server picks, it must RECONCILE with the resulting state: a 2xx
  "confirmed" delete requires C2 actually gone (describe 404 + absent
  from list); a 4xx rejection requires C2 still present (describe
  200). A 200-that-does-not-delete or a 4xx-that-deletes = the status
  lies about the state = Type4 (behavioral_collections_delete_001's
  200/404 semantics applied through the alias face).
  [chunk_collections+delete coverage: delete_consistency x
   qdrant_behavioral_collections_delete_001 +
   qdrant_bc_delete_invisibility_001 (delete-by-name with dangling
   alias; delete-by-alias reconciliation)]
Oracle: after 200 delete-by-name -> describe-by-alias NOT 200 (404
  expected; 200 = ghost = Type4) and C1 absent from list; for
  delete-by-alias -> 2xx implies describe(C2)=404 + absent from list,
  4xx implies describe(C2)=200 (violations = Type4; 5xx = Type3 only
  after /healthz confirms liveness).
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


def list_names(raw):
    """List items parse via the "name" key (R11 standing lesson)."""
    body = parse_json(raw)
    if body:
        res = body.get("result")
        if isinstance(res, dict):
            cols = res.get("collections")
            if isinstance(cols, list):
                return [c.get("name") for c in cols if isinstance(c, dict)]
    return None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scdl5_" + TS + "_"
    C1, A1 = PFX + "ali1", PFX + "ala1"
    C2, A2 = PFX + "ali2", PFX + "ala2"
    VEC_CFG = {"vectors": {"size": 4, "distance": "Cosine"}}
    DEFECTS = []

    def liveness(tag):
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    def create_with_alias(coll, alias, tag):
        cs, craw = safe_request("PUT", "create_collection",
                                path_params={"name": coll}, body=VEC_CFG)
        print(f"[{tag} create {coll}] status={cs} raw={craw[:160]}")
        if cs not in (200, 201):
            return False
        abody = {"actions": [{"create_alias": {"alias_name": alias,
                                               "collection_name": coll}}]}
        as_, araw = safe_request("POST", "update_aliases", body=abody)
        print(f"[{tag} alias {alias}->{coll}] status={as_} raw={araw[:160]}")
        return as_ in (200, 201)

    try:
        # ================= LEG 1: delete-by-name, alias must not resurrect ==
        if not create_with_alias(C1, A1, "L1"):
            print("SETUP_ERROR: leg-1 create/alias failed")
            return "SCRIPT_ERROR"
        pre_s, pre_raw = safe_request("GET", "describe_collection",
                                      path_params={"name": A1})
        print(f"[L1 describe-by-alias sanity] status={pre_s} raw={pre_raw[:160]}")
        if pre_s != 200:
            print(f"NOTE: alias resolution pre-delete returned {pre_s} "
                  f"(informational; post-delete oracle below is 200-equals-ghost "
                  f"either way)")
        d1_s, d1_raw = safe_request("DELETE", "drop_collection",
                                    path_params={"name": C1})
        print(f"[L1 delete-by-name {C1}] status={d1_s} raw={d1_raw[:160]}")
        if d1_s == 0:
            liveness("L1-delete")
            return "SCRIPT_ERROR"
        if 500 <= d1_s <= 599:
            if not liveness("L1-delete"):
                return "SCRIPT_ERROR"
            DEFECTS.append(f"(L1) DELETE returned {d1_s} with service alive — "
                           f"Type3_RuntimeFailure — raw={d1_raw[:200]}")
        elif d1_s != 200:
            DEFECTS.append(f"(L1) DELETE on existing (aliased) collection returned "
                           f"{d1_s} (assertion: confirmed with 200) — "
                           f"Type4_StateLogicViolation — raw={d1_raw[:200]}")
        # alias face must not serve the deleted collection
        pa_s, pa_raw = safe_request("GET", "describe_collection",
                                    path_params={"name": A1})
        print(f"[L1 describe-by-alias AFTER delete] status={pa_s} raw={pa_raw[:200]}")
        if pa_s == 0 or 500 <= pa_s <= 599:
            if not liveness("L1-alias-after"):
                return "SCRIPT_ERROR"
            DEFECTS.append(f"(L1) describe-by-alias after 200 delete returned "
                           f"{pa_s} with service alive — Type3_RuntimeFailure — "
                           f"raw={pa_raw[:200]}")
        elif pa_s == 200:
            DEFECTS.append(f"(L1) confirmed-deleted collection still directly "
                           f"reachable via alias {A1} (describe-by-alias 200) — "
                           f"ghost visibility through the alias face — "
                           f"Type4_StateLogicViolation "
                           f"(qdrant_bc_delete_invisibility_001) — raw={pa_raw[:200]}")
        # name face: absent from list
        l1_s, l1_raw = safe_request("GET", "list_collections")
        print(f"[L1 list] status={l1_s}")
        if l1_s == 200:
            names = list_names(l1_raw)
            present = (C1 in names) if names is not None else (C1 in (l1_raw or ""))
            print(f"[L1 list] mode={'structural' if names is not None else 'substring'}"
                  f" present={present}")
            if present:
                DEFECTS.append(f"(L1) deleted collection {C1} still present in "
                               f"list_collections — Type4_StateLogicViolation "
                               f"(qdrant_bc_delete_invisibility_001)")
        else:
            print(f"NOTE: list_collections returned {l1_s} — name-face list check "
                  f"inconclusive for L1")

        # ================= LEG 2: delete-by-alias status/state reconciliation ==
        if not create_with_alias(C2, A2, "L2"):
            print("SETUP_ERROR: leg-2 create/alias failed")
            return "SCRIPT_ERROR"
        d2_s, d2_raw = safe_request("DELETE", "drop_collection",
                                    path_params={"name": A2})
        print(f"[L2 delete-by-alias {A2}] status={d2_s} raw={d2_raw[:200]}")
        if d2_s == 0:
            liveness("L2-delete-by-alias")
            return "SCRIPT_ERROR"
        if 500 <= d2_s <= 599:
            if not liveness("L2-delete-by-alias"):
                return "SCRIPT_ERROR"
            DEFECTS.append(f"(L2) DELETE by alias returned {d2_s} with service "
                           f"alive — Type3_RuntimeFailure — raw={d2_raw[:200]}")
        else:
            # reconcile status with actual state of the underlying C2
            vd_s, vd_raw = safe_request("GET", "describe_collection",
                                        path_params={"name": C2})
            print(f"[L2 verify underlying {C2}] status={vd_s} raw={vd_raw[:160]}")
            l2_s, l2_raw = safe_request("GET", "list_collections")
            names2 = list_names(l2_raw) if l2_s == 200 else None
            present2 = ((C2 in names2) if names2 is not None
                        else (l2_s == 200 and C2 in (l2_raw or "")))
            print(f"[L2 list] status={l2_s} present={present2}")
            if 200 <= d2_s <= 299:
                # "confirmed" — underlying collection must be gone
                if vd_s != 404 or present2:
                    DEFECTS.append(f"(L2) DELETE by alias returned {d2_s} (confirmed) "
                                   f"but underlying state disagrees: describe(C2)="
                                   f"{vd_s}, in-list={present2} — status lies about "
                                   f"state — Type4_StateLogicViolation "
                                   f"(qdrant_behavioral_collections_delete_001) — "
                                   f"raw={d2_raw[:160]}/{vd_raw[:120]}")
            elif 400 <= d2_s <= 499:
                # rejected — underlying collection must still be there
                if vd_s != 200 or not present2:
                    DEFECTS.append(f"(L2) DELETE by alias returned {d2_s} (rejected) "
                                   f"but underlying state disagrees: describe(C2)="
                                   f"{vd_s}, in-list={present2} — rejection must not "
                                   f"delete — Type4_StateLogicViolation — "
                                   f"raw={d2_raw[:160]}/{vd_raw[:120]}")
            else:
                print(f"NOTE: delete-by-alias returned unconventional status "
                      f"{d2_s}; state recorded (describe={vd_s}) for the report")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        # cleanup: drop collections, then remove aliases (each independent,
        # each try/except — cleanup failure must not affect the verdict)
        for _coll in (C1, C2):
            try:
                rt.drop_collection(_coll)
            except Exception:
                pass
        for _al in (A1, A2):
            try:
                safe_request("POST", "update_aliases",
                             body={"actions": [{"delete_alias": {"alias_name": _al}}]})
            except Exception:
                pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
