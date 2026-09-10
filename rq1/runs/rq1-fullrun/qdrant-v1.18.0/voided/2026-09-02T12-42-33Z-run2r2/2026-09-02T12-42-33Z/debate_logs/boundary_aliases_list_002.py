#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary on the contract-listed query parameter `collection_name` of aliases+list (empty string / numeric string / null-literal / boolean-literal / array-ish / 1e10 / unicode / NUL / overlong 100k / SQL-injection / JSON-injection / existing-other-collection / nonexistent-collection) × qdrant_behavioral_aliases_list_001 (endpoint aliases+list; GET /aliases)
Oracle: GET /aliases is documented as parameterless ("list across all collections"); for every probed collection_name value the endpoint returns either (a) 200 with the full documented envelope intact and the prefix-owned alias still present (param ignored), or (b) a 4xx rejection whose body carries a non-empty error diagnostic; 5xx = Type3_RuntimeFailure, 200 with result.aliases missing/mis-nested = Type4_StateLogicViolation, 200 where the prefix-owned alias of collection c1 silently vanishes because another collection's name was passed = Type1_IllegalSuccess (undocumented filtering breaks "across all collections"), empty-body 4xx = Type2_PoorDiagnostics (constraint qdrant_behavioral_aliases_list_001)
Constraint: qdrant_behavioral_aliases_list_001 (behavioral assertion: "returns 200 with a list of {alias, collection_name} across all collections")
Blindspot: BS-01 Parameter Type Coercion Trust (contract lists collection_name as an openapi mechanical-backfill param on this endpoint; type/shape of its value is untrusted)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collections-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Placement check: contract lists collection_name as a query parameter -> all
probes go through params= (never stuffed into a body; GET has no body params).
R1 lesson applied: envelope nests at result.aliases; ownership by unique prefix.
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
    """Parse a GET /aliases 200 envelope per contract response_shape
    (list nested at result.aliases). Returns (aliases_list, err)."""
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


def find_alias(entries, alias_name):
    for e in entries:
        if isinstance(e, dict) and e.get("alias_name") == alias_name:
            return e
    return None


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
    pfx = "bal2" + tag
    c1 = pfx + "c1"   # carries our alias
    c2 = pfx + "c2"   # exists but carries no alias (filter-probe target)
    alias = pfx + "a1"
    print(f"ownership prefix: {pfx} (c1={c1} with alias, c2={c2} without)")

    # Arrange: two collections, one alias bound to c1
    for name in (c1, c2):
        s, _, raw = safe_request("PUT", f"/collections/{name}",
                                 json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
        if s not in (200, 201, 409):
            print(f"setup create {name} failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
    s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                             json={"actions": [{"create_alias": {
                                 "collection_name": c1, "alias_name": alias}}]}, timeout=60)
    print(f"create alias status={s} raw={raw[:300]}")
    if s != 200:
        print("VERDICT: SCRIPT_ERROR — alias setup failed, no defect conclusion")
        return

    try:
        # Baseline: without any param the prefix-owned alias must be listed
        s0, _, raw0 = safe_request("GET", "/aliases", timeout=30)
        if s0 <= 0:
            hs, hraw = liveness()
            print(f"transport failure on baseline GET (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s0 != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — baseline GET /aliases "
                  f"returned {s0} (promise: 200 with list)")
            return
        entries0, err0 = parse_alias_envelope(raw0)
        if err0 == "non_json":
            print(f"VERDICT: SCRIPT_ERROR — 200 but body not usable JSON: {raw0[:300]}")
            return
        if err0 is not None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — baseline envelope "
                  f"violates response_shape ({err0})")
            return
        if find_alias(entries0, alias) is None:
            print("VERDICT: SCRIPT_ERROR — baseline list lacks our alias; setup inconsistent")
            return
        print(f"OK: baseline lists {alias} -> {c1}")

        # Act: type/shape-confusion probes on the query parameter
        probes = [
            ("empty-string", ""),
            ("numeric-zero", "0"),
            ("numeric-negative", "-1"),
            ("null-literal", "null"),
            ("boolean-literal", "true"),
            ("array-ish", "[]"),
            ("object-ish", "{}"),
            ("huge-float", "1e10"),
            ("unicode", pfx + "-中文🎯"),
            ("nul-byte", "a\x00b"),
            ("overlong-100k", "a" * 100000),
            ("sql-injection", "'; DROP TABLE aliases--"),
            ("json-injection", '{"$gt": ""}'),
            ("other-existing-collection", c2),
            ("nonexistent-collection", pfx + "nope"),
        ]
        for label, value in probes:
            shown = value if len(value) <= 40 else value[:37] + "..."
            s, _, raw = safe_request("GET", "/aliases",
                                     params={"collection_name": value}, timeout=30)
            print(f"probe[{label}] value={shown!r} -> status={s}")
            print(f"  raw: {raw[:300]}")
            if s <= 0:
                hs, hraw = liveness()
                print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
                return
            if 500 <= s <= 599:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — collection_name="
                      f"{shown!r} ({label}) triggered {s} on a documented-200 GET")
                return
            if 400 <= s <= 499:
                if not raw.strip():
                    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — collection_name="
                          f"{shown!r} ({label}) rejected with {s} but empty diagnostic body")
                    return
                print(f"  OK: rejected {s} with non-empty diagnostics")
                continue
            if s != 200:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — unexpected status "
                      f"{s} for collection_name={shown!r} ({label})")
                return
            entries, err = parse_alias_envelope(raw)
            if err == "non_json":
                print(f"VERDICT: SCRIPT_ERROR — 200 but body not usable JSON: {raw[:300]}")
                return
            if err is not None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 with "
                      f"collection_name={shown!r} ({label}) corrupted the envelope ({err}); "
                      f"promise: result.aliases array of {{alias, collection_name}}")
                return
            hit = find_alias(entries, alias)
            if hit is None:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — undocumented "
                      f"parameter took effect: collection_name={shown!r} ({label}) "
                      f"silently filtered the 'across all collections' list and dropped "
                      f"alias {alias} of {c1}")
                return
            if hit.get("collection_name") != c1:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias binding "
                      f"altered under collection_name={shown!r} ({label}): "
                      f"{json.dumps(hit, ensure_ascii=False)[:200]}")
                return
            print(f"  OK: 200, envelope intact, {alias} still listed -> {c1}")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            delete_alias(alias)
        except Exception:
            pass  # cleanup failures are non-fatal
        try:
            drop_collection(c1)
        except Exception:
            pass  # cleanup failures are non-fatal
        try:
            drop_collection(c2)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
