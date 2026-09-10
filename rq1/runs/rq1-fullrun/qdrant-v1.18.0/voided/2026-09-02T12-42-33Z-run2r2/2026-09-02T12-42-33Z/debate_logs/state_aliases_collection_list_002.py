#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_aliases_collection_list_002
# strategy: count_consistency
# endpoint: aliases+collection+list
# constraint_ids: qdrant_behavioral_aliases_collection_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collection-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: CRUD-then-listing count consistency x qdrant_behavioral_aliases_collection_list_001
  (create 3 -> delete 1 -> rename 1 -> cross-collection isolation; per-collection
  listing count/membership must equal the alias map state after every accepted op;
  cross-face equality with the global aliases listing after every op)
Oracle: after each accepted alias op every listing face returns HTTP 200 whose alias set exactly equals the expected set (count and membership equal, no duplicate rows, no cross-face drift)
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
BASE_URL = BASE_URL.rstrip("/")

import requests  # noqa: E402

_FB_PRINTED = [False]


def _fallback_markers():
    if _FB_PRINTED[0]:
        return
    _FB_PRINTED[0] = True
    print("FALLBACK_TRIGGERED: per-collection alias listing (aliases+collection+list) has no qdrant runtime PATHS key; issuing the contract-derived REST path GET /collections/{collection_name}/aliases via requests")
    print("[FALLBACK_JUSTIFIED: scripts/runtime/qdrant.py PATHS exposes only update_aliases (POST /collections/aliases) and list_aliases (GET /aliases); the chunk unit endpoint aliases+collection+list (contract api_endpoints: method GET, required path parameter collection_name, source_url slug get-collection-aliases) is NOT reachable through the rt.request path_key whitelist; the REST route is derived 1:1 from the contract endpoint (raw_knowledge.json document_sources 0-12, v-1-18-x api-reference)]")


def collection_aliases_http(coll):
    """FALLBACK face: GET /collections/{collection_name}/aliases -> (status, raw_text)."""
    _fallback_markers()
    url = BASE_URL + "/collections/" + str(coll) + "/aliases"
    headers = {"Content-Type": "application/json"}
    _a = os.environ.get("TESTVDB_AUTH_HEADER", "")
    if _a:
        headers["Authorization"] = _a
    try:
        r = requests.get(url, headers=headers, timeout=30)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


# ---------------- helpers ----------------
def parse_aliases(raw):
    """result.aliases[] -> (dict alias_name->collection_name, dups list). None = unparsable."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError):
        return None
    node = b.get("result") if isinstance(b, dict) else None
    items = node.get("aliases") if isinstance(node, dict) else None
    if items is None or not isinstance(items, list):
        return None
    out, dups = {}, []
    for it in items:
        if isinstance(it, dict) and "alias_name" in it:
            a = it["alias_name"]
            if a in out:
                dups.append(a)
            out[a] = it.get("collection_name")
    return out, dups


def expect_2xx(s):
    return s in (200, 201)


def main():
    TS = str(int(time.time()))
    A = "salc_cnt_a_" + TS
    B = "salc_cnt_b_" + TS
    A1 = "salc_cnt_a1_" + TS
    A2 = "salc_cnt_a2_" + TS
    A3 = "salc_cnt_a3_" + TS
    A4 = "salc_cnt_a4_" + TS
    B1 = "salc_cnt_b1_" + TS
    DEFECTS = []
    created = []

    def batch(actions, label):
        s, raw = rt.request("POST", "update_aliases", {"actions": actions})
        print(f"[op:{label}] status={s} raw={raw[:160]}")
        if not expect_2xx(s):
            print(f"OP_FAILED {label}: {s} {raw[:200]}")
            return False
        return True

    def check_state(phase, exp_a, exp_b):
        """Three faces must agree: per-collection A, per-collection B, global list."""
        ok = True
        for coll, exp in ((A, exp_a), (B, exp_b)):
            s, raw = collection_aliases_http(coll)
            print(f"[face:{coll}] status={s} raw={raw[:300]}")
            if not expect_2xx(s):
                print(f"FACE_ANOMALY {coll}: {s} (existing collection should be 200)")
                return False  # probe anomaly -> SCRIPT_ERROR decision upstream
            m = parse_aliases(raw)
            if m is None:
                print(f"FACE_UNPARSEABLE {coll}: {raw[:200]}")
                return False
            m, dups = m
            got = {a: c for a, c in m.items()}
            if dups:
                DEFECTS.append(f"{phase}: face {coll} returned duplicate alias rows {dups}")
                ok = False
            if got != exp:
                DEFECTS.append(
                    f"{phase}: face {coll} listing = {got}, expected {exp} (Type4_StateLogicViolation)"
                )
                ok = False
        s, raw = rt.request("GET", "list_aliases")
        print(f"[face:global] status={s} raw={raw[:400]}")
        if not expect_2xx(s):
            print(f"FACE_ANOMALY global: {s}")
            return False
        g = parse_aliases(raw)
        if g is None:
            print(f"FACE_UNPARSEABLE global: {raw[:200]}")
            return False
        g, gdups = g
        full_exp = dict(exp_a)
        full_exp.update(exp_b)
        if gdups:
            DEFECTS.append(f"{phase}: global list returned duplicate rows {gdups}")
            ok = False
        if g != full_exp:
            DEFECTS.append(
                f"{phase}: global listing = {g}, expected {full_exp} "
                f"(cross-face drift vs per-collection faces, Type4_StateLogicViolation)"
            )
            ok = False
        # count-consistency cross-check: per-collection count == filtered global count
        for coll, exp in ((A, exp_a), (B, exp_b)):
            g_sub = {a: c for a, c in g.items() if c == coll}
            if g_sub != exp:
                DEFECTS.append(
                    f"{phase}: global projection for {coll} = {g_sub}, expected {exp} "
                    f"(per-collection face count {len(exp)} != global projection count {len(g_sub)}, "
                    f"Type4_StateLogicViolation)"
                )
                ok = False
        return ok

    try:
        for cname in (A, B):
            ok, err = rt.setup_default(cname, 128, "Cosine")
            if not ok:
                print(f"SETUP_ERROR create {cname}: {err}")
                return "SCRIPT_ERROR"
            created.append(cname)

        # Phase 1: create 3 aliases on A -> listing A == {a1,a2,a3}, B == {}
        if not batch([{"create_alias": {"collection_name": A, "alias_name": A1}},
                      {"create_alias": {"collection_name": A, "alias_name": A2}},
                      {"create_alias": {"collection_name": A, "alias_name": A3}}],
                     "create_3_on_A"):
            return "SCRIPT_ERROR"
        if not check_state("P1", {A1: A, A2: A, A3: A}, {}):
            return "SCRIPT_ERROR"

        # Phase 2: delete a2 -> listing A == {a1,a3}
        if not batch([{"delete_alias": {"alias_name": A2}}], "delete_a2"):
            return "SCRIPT_ERROR"
        if not check_state("P2", {A1: A, A3: A}, {}):
            return "SCRIPT_ERROR"

        # Phase 3: rename a3 -> a4 (same target A) -> listing A == {a1,a4}
        if not batch([{"rename_alias": {"old_alias_name": A3, "new_alias_name": A4}}], "rename_a3_to_a4"):
            return "SCRIPT_ERROR"
        if not check_state("P3", {A1: A, A4: A}, {}):
            return "SCRIPT_ERROR"

        # Phase 4: alias on B must NOT leak into A's listing (scope isolation)
        if not batch([{"create_alias": {"collection_name": B, "alias_name": B1}}], "create_b1_on_B"):
            return "SCRIPT_ERROR"
        if not check_state("P4", {A1: A, A4: A}, {B1: B}):
            return "SCRIPT_ERROR"

        # Phase 5: duplicate create of an existing alias (upsert semantics: still 1 row)
        if not batch([{"create_alias": {"collection_name": A, "alias_name": A1}}], "recreate_a1"):
            return "SCRIPT_ERROR"
        if not check_state("P5", {A1: A, A4: A}, {B1: B}):
            return "SCRIPT_ERROR"

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for c in created:
            try:
                rt.drop_collection(c)
            except Exception:
                pass
        try:
            rt.request("POST", "update_aliases", {"actions": [
                {"delete_alias": {"alias_name": A1}},
                {"delete_alias": {"alias_name": A4}},
                {"delete_alias": {"alias_name": B1}},
            ]})
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
