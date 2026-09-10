#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_exists_002
# strategy: delete_consistency
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: post-DELETE exists consistency + cross-face agreement
  (Strategy 2). collections+exists pins the channel: a missing
  collection yields HTTP 200 + result.exists=false, NEVER 404 — even
  right after a deletion, and no matter how many redundant deletions
  are issued against the absent name. Additionally the exists face
  must AGREE with the other state faces of the same name (G9:
  same parameter, different interface faces — inconsistent
  disposition across faces is itself a defect signal):
    describe face  GET /collections/{name}        -> non-200 (absent)
    list face      GET /collections               -> name absent from result.collections
    exists face    GET /collections/{name}/exists -> 200 + result.exists=false
  Legs:
  (A setup) create C -> 200; exists=true sanity (setup gate).
  (B post-delete) DELETE C -> 200; immediately exists(C) -> 200+false.
  (C redundant-delete pressure) issue a second DELETE (its own status
      is the delete chunk's unit — printed, NOT judged here), then
      exists(C) again -> must STILL be 200+false (no 404, no true).
  (D cross-face, absent) describe(C) non-200 AND list face must not
      contain C AND exists says false — any face claiming presence
      while exists says false (or vice versa) = Type4.
  (E recreate) recreate C -> exists=true AND describe=200 AND name
      present in list — all three faces must flip to present together.
  (F final delete) drop C -> exists=200+false one last time.
  [chunk_collections+exists coverage: delete_consistency x
   qdrant_behavioral_collections_exists_001 (immediate post-delete /
   redundant-delete pressure / describe+list cross-face agreement /
   recreate face-flip)]
Oracle: after a 200-confirmed DELETE -> exists returns exactly
  200 + result.exists=false (before AND after a redundant delete);
  describe returns non-200 and the name is absent from
  GET /collections at the same time; after recreate all three faces
  report present together. A 404/other non-200 on exists, a true
  verdict on the deleted name, or any face disagreement =
  Type4_StateLogicViolation; 5xx = Type3_RuntimeFailure only after
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

# exists endpoint is not in the runtime PATHS whitelist — register it
# VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "collections+exists", "method": "GET",
#    "url": "/collections/{collection_name}/exists"}
rt.PATHS["collection_exists"] = "/collections/{collection_name}/exists"
if rt.PATHS.get("collection_exists") != "/collections/{collection_name}/exists":
    print("VERDICT: SCRIPT_ERROR - exists URL registration failed")
    sys.exit(2)


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_exists(raw):
    """Shape-checked readout per materialized response_shape
    (result: object, result.exists: boolean)."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return False, None, "non-JSON body"
    res = b.get("result") if isinstance(b, dict) else None
    if isinstance(res, bool):
        return False, res, "result is a bare bool (spec pins result.exists object shape)"
    if not isinstance(res, dict):
        return False, None, "result missing or not an object"
    ev = res.get("exists")
    if not isinstance(ev, bool):
        return False, None, "result.exists missing or not a boolean"
    return True, ev, ""


def parse_list_collections(raw):
    """GET /collections -> (names list or None, parsed_ok)."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None, False
    res = b.get("result") if isinstance(b, dict) else None
    cols = res.get("collections") if isinstance(res, dict) else None
    if not isinstance(cols, list):
        return None, True
    return [c if isinstance(c, str) else str(c.get("name", "")) if isinstance(c, dict) else str(c)
            for c in cols], True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sce2_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    def liveness(tag):
        print(f"[liveness {tag}] healthz probe required")
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    def probe_exists(tag, expect):
        """Judged exists probe. Returns True/False (False = defect recorded)
        or None when the run must abort (env-class)."""
        s, raw = safe_request("GET", "collection_exists",
                              path_params={"collection_name": C})
        print(f"[{tag}] status={s} raw={str(raw)[:200]}")
        if s == 0:
            liveness(tag)
            return None
        if 500 <= s <= 599:
            if liveness(tag):
                DEFECTS.append(f"({tag}) exists returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
                return False
            return None
        shape_ok, ev, note = parse_exists(raw)
        if s != 200:
            chan = "never 404" if s == 404 else "HTTP 200 expected"
            DEFECTS.append(f"({tag}) exists returned {s} (assertion pins {chan}; "
                           f"existence belongs in the body) — Type4_StateLogicViolation "
                           f"— raw={str(raw)[:150]} "
                           f"(qdrant_behavioral_collections_exists_001)")
            return False
        if not shape_ok:
            DEFECTS.append(f"({tag}) exists returned 200 but body violates the pinned "
                           f"shape result.exists:boolean ({note}) — Type4_StateLogicViolation "
                           f"— raw={str(raw)[:150]}")
            return False
        if ev != expect:
            DEFECTS.append(f"({tag}) exists verdict is {ev} but state demands {expect} — "
                           f"Type4_StateLogicViolation "
                           f"(qdrant_behavioral_collections_exists_001)")
            return False
        print(f"[{tag}] OK: 200 + result.exists={ev}")
        return True

    def describe(tag):
        s, raw = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[{tag}] describe status={s} raw={str(raw)[:150]}")
        return s

    def list_contains_c(tag):
        s, raw = safe_request("GET", "list_collections")
        names, parsed_ok = parse_list_collections(raw)
        print(f"[{tag}] list status={s} parsed={parsed_ok} contains_C={names is not None and C in names} "
              f"raw={str(raw)[:150]}")
        if s == 0 or 500 <= s <= 599 or not parsed_ok or names is None:
            liveness(tag)
            return None
        return C in names

    try:
        # ---- (A setup) create + exists=true sanity ----
        a_s, a_raw = safe_request("PUT", "create_collection", path_params={"name": C},
                                  body={"vectors": {"size": 4, "distance": "Cosine"}})
        print(f"[A create] status={a_s} raw={a_raw[:200]}")
        if a_s != 200:
            print(f"SETUP_ERROR: create returned {a_s}")
            return "SCRIPT_ERROR"
        if probe_exists("A exists-live", True) is None:
            return "SCRIPT_ERROR"

        # ---- (B post-delete) immediate exists -> 200 + false ----
        b_s, b_raw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[B delete] status={b_s} raw={b_raw[:150]}")
        if b_s != 200:
            print(f"SETUP_ERROR: delete returned {b_s} — cannot judge post-delete exists")
            return "SCRIPT_ERROR"
        if probe_exists("B post-delete", False) is None:
            return "SCRIPT_ERROR"

        # ---- (C redundant-delete pressure) ----
        c_s, c_raw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[C redundant delete] status={c_s} raw={c_raw[:150]} "
              f"(delete-face status NOT judged here — different chunk unit)")
        if probe_exists("C after-redundant-delete", False) is None:
            return "SCRIPT_ERROR"

        # ---- (D cross-face agreement while absent) ----
        d_desc = describe("D describe-absent")
        if d_desc == 0:
            liveness("D")
            return "SCRIPT_ERROR"
        d_list = list_contains_c("D list-absent")
        if d_list is None:
            return "SCRIPT_ERROR"
        # exists face already judged false in (C); reconcile the three faces
        if d_desc == 200:
            DEFECTS.append(f"(D) cross-face disagreement: exists says absent (false, "
                           f"200) but describe face returns 200 for {C} — one face "
                           f"claims presence, another absence — Type4_StateLogicViolation "
                           f"(qdrant_behavioral_collections_exists_001)")
        if d_list:
            DEFECTS.append(f"(D) cross-face disagreement: exists says absent (false, "
                           f"200) but GET /collections still lists {C} — "
                           f"Type4_StateLogicViolation "
                           f"(qdrant_behavioral_collections_exists_001)")

        # ---- (E recreate: all three faces flip to present together) ----
        e_s, e_raw = safe_request("PUT", "create_collection", path_params={"name": C},
                                  body={"vectors": {"size": 4, "distance": "Cosine"}})
        print(f"[E recreate] status={e_s} raw={e_raw[:150]}")
        if e_s != 200:
            print(f"SETUP_ERROR: recreate returned {e_s}")
            return "SCRIPT_ERROR"
        if probe_exists("E exists-recreated", True) is None:
            return "SCRIPT_ERROR"
        e_desc = describe("E describe-recreated")
        e_list = list_contains_c("E list-recreated")
        if e_desc == 0 or e_list is None:
            liveness("E")
            return "SCRIPT_ERROR"
        if e_desc != 200 or not e_list:
            which = []
            if e_desc != 200:
                which.append(f"describe={e_desc}")
            if not e_list:
                which.append("list-absent")
            DEFECTS.append(f"(E) cross-face disagreement after recreate: exists=true "
                           f"but {', '.join(which)} — faces did not flip to present "
                           f"together — Type4_StateLogicViolation "
                           f"(qdrant_behavioral_collections_exists_001)")

        # ---- (F final delete + exists) ----
        f_s, _ = safe_request("DELETE", "drop_collection", path_params={"name": C})
        if f_s != 200:
            print(f"SETUP_ERROR: final delete returned {f_s}")
            return "SCRIPT_ERROR"
        if probe_exists("F final-post-delete", False) is None:
            return "SCRIPT_ERROR"

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
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
