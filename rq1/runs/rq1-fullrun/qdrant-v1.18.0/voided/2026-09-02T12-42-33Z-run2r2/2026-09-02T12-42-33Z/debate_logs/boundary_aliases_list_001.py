#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value (global alias-list size closure {0,1} under a unique ownership prefix) + response_shape conformance × qdrant_behavioral_aliases_list_001 (endpoint aliases+list; GET /aliases)
Oracle: existing collection with exactly 1 prefix-owned alias -> GET /aliases returns HTTP 200 and result.aliases (nested object->array per response_shape) contains exactly one entry {alias_name=<alias>, collection_name=<collection>} with both fields strings; before creation the prefix-owned count is 0 (closure of the 0 side); 5xx = Type3, non-200 on the legal GET = Type1, 200 with missing/mis-nested/malformed result.aliases = Type4 (constraint qdrant_behavioral_aliases_list_001)
Constraint: qdrant_behavioral_aliases_list_001 (behavioral assertion: "returns 200 with a list of {alias, collection_name} across all collections")
Blindspot: BS-04 Boundary Default Optimism (list-size boundary 0 vs 1 on the global face)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collections-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R1 lesson applied: the qdrant REST envelope nests the list at result.<field>
(result.aliases), NOT a bare result list; adjudication reads result.aliases.
Global-face oracle tolerates concurrent sibling scripts: ownership is decided
by a per-script unique prefix, never by absolute list length.
"""

import json
import os
import sys
import uuid
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap: three-layer fallback (env -> upward walk -> contract target) ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    _root = Path(__file__).resolve()
    for _p in (_root, *list(_root.parents)):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or TARGET != "qdrant":
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)


def safe_request(method, endpoint, json=None, params=None, data=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, params=params,
            data=data, headers=headers, timeout=timeout,
        )
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except Exception:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def parse_alias_envelope(raw):
    """Parse a GET /aliases 200 envelope per contract response_shape.

    result must be an object carrying an `aliases` array (R1 lesson: the list
    is nested at result.aliases, not a bare result list).
    Returns (aliases_list, err) with err in:
    None | non_json | no_result | bad_result_type | no_aliases | bad_aliases_type
    """
    try:
        b = json.loads(raw) if raw else None
    except Exception:
        return None, "non_json"
    if not isinstance(b, dict):
        return None, "non_json"
    if "result" not in b:
        return None, "no_result"
    r = b["result"]
    if not isinstance(r, dict):
        return None, "bad_result_type"
    if "aliases" not in r:
        return None, "no_aliases"
    a = r["aliases"]
    if not isinstance(a, list):
        return None, "bad_aliases_type"
    return a, None


def shape_violations(entries):
    """Deterministic per-entry response_shape check: every entry is an object
    with string alias_name and string collection_name."""
    v = []
    for e in entries:
        if not isinstance(e, dict):
            v.append("non-object entry: " + json.dumps(e, ensure_ascii=False)[:80])
            continue
        an, cn = e.get("alias_name"), e.get("collection_name")
        if not isinstance(an, str):
            v.append("alias_name not a string: " + repr(an)[:80])
        if not isinstance(cn, str):
            v.append("collection_name not a string: " + repr(cn)[:80])
    return v


def owned_entries(entries, prefix):
    """Entries whose alias_name carries this script's unique prefix
    (concurrency-tolerant ownership filter)."""
    out = []
    for e in entries:
        if isinstance(e, dict) and isinstance(e.get("alias_name"), str) \
                and e["alias_name"].startswith(prefix):
            out.append(e)
    return out


def liveness():
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs, hraw


def drop_collection(name):
    try:
        safe_request("DELETE", f"/collections/{name}", params={"timeout": 60}, timeout=60)
    except Exception:
        pass  # cleanup failures are non-fatal


def delete_alias(name):
    try:
        safe_request("POST", "/collections/aliases", params={"timeout": 60},
                     json={"actions": [{"delete_alias": {"alias_name": name}}]}, timeout=60)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bal1" + tag
    coll = pfx + "c1"
    alias = pfx + "a1"
    print(f"ownership prefix: {pfx} (collection={coll}, alias={alias})")

    # Arrange: one existing collection (unique name; sandbox is cleaned between
    # rounds but 409 is tolerated defensively for crashed prior runs)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201, 409):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # Act 1 (closure, 0 side): list aliases BEFORE any prefix-owned alias exists
        s1, _, raw1 = safe_request("GET", "/aliases", timeout=30)
        print(f"GET /aliases (pre-create) -> status={s1}")
        print(f"raw: {raw1[:600]}")
        if s1 <= 0:
            hs, hraw = liveness()
            print(f"transport failure on GET (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s1 <= 599:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — legal GET /aliases "
                  f"on a live deployment returned {s1} instead of 200")
            return
        if s1 != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal GET /aliases "
                  f"wrongly rejected with {s1} (promise: 200 with list)")
            return
        entries1, err1 = parse_alias_envelope(raw1)
        if err1 == "non_json":
            print(f"VERDICT: SCRIPT_ERROR — 200 but body not usable JSON: {raw1[:300]}")
            return
        if err1 is not None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 envelope "
                  f"violates response_shape ({err1}); promise: result.aliases array of "
                  f"{{alias, collection_name}}")
            return
        bad = shape_violations(entries1)
        if bad:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — malformed "
                  f"entries in result.aliases: {bad[:3]}")
            return
        pre = owned_entries(entries1, pfx)
        if len(pre) != 0:
            print(f"VERDICT: SCRIPT_ERROR — prefix collision, expected 0 owned "
                  f"entries before creation, found {len(pre)}")
            return
        print("OK: 0-side closure — prefix-owned count is 0 before alias creation")

        # Arrange 2: bind alias -> coll (list must then be non-empty for us)
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [{"create_alias": {
                                     "collection_name": coll, "alias_name": alias}}]},
                                 timeout=60)
        print(f"create alias status={s} raw={raw[:300]}")
        if s != 200:
            print("VERDICT: SCRIPT_ERROR — alias setup failed, no defect conclusion")
            return

        # Act 2 (closure, 1 side): the global list must carry exactly our pair
        s2, _, raw2 = safe_request("GET", "/aliases", timeout=30)
        print(f"GET /aliases (post-create) -> status={s2}")
        print(f"raw: {raw2[:600]}")
        if s2 <= 0:
            hs, hraw = liveness()
            print(f"transport failure on GET (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s2 <= 599:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — legal GET /aliases "
                  f"after alias creation returned {s2} instead of 200")
            return
        if s2 != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal GET /aliases "
                  f"wrongly rejected with {s2} (promise: 200 with list)")
            return
        entries2, err2 = parse_alias_envelope(raw2)
        if err2 == "non_json":
            print(f"VERDICT: SCRIPT_ERROR — 200 but body not usable JSON: {raw2[:300]}")
            return
        if err2 is not None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 envelope "
                  f"violates response_shape ({err2}); promise: result.aliases array of "
                  f"{{alias, collection_name}}")
            return
        bad2 = shape_violations(entries2)
        if bad2:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — malformed "
                  f"entries in result.aliases: {bad2[:3]}")
            return
        mine = owned_entries(entries2, pfx)
        if len(mine) == 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — created alias "
                  f"{alias} bound to {coll} is NOT listed by GET /aliases (promise: "
                  f"list of {{alias, collection_name}} across all collections)")
            return
        if len(mine) > 1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias "
                  f"duplicated in global list ({len(mine)} prefix-owned entries): "
                  f"{json.dumps(mine, ensure_ascii=False)[:300]}")
            return
        e = mine[0]
        if e.get("alias_name") != alias or e.get("collection_name") != coll:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — listed pair "
                  f"mismatches the created binding: {json.dumps(e, ensure_ascii=False)} "
                  f"(expected alias_name={alias}, collection_name={coll})")
            return
        print(f"OK: 1-side closure — exactly one prefix-owned pair "
              f"{{alias_name={alias}, collection_name={coll}}} listed")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            delete_alias(alias)
        except Exception:
            pass  # cleanup failures are non-fatal
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
