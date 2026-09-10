#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_list_003
# strategy: upsert_idempotence
# endpoint: collections+list
# constraint_ids: qdrant_behavioral_collections_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collections
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 3 (idempotence) lifted to the collection-registry
  level and judged through the global LIST face (collections+list;
  runtime PATHS list_collections = /collections, verbatim
  raw_knowledge api_endpoints[].url). The registry behind
  qdrant_behavioral_collections_list_001 (200 + result.collections[]
  of {name} entries) must stay a SET keyed by name: an idempotent or
  repeated mutation of one name may never yield two entries, and a
  recreate may never pair a stale entry with the new one.
  Mutation justification (G6): duplicate-create and
  recreate-after-delete are the two mutations that most easily break a
  name-keyed registry -- they are the exact points where an
  insert-without-dedup or an append-without-tombstone-check shows up
  as duplicate/ghost entries in the list.
  (A) create X -> listed exactly once (positive leg).
  (B) duplicate PUT create with the SAME body (its status belongs to
      the create chunk's unit -- printed, NOT judged here) -> X must
      STILL appear exactly once; two entries for one name = registry
      violated its key semantics.
  (C) delete X -> 200 -> X absent (bounded retry).
  (D) recreate X -> 200 -> X present EXACTLY once (a stale entry
      surviving alongside the recreated one = duplicate).
  (E) idempotent re-read: two back-to-back lists must agree on X's
      membership (flap between present/absent with no mutation in
      between = state inconsistency).
  Global-face discipline: membership PREFIX-FILTERED (siblings
  tolerated); envelope shape judged on all entries.
  [chunk_collections+list coverage: upsert_idempotence x
   qdrant_behavioral_collections_list_001 (duplicate-create /
   recreate-after-delete dedup / read idempotence through the list
   face)]
Oracle: X appears in result.collections exactly once after its create,
  exactly once after a duplicate create of the same name/body, is
  absent after a 200-confirmed delete (bounded retries), and exactly
  once again after recreate; two entries for X at any point =
  Type4_StateLogicViolation (registry key semantics); X absent when it
  exists or present when deleted = Type4; two consecutive lists
  disagreeing on X with no mutation between them = Type4; non-200 on
  the list face with /healthz alive = Type4; 5xx with /healthz alive =
  Type3_RuntimeFailure.
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
    PFX = "scl3_" + TS + "_"
    X = PFX + "x"
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

    def dupes_of(names):
        mine = [n for n in (names or [])
                if isinstance(n, str) and n.startswith(PFX)]
        return sorted({n for n in mine if mine.count(n) > 1})

    try:
        # ---- (A) positive leg: created once -> listed exactly once ----
        ok, err = rt.setup_default(X, DIM, "Cosine")
        if not ok:
            print(f"SETUP_FAIL: create {X} {err}")
            return "SCRIPT_ERROR"
        st, names = list_until("A", lambda ns: ns.count(X) == 1)
        if st == "ERR":
            return "SCRIPT_ERROR"
        if st == "NO":
            cnt = (names or []).count(X)
            DEFECTS.append(f"(A) after create, {X} appears {cnt} times "
                           f"(expected exactly 1) — "
                           f"Type4_StateLogicViolation")

        # ---- (B) duplicate create, same body: registry must stay a set ----
        s, raw = safe_request("PUT", "create_collection",
                              {"vectors": {"size": DIM, "distance": "Cosine"}},
                              path_params={"name": X},
                              query_params={"timeout": "30"})
        print(f"[duplicate create {X}] status={s} raw={str(raw)[:200]} "
              f"(status NOT judged here — create chunk's unit)")
        st, names = list_until("B", lambda ns: ns.count(X) == 1)
        if st == "ERR":
            return "SCRIPT_ERROR"
        if st == "NO":
            cnt = (names or []).count(X)
            DEFECTS.append(f"(B) after a duplicate create of the same name, "
                           f"{X} appears {cnt} times in result.collections "
                           f"(registry must stay keyed by name) — "
                           f"Type4_StateLogicViolation")
        d = dupes_of(names)
        if d:
            DEFECTS.append(f"(B) duplicated prefixed entries {d} after "
                           f"duplicate create — Type4_StateLogicViolation")

        # ---- (C) delete -> absent (bounded retry) ----
        s, raw = safe_request("DELETE", "drop_collection",
                              path_params={"name": X},
                              query_params={"timeout": "30"})
        print(f"[delete {X}] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print(f"SETUP_FAIL: delete {X} returned {s}")
            return "SCRIPT_ERROR"
        st, names = list_until("C", lambda ns: X not in ns)
        if st == "ERR":
            return "SCRIPT_ERROR"
        if st == "NO":
            DEFECTS.append(f"(C) {X} persists in the list after a "
                           f"200-confirmed delete — Type4_StateLogicViolation")

        # ---- (D) recreate -> present EXACTLY once (no stale+new pair) ----
        ok, err = rt.setup_default(X, DIM, "Euclid")
        if not ok:
            print(f"SETUP_FAIL: recreate {X} {err}")
            return "SCRIPT_ERROR"
        st, names = list_until("D", lambda ns: ns.count(X) == 1)
        if st == "ERR":
            return "SCRIPT_ERROR"
        if st == "NO":
            cnt = (names or []).count(X)
            DEFECTS.append(f"(D) after recreate of a deleted name, {X} "
                           f"appears {cnt} times (stale entry surviving "
                           f"alongside the recreated one) — "
                           f"Type4_StateLogicViolation")
        d = dupes_of(names)
        if d:
            DEFECTS.append(f"(D) duplicated prefixed entries {d} after "
                           f"recreate — Type4_StateLogicViolation")

        # ---- (E) idempotent re-read: two back-to-back lists must agree ----
        st1, names1 = list_face("E.1")
        st2, names2 = list_face("E.2")
        if st1 == "ERR" or st2 == "ERR":
            return "SCRIPT_ERROR"
        if st1 == "OK" and st2 == "OK":
            m1 = (X in names1)
            m2 = (X in names2)
            if m1 != m2:
                DEFECTS.append(f"(E) two consecutive lists with no mutation "
                               f"in between disagree on {X}: first="
                               f"{m1} second={m2} — Type4_StateLogicViolation")
            elif names1 != names2:
                d1 = dupes_of(names1) + dupes_of(names2)
                print(f"OBSERVATION: consecutive lists differ in content "
                      f"(sibling churn tolerated); prefixed dupes={d1}")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(X)
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
