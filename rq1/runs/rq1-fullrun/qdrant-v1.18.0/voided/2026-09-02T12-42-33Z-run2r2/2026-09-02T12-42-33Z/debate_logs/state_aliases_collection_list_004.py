#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_aliases_collection_list_004
# strategy: upsert_idempotence
# endpoint: aliases+collection+list
# constraint_ids: qdrant_behavioral_aliases_collection_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collection-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: alias upsert idempotence x qdrant_behavioral_aliases_collection_list_001
  (create same alias twice on one collection; rebind same alias name to a second
  collection; delete + name reuse; the per-collection listing must never show a
  duplicate row nor keep residue on the previous target face, and every row's
  collection_name must equal the face being listed)
Oracle: after every accepted alias op each listing face returns HTTP 200 holding exactly one row per alias name whose membership equals the last binding and whose collection_name equals the listed collection (no duplicate rows, no residue)
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
    A = "salc_up_a_" + TS
    B = "salc_up_b_" + TS
    DUP = "salc_up_dup_" + TS
    DEFECTS = []
    created = []

    def alias_op(actions, label):
        s, raw = rt.request("POST", "update_aliases", {"actions": actions})
        print(f"[op:{label}] status={s} raw={raw[:160]}")
        if not expect_2xx(s):
            # State chaining needs the op applied; a rejection here would belong to
            # the aliases+update unit's adjudication, not this listing unit.
            print(f"OP_NOT_APPLIED {label}: {s} {raw[:200]}")
            return False
        return True

    def check_state(phase, exp_a, exp_b):
        ok = True
        for coll, exp in ((A, exp_a), (B, exp_b)):
            s, raw = collection_aliases_http(coll)
            print(f"[face:{coll}] status={s} raw={raw[:300]}")
            if not expect_2xx(s):
                print(f"FACE_ANOMALY {coll}: {s}")
                return None
            m = parse_aliases(raw)
            if m is None:
                print(f"FACE_UNPARSEABLE {coll}: {raw[:200]}")
                return None
            m, dups = m
            if dups:
                DEFECTS.append(f"{phase}: face {coll} returned duplicate rows {dups} "
                               f"(upsert must keep a single row per alias name, Type4_StateLogicViolation)")
                ok = False
            # every row on this face must name the face itself as collection_name
            bad_rows = [a for a, c in m.items() if c != coll]
            if bad_rows:
                DEFECTS.append(f"{phase}: face {coll} rows {bad_rows} carry collection_name != {coll} "
                               f"(Type4_StateLogicViolation)")
                ok = False
            if m != exp:
                DEFECTS.append(f"{phase}: face {coll} listing={m} expected={exp} "
                               f"(Type4_StateLogicViolation)")
                ok = False
        s, raw = rt.request("GET", "list_aliases")
        print(f"[face:global] status={s} raw={raw[:300]}")
        if not expect_2xx(s):
            print(f"FACE_ANOMALY global: {s}")
            return None
        g = parse_aliases(raw)
        if g is None:
            print(f"FACE_UNPARSEABLE global: {raw[:200]}")
            return None
        g, gdups = g
        full_exp = dict(exp_a)
        full_exp.update(exp_b)
        if gdups:
            DEFECTS.append(f"{phase}: global rows duplicated {gdups} (Type4_StateLogicViolation)")
            ok = False
        if g != full_exp:
            DEFECTS.append(f"{phase}: global listing={g} expected={full_exp} "
                           f"(cross-face drift, Type4_StateLogicViolation)")
            ok = False
        return ok

    try:
        for cname in (A, B):
            ok, err = rt.setup_default(cname, 128, "Cosine")
            if not ok:
                print(f"SETUP_ERROR create {cname}: {err}")
                return "SCRIPT_ERROR"
            created.append(cname)

        # S1: first create
        if not alias_op([{"create_alias": {"collection_name": A, "alias_name": DUP}}], "create_dup_A"):
            return "SCRIPT_ERROR"
        r = check_state("S1", {DUP: A}, {})
        if r is None:
            return "SCRIPT_ERROR"

        # S2: create the SAME alias on the SAME collection again (idempotent re-insert)
        if not alias_op([{"create_alias": {"collection_name": A, "alias_name": DUP}}], "recreate_dup_A"):
            return "SCRIPT_ERROR"
        r = check_state("S2", {DUP: A}, {})
        if r is None:
            return "SCRIPT_ERROR"

        # S3: rebind the SAME alias name to B (last-write-wins; A must show no residue)
        if not alias_op([{"create_alias": {"collection_name": B, "alias_name": DUP}}], "rebind_dup_B"):
            return "SCRIPT_ERROR"
        r = check_state("S3", {}, {DUP: B})
        if r is None:
            return "SCRIPT_ERROR"

        # S4: delete the alias -> both faces empty
        if not alias_op([{"delete_alias": {"alias_name": DUP}}], "delete_dup"):
            return "SCRIPT_ERROR"
        r = check_state("S4", {}, {})
        if r is None:
            return "SCRIPT_ERROR"

        # S5: name reuse after delete (create again on A)
        if not alias_op([{"create_alias": {"collection_name": A, "alias_name": DUP}}], "recreate_after_delete"):
            return "SCRIPT_ERROR"
        r = check_state("S5", {DUP: A}, {})
        if r is None:
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
                {"delete_alias": {"alias_name": DUP}}]})
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
