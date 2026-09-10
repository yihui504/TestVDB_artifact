#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_list_002
# strategy: delete_consistency
# endpoint: collections+list
# constraint_ids: qdrant_behavioral_collections_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collections
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 2 (post-DELETE consistency) executed through the
  global LIST face (collections+list; runtime PATHS list_collections =
  /collections, verbatim raw_knowledge api_endpoints[].url).
  qdrant_behavioral_collections_list_001 pins the face (200 +
  result.collections[] of {name} entries); the state semantics probed
  here are qdrant_inv_delete_gone_001 / qdrant_bc_delete_invisibility_
  001's "deleted collection is absent from the list" leg, judged
  through THIS chunk's face. Global-face discipline: membership
  assertions are PREFIX-FILTERED (sibling collections tolerated); only
  the envelope shape is judged on all entries.
  (A positive pairing) create A1, A2 -> both listed exactly once
      (the promise exercised before it is challenged).
  (B post-delete) DELETE A1 -> 200; IMMEDIATE list records whether A1
      is already absent; bounded retries then require converged
      absence. Immediate-presence that converges = OBSERVATION
      (eventual consistency); never-absent = zombie = Type4. A2 must
      stay present throughout (no collateral disappearance).
  (C settle recheck) after 1s the list still excludes A1 and includes
      A2 (no resurrection / no flapping).
  (D create-delete immediacy) create A3 -> 200, DELETE A3 -> 200,
      immediately list -> A3 absent (same immediate/converged
      discipline on a fresh name).
  (E redundant-delete pressure) a redundant DELETE against the absent
      A1 is issued (its status belongs to the delete chunk's unit --
      printed, NOT judged here), then the list must STILL exclude A1:
      redundant operations must not resurrect registry entries.
  [chunk_collections+list coverage: delete_consistency x
   qdrant_behavioral_collections_list_001 (post-delete absence /
   zombie persistence / redundant-delete pressure / collateral
   survival through the list face)]
Oracle: after a 200-confirmed DELETE of A1 the list face converges
  within bounded retries (4 attempts / 0.5s apart) to exclude A1
  while keeping A2 present exactly once; a persisting A1 entry =
  Type4_StateLogicViolation (zombie); A2 disappearing = Type4; a
  redundant DELETE against the absent name must not reintroduce A1
  (reappearance = Type4); non-200 on the list face with /healthz
  alive = Type4; 5xx with /healthz alive = Type3_RuntimeFailure;
  immediate-presence-that-converges is logged as an OBSERVATION, not
  a defect.
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

DIM = 4


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scl2_" + TS + "_"
    A1 = PFX + "a1"
    A2 = PFX + "a2"
    A3 = PFX + "a3"
    DEFECTS = []

    def alive():
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    def list_face(tag):
        """One list call: transport/5xx/non-200/shape triage.
        Returns ('OK', names) / ('BAD', None) / ('ERR', None)."""
        s, raw = safe_request("GET", "list_collections")
        print(f"[list#{tag}] status={s} raw={str(raw)[:240]}")
        if s == 0:
            alive()
            return "ERR", None
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"list#{tag} returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "ERR", None
            return "BAD", None
        if s != 200:
            if alive():
                DEFECTS.append(f"list#{tag} returned {s} (assertion pins 200 + "
                               f"result.collections[] array) — "
                               f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
            else:
                return "ERR", None
            return "BAD", None
        b = parse_json(raw)
        res = b.get("result") if isinstance(b, dict) else None
        cols = res.get("collections") if isinstance(res, dict) else None
        if not isinstance(cols, list):
            DEFECTS.append(f"list#{tag} 200 body lacks the result.collections "
                           f"array (assertion: array of {{name}} entries) — "
                           f"Type4_StateLogicViolation — raw={str(raw)[:200]} "
                           f"(qdrant_behavioral_collections_list_001)")
            return "BAD", None
        names = []
        bad = 0
        for e in cols:
            if isinstance(e, dict) and isinstance(e.get("name"), str) and e["name"]:
                names.append(e["name"])
            else:
                bad += 1
        if bad:
            DEFECTS.append(f"list#{tag}: {bad} entries in result.collections "
                           f"carry no non-empty string name — "
                           f"Type4_StateLogicViolation")
        return "OK", names

    def list_until(tag, pred, attempts=4, delay=0.5):
        names = None
        for i in range(attempts):
            st, names = list_face(f"{tag}.{i}")
            if st == "ERR":
                return "ERR", None
            if st == "OK" and pred(names):
                return "OK", names
            if i < attempts - 1:
                time.sleep(delay)
        return "NO", names

    try:
        # ---- (A) positive pairing: both created names listed exactly once ----
        for n in (A1, A2):
            ok, err = rt.setup_default(n, DIM, "Cosine")
            if not ok:
                print(f"SETUP_FAIL: create {n} {err}")
                return "SCRIPT_ERROR"
        st, names = list_until("A", lambda ns: A1 in ns and A2 in ns)
        if st == "ERR":
            return "SCRIPT_ERROR"
        if st == "NO":
            miss = [n for n in (A1, A2) if n not in (names or [])]
            DEFECTS.append(f"positive leg: created names {miss} missing from "
                           f"the list face — Type4_StateLogicViolation "
                           f"(qdrant_behavioral_collections_list_001)")
        else:
            mine = [n for n in names if n.startswith(PFX)]
            d = sorted({n for n in mine if mine.count(n) > 1})
            if d:
                DEFECTS.append(f"positive leg: duplicated entries {d} — "
                               f"Type4_StateLogicViolation")

        # ---- (B) delete A1 -> immediate + converged absence, A2 survives ----
        s, raw = safe_request("DELETE", "drop_collection",
                              path_params={"name": A1},
                              query_params={"timeout": "30"})
        print(f"[delete {A1}] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print(f"SETUP_FAIL: delete {A1} returned {s} (state transition "
                  f"only; its face is the delete chunk's unit)")
            return "SCRIPT_ERROR"

        st_i, names_i = list_face("B.immediate")
        immediate_absent = (st_i == "OK" and A1 not in names_i)
        if st_i == "ERR":
            return "SCRIPT_ERROR"

        st, names = list_until("B", lambda ns: A1 not in ns and A2 in ns)
        if st == "ERR":
            return "SCRIPT_ERROR"
        if st == "NO":
            if A1 in (names or []):
                DEFECTS.append(f"zombie entry {A1} persists in the list after a "
                               f"200-confirmed delete + bounded retries — "
                               f"Type4_StateLogicViolation (mirrors "
                               f"qdrant_inv_delete_gone_001 absence leg)")
            if A2 not in (names or []):
                DEFECTS.append(f"collateral disappearance: surviving {A2} "
                               f"missing from the list after deleting {A1} — "
                               f"Type4_StateLogicViolation")
        elif st_i == "OK" and not immediate_absent:
            print(f"OBSERVATION: {A1} still listed on the FIRST list after the "
                  f"200-delete but converged to absent within bounded retries "
                  f"(eventual consistency on the list face)")

        # ---- (C) settle recheck: no resurrection / no flapping ----
        time.sleep(1.0)
        st, names = list_until("C", lambda ns: A1 not in ns and A2 in ns)
        if st == "ERR":
            return "SCRIPT_ERROR"
        if st == "NO":
            if A1 in (names or []):
                DEFECTS.append(f"{A1} REAPPEARED in the list after settled "
                               f"absence (resurrection/flap) — "
                               f"Type4_StateLogicViolation")
            if A2 not in (names or []):
                DEFECTS.append(f"{A2} disappeared at settle recheck — "
                               f"Type4_StateLogicViolation")

        # ---- (D) create-delete immediacy on a fresh name ----
        ok, err = rt.setup_default(A3, DIM, "Cosine")
        if not ok:
            print(f"SETUP_FAIL: create {A3} {err}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("DELETE", "drop_collection",
                              path_params={"name": A3},
                              query_params={"timeout": "30"})
        print(f"[delete {A3}] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print(f"SETUP_FAIL: delete {A3} returned {s}")
            return "SCRIPT_ERROR"
        st, names = list_until("D", lambda ns: A3 not in ns and A2 in ns)
        if st == "ERR":
            return "SCRIPT_ERROR"
        if st == "NO":
            if A3 in (names or []):
                DEFECTS.append(f"fresh name {A3} persists in the list after "
                               f"create->200-delete — Type4_StateLogicViolation")

        # ---- (E) redundant delete against the absent name must not resurrect ----
        s, raw = safe_request("DELETE", "drop_collection",
                              path_params={"name": A1},
                              query_params={"timeout": "30"})
        print(f"[redundant delete {A1}] status={s} raw={str(raw)[:160]} "
              f"(status NOT judged here — delete chunk's unit)")
        st, names = list_until("E", lambda ns: A1 not in ns and A2 in ns)
        if st == "ERR":
            return "SCRIPT_ERROR"
        if st == "NO":
            if A1 in (names or []):
                DEFECTS.append(f"redundant DELETE against absent {A1} "
                               f"RESURRECTED its list entry — "
                               f"Type4_StateLogicViolation")
            if A2 not in (names or []):
                DEFECTS.append(f"{A2} disappeared after redundant-delete "
                               f"pressure — Type4_StateLogicViolation")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for n in (A1, A2, A3):
            try:
                rt.drop_collection(n)
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
