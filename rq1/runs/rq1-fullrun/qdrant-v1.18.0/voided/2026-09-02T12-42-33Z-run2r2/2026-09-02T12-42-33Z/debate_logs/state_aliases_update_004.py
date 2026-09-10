#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_aliases_update_004
# strategy: count_consistency
# endpoint: aliases+update
# constraint_ids: qdrant_bc_alias_switch_atomic_001, qdrant_behavioral_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (stale alias resolution: reads through the alias disagree with the target)
"""
Attack: count_consistency (Strategy 1 through the ALIAS indirection) +
  the behavioral contract's SEQUENTIAL scenario (positive/negative pair of
  the race in state_aliases_update_003): A holds 5 points, B holds 9;
  alias al->A. Stages: (1) count via al == count via A == 5; (2) rename
  al->al2 (name-only rename) must preserve the target: count via al2 == 5
  and the OLD name must stop resolving (404) and leave the listing;
  (3) single-request atomic switch [delete al2, create al2->B] -> 200 ->
  count via al2 must equal 9; (4) delete_alias al2 -> 200 -> count via al2
  must 404 and the row must leave the listing
  x qdrant_bc_alias_switch_atomic_001 (after a 200 the alias resolves to the
    new target; no intermediate state)
  x qdrant_behavioral_aliases_update_001 (valid batches return 200)
  [chunk_aliases+update coverage: count_consistency x
   qdrant_bc_alias_switch_atomic_001; count_consistency x
   qdrant_behavioral_aliases_update_001 (200 legs)]
Oracle: every count through a LIVE alias returns 200 and equals the current
  target's direct count (5 for A, 9 for B); after rename the old name
  returns 404 while the new name returns 200 with the SAME count; after the
  200 of the switch batch count via al2 == 9; after the 200 of delete_alias
  count via al2 == 404 and GET /aliases no longer lists al2 (any mismatch =
  Type4_StateLogicViolation)
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


# ---------------- helpers ----------------
def parse_aliases(raw):
    """result.aliases[] -> (mapping alias_name->collection_name, anomalies list)."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None, []
    node = b.get("result") if isinstance(b, dict) else None
    items = node.get("aliases") if isinstance(node, dict) else None
    if not isinstance(items, list):
        return None, []
    mapping, anoms = {}, []
    for it in items:
        if isinstance(it, dict) and "alias_name" in it:
            a = it["alias_name"]
            if a in mapping:
                anoms.append(f"duplicate-row:{a}")
            mapping[a] = it.get("collection_name")
        else:
            anoms.append(f"malformed-entry:{str(it)[:60]}")
    return mapping, anoms


def alive():
    """D3b liveness re-check via the lightweight health endpoint."""
    hs, hraw = rt.request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def exact_count(name):
    """POST count {exact:true} via collection name OR alias -> (status, count|None, raw)."""
    s, raw = rt.request("POST", "count", {"exact": True}, path_params={"name": name})
    if s != 200:
        return s, None, raw
    try:
        b = json.loads(raw) if raw else {}
        cnt = b.get("result", {}).get("count") if isinstance(b, dict) else None
        if not isinstance(cnt, int):
            return s, None, raw
        return s, cnt, raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def seed_point(name, n):
    pts = [{"id": i, "vector": [0.10 + 0.01 * i, 0.2, 0.3, 0.4]} for i in range(n)]
    s, raw = rt.request("PUT", "upsert_points", {"points": pts},
                        path_params={"name": name}, query_params={"wait": "true"})
    print(f"[seed {name} x{n}] status={s} raw={raw[:200]}")
    return s in (200, 201)


def alias_face(pfx):
    """GET /aliases -> (mode, prefix-map or None, status, raw)."""
    s, raw = rt.request("GET", "list_aliases")
    print(f"[list_aliases] status={s} raw={raw[:800]}")
    if s == 0 or 500 <= s <= 599 or s in (401, 403):
        alive()
        return "ENV_DOWN", None, s, raw
    if s != 200:
        return "FACE_DEFECT", None, s, raw
    mapping, _ = parse_aliases(raw)
    if mapping is None:
        return "FACE_DEFECT", None, s, raw
    return "OK", {a: c for a, c in mapping.items() if str(a).startswith(pfx)}, s, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sau4_" + TS + "_"
    A = PFX + "colA"
    B = PFX + "colB"
    AL = PFX + "al"
    AL2 = PFX + "al2"
    COUNT_A, COUNT_B = 5, 9
    DEFECTS = []

    def expect_count(label, via, want_status, want_count=None):
        """Declared-expectation read: exact status (+count when 200 promised)."""
        s, cnt, raw = exact_count(via)
        print(f"[{label}] via={via} status={s} count={cnt} raw={str(raw)[:200]}")
        if s == 0 or (500 <= s <= 599) or s in (401, 403):
            alive()
            return "ENV_DOWN"
        if s != want_status:
            DEFECTS.append(
                f"{label}: read via {via} returned {s}, expected {want_status} — "
                f"Type4_StateLogicViolation raw={str(raw)[:200]}"
            )
            return "BAD"
        if want_status == 200 and want_count is not None and cnt != want_count:
            DEFECTS.append(
                f"{label}: count via {via} = {cnt}, expected {want_count} — alias "
                f"resolution disagrees with the target collection — "
                f"Type4_StateLogicViolation"
            )
            return "BAD"
        return "OK"

    try:
        # ---- setup ----
        for c in (A, B):
            ok, err = rt.setup_default(c, 4, "Cosine")
            if not ok:
                print(f"SETUP_ERROR create {c}: {err}")
                return "SCRIPT_ERROR"
        if not seed_point(A, COUNT_A) or not seed_point(B, COUNT_B):
            print("SETUP_ERROR seeding points")
            return "SCRIPT_ERROR"
        s, raw = rt.request("POST", "update_aliases", {"actions": [
            {"create_alias": {"collection_name": A, "alias_name": AL}},
        ]})
        print(f"[create {AL}->{A}] status={s} raw={raw[:300]}")
        if s != 200:
            print(f"SETUP_ERROR create alias: {s} {raw[:200]}")
            return "SCRIPT_ERROR"

        # ---- stage 1: count via alias == direct count of A ----
        r1 = expect_count("stage1 direct A", A, 200, COUNT_A)
        r2 = expect_count("stage1 via alias", AL, 200, COUNT_A)
        if r1 == "ENV_DOWN" or r2 == "ENV_DOWN":
            return "SCRIPT_ERROR"

        # ---- stage 2: rename al -> al2 (name change, target preserved) ----
        s, raw = rt.request("POST", "update_aliases", {"actions": [
            {"rename_alias": {"old_alias_name": AL, "new_alias_name": AL2}},
        ]})
        print(f"[rename {AL}->{AL2}] status={s} raw={raw[:300]}")
        v = rt.judge_200(s, raw, setup_ok=True)
        if v == "SCRIPT_ERROR":
            alive()
            return "SCRIPT_ERROR"
        if v == "DEFECT_FOUND":
            DEFECTS.append(
                f"stage2 rename: legal rename_alias returned {s} (promised 200) "
                f"raw={str(raw)[:200]}"
            )
        else:
            r3 = expect_count("stage2 via new name (target preserved)", AL2, 200, COUNT_A)
            r4 = expect_count("stage2 via old name (must stop resolving)", AL, 404)
            if r3 == "ENV_DOWN" or r4 == "ENV_DOWN":
                return "SCRIPT_ERROR"

        mode, mine, fs, fraw = alias_face(PFX)
        if mode == "ENV_DOWN":
            return "SCRIPT_ERROR"
        if mode == "FACE_DEFECT":
            DEFECTS.append(f"stage2: GET /aliases face failed ({fs}) raw={str(fraw)[:200]}")
        else:
            if AL in mine:
                DEFECTS.append(
                    f"stage2: old alias name {AL} still listed after a 200 rename to "
                    f"{AL2} (maps to {mine.get(AL)}) — stale row — "
                    f"Type4_StateLogicViolation"
                )
            if mine.get(AL2) != A:
                DEFECTS.append(
                    f"stage2: after rename, expected {{{AL2}: {A}}}, prefix map says "
                    f"{mine.get(AL2)} — rename lost/retargeted the mapping — "
                    f"Type4_StateLogicViolation"
                )
            if mine.get(AL2) == A and AL not in mine:
                print(f"stage2 OK: rename {AL}->{AL2} preserved target {A}")

        # ---- stage 3: atomic switch [delete al2, create al2->B] in ONE request ----
        s, raw = rt.request("POST", "update_aliases", {"actions": [
            {"delete_alias": {"alias_name": AL2}},
            {"create_alias": {"collection_name": B, "alias_name": AL2}},
        ]})
        print(f"[atomic switch {AL2}: {A}->{B}] status={s} raw={raw[:300]}")
        v = rt.judge_200(s, raw, setup_ok=True)
        if v == "SCRIPT_ERROR":
            alive()
            return "SCRIPT_ERROR"
        if v == "DEFECT_FOUND":
            DEFECTS.append(
                f"stage3 atomic switch: legal single-request switch returned {s} "
                f"(promised 200) raw={str(raw)[:200]}"
            )
        else:
            r5 = expect_count("stage3 via alias after 200 switch", AL2, 200, COUNT_B)
            if r5 == "ENV_DOWN":
                return "SCRIPT_ERROR"
            mode, mine2, fs2, fraw2 = alias_face(PFX)
            if mode == "OK" and mine2.get(AL2) != B:
                DEFECTS.append(
                    f"stage3: after a 200 switch, listing says {AL2}->{mine2.get(AL2)}, "
                    f"expected ->{B} — Type4_StateLogicViolation"
                )

        # ---- stage 4: delete_alias -> reads must 404 and the row must vanish ----
        s, raw = rt.request("POST", "update_aliases", {"actions": [
            {"delete_alias": {"alias_name": AL2}},
        ]})
        print(f"[delete {AL2}] status={s} raw={raw[:300]}")
        v = rt.judge_200(s, raw, setup_ok=True)
        if v == "SCRIPT_ERROR":
            alive()
            return "SCRIPT_ERROR"
        if v == "DEFECT_FOUND":
            DEFECTS.append(
                f"stage4 delete: deleting a live alias returned {s} (promised 200) "
                f"raw={str(raw)[:200]}"
            )
        else:
            r6 = expect_count("stage4 via deleted alias", AL2, 404)
            if r6 == "ENV_DOWN":
                return "SCRIPT_ERROR"
            mode, mine3, fs3, fraw3 = alias_face(PFX)
            if mode == "OK" and AL2 in mine3:
                DEFECTS.append(
                    f"stage4: alias {AL2} still listed (->{mine3.get(AL2)}) after a "
                    f"200 delete_alias — post-delete residue — "
                    f"Type4_StateLogicViolation"
                )
            elif mode == "OK":
                print("stage4 OK: deleted alias row gone from the listing")

        # collections themselves must be untouched by all alias churn
        r7 = expect_count("final direct A", A, 200, COUNT_A)
        r8 = expect_count("final direct B", B, 200, COUNT_B)
        if r7 == "ENV_DOWN" or r8 == "ENV_DOWN":
            return "SCRIPT_ERROR"

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.request("POST", "update_aliases", {"actions": [
                {"delete_alias": {"alias_name": AL}},
                {"delete_alias": {"alias_name": AL2}},
            ]})
        except Exception:
            pass
        for c in (A, B):
            try:
                rt.drop_collection(c)
            except Exception:
                pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
