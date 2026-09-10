#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_aliases_collection_list_001
# strategy: delete_consistency
# endpoint: aliases+collection+list
# constraint_ids: qdrant_behavioral_aliases_collection_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collection-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (post-delete state residue on the per-collection alias listing face)
"""
Attack: delete/post-delete consistency x qdrant_behavioral_aliases_collection_list_001
  (unknown-collection branch, both instantiations: never-created collection AND
  collection dropped via DELETE; sibling-face controls describe/count -> 404)
Oracle: unknown (never-created or dropped) collection -> HTTP 404 expected on GET /collections/{name}/aliases; existing collection -> HTTP 200 with exactly its bound aliases
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

import requests  # noqa: E402  (used only by the fallback face below)

_FB_PRINTED = [False]


def _fallback_markers():
    if _FB_PRINTED[0]:
        return
    _FB_PRINTED[0] = True
    print("FALLBACK_TRIGGERED: per-collection alias listing (aliases+collection+list) has no qdrant runtime PATHS key; issuing the contract-derived REST path GET /collections/{collection_name}/aliases via requests")
    print("[FALLBACK_JUSTIFIED: scripts/runtime/qdrant.py PATHS exposes only update_aliases (POST /collections/aliases) and list_aliases (GET /aliases); the chunk unit endpoint aliases+collection+list (contract api_endpoints: method GET, required path parameter collection_name, source_url slug get-collection-aliases) is NOT reachable through the rt.request path_key whitelist, and the sibling list_aliases face cannot express the unit's per-collection 404 branch; the REST route is derived 1:1 from the contract endpoint (raw_knowledge.json document_sources 0-12, v-1-18-x api-reference) and its response shape was confirmed by prior live sessions (200 {\"result\":{\"aliases\":[...]}})]")


def collection_aliases_http(coll):
    """FALLBACK face: GET /collections/{collection_name}/aliases -> (status, raw_text).

    Mirrors rt.request's 2-tuple so the rest of the script stays uniform.
    """
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
    """result.aliases[] -> (dict alias_name->collection_name, dups list). None = unparsable/wrong shape."""
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
    A = "salc_del_a_" + TS
    NEVER = "salc_del_never_created_" + TS
    AL1 = "salc_del_al1_" + TS
    AL2 = "salc_del_al2_" + TS
    DEFECTS = []
    created = []

    try:
        # ---- setup ----
        ok, err = rt.setup_default(A, 128, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {A}: {err}")
            return "SCRIPT_ERROR"
        created.append(A)

        s, raw = rt.request("POST", "update_aliases", {"actions": [
            {"create_alias": {"collection_name": A, "alias_name": AL1}},
            {"create_alias": {"collection_name": A, "alias_name": AL2}},
        ]})
        print(f"seed_alias_batch status={s} raw={raw}")
        if not expect_2xx(s):
            print(f"SETUP_ERROR alias seed failed: {s} {raw[:200]}")
            return "SCRIPT_ERROR"

        # ---- positive control: existing collection lists exactly its aliases ----
        ps, praw = collection_aliases_http(A)
        print(f"[positive:existing] status={ps} raw={praw}")
        if not expect_2xx(ps):
            # If the fallback path itself is wrong (e.g. 404), both faces would lie;
            # without a working positive face the negative claim is not measurable.
            print(f"POSITIVE_FACE_FAILED status={ps} — fallback probe path unverified")
            return "SCRIPT_ERROR"
        pmap = parse_aliases(praw)
        if pmap is None:
            print(f"POSITIVE_FACE_UNPARSEABLE raw={praw[:200]}")
            return "SCRIPT_ERROR"
        pmap, pdups = pmap
        if pdups or set(pmap) != {AL1, AL2} or any(pmap[x] != A for x in pmap):
            DEFECTS.append(f"positive: listing of existing {A} = {pmap} (dups={pdups}) expected {{{AL1}:{A}, {AL2}:{A}}}")
        else:
            print(f"positive control OK: {A} lists {sorted(pmap)}")

        # ---- NEG-1: collection that never existed ----
        # control: schema face confirms the name is unknown (404)
        cs, craw = rt.request("GET", "describe_collection", path_params={"name": NEVER})
        print(f"[control:describe never-created] status={cs} raw={craw[:160]}")
        if cs != 404:
            print(f"CONTROL_ANOMALY describe of never-created returned {cs} — cannot establish 'unknown'")
            return "SCRIPT_ERROR"
        ns, nraw = collection_aliases_http(NEVER)
        print(f"[NEG-1:never-created] status={ns} raw={nraw}")
        if ns != 404:
            DEFECTS.append(
                f"NEG-1: aliases listing of never-created collection returned {ns} (expected 404 per unit assertion) "
                f"— Type4_StateLogicViolation raw={nraw[:200]}"
            )

        # ---- NEG-2: collection dropped via DELETE (aliases cascade-removed) ----
        ds, draw = rt.request("DELETE", "drop_collection", path_params={"name": A})
        print(f"drop status={ds} raw={draw}")
        if not expect_2xx(ds):
            print(f"SETUP_ERROR drop {A}: {ds} {draw[:200]}")
            return "SCRIPT_ERROR"
        cs2, craw2 = rt.request("GET", "describe_collection", path_params={"name": A})
        print(f"[control:describe dropped] status={cs2} raw={craw2[:160]}")
        if cs2 != 404:
            print(f"CONTROL_ANOMALY describe of dropped collection returned {cs2}")
            return "SCRIPT_ERROR"
        # sibling data-plane face on the same unknown collection (G9 disposition check)
        ks, kraw = rt.request("POST", "count", {"exact": True}, path_params={"name": A})
        print(f"[sibling:count dropped] status={ks} raw={kraw[:160]}")
        gs, graw = collection_aliases_http(A)
        print(f"[NEG-2:dropped] status={gs} raw={graw}")
        if gs != 404:
            DEFECTS.append(
                f"NEG-2: aliases listing of dropped collection returned {gs} (expected 404 per unit assertion); "
                f"sibling faces describe/count on the same name return {cs2}/{ks} — face asymmetry "
                f"— Type4_StateLogicViolation raw={graw[:200]}"
            )

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
        # best-effort alias cleanup (cascade normally covers it)
        try:
            rt.request("POST", "update_aliases", {"actions": [
                {"delete_alias": {"alias_name": AL1}},
                {"delete_alias": {"alias_name": AL2}},
            ]})
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
