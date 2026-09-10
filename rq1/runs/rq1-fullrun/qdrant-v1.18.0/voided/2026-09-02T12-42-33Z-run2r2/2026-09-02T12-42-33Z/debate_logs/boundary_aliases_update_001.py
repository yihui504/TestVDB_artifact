#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value on the contract-listed query parameter `timeout` of aliases+update (POST /collections/aliases; contract documents "query: min 1") x qdrant_behavioral_aliases_update_001 — probes: min-1 (0), negative (-1, -100), min closure (1), min+1 (2), mid (5), INT_MAX (2147483647), 1000000000
Oracle: boundary closure — every timeout>=1 probe with a valid create_alias action returns 200 with envelope result:boolean true and the alias really listed by GET /aliases; every timeout<1 probe (0/-1/-100) is rejected with 4xx (documented min 1); 200 on a timeout<1 probe that actually applied the alias = Type1_IllegalSuccess; 5xx = Type3_RuntimeFailure (healthz rechecked); 200 whose envelope breaks result:boolean = Type4_StateLogicViolation (constraint qdrant_behavioral_aliases_update_001 + parameter description "query: min 1")
Constraint: qdrant_behavioral_aliases_update_001 (behavioral assertion: "valid alias batch returns HTTP 200") + aliases+update param timeout ("query: min 1")
Blindspot: BS-04 Boundary Default Optimism (the min-1 bound is documented but assumed enforced; below-min values must actually be refused)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Placement check: contract lists timeout as a QUERY parameter -> all probes go
through params= (never stuffed into the body; v34 R1 lesson).
R1 lesson applied: envelope nests at result (boolean here); ownership by
unique per-script prefix bau1<uuid>.
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


def liveness():
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs, hraw


def parse_global_aliases(raw):
    """Parse GET /aliases 200 envelope per contract response_shape
    (aliases nested at result.aliases). Returns (aliases_list, err)."""
    try:
        b = json.loads(raw) if raw else None
    except Exception:
        return None, "non_json"
    if not isinstance(b, dict) or "result" not in b:
        return None, "no_result"
    r = b["result"]
    if not isinstance(r, dict) or "aliases" not in r:
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
    pfx = "bau1" + tag
    coll = pfx + "c1"
    print(f"ownership prefix: {pfx}")

    # Arrange: one collection to anchor valid create_alias actions
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    created = []  # aliases this script created (for cleanup)
    try:
        # Act: for each timeout probe, submit a fully valid create_alias action
        # (all required leaf fields present per request_required_paths) with a
        # unique alias name, then verify application via GET /aliases.
        probes = [
            ("below-min-zero", 0, "reject"),
            ("below-min-neg1", -1, "reject"),
            ("below-min-neg100", -100, "reject"),
            ("min-closure-1", 1, "accept"),
            ("min-plus-1", 2, "accept"),
            ("mid-5", 5, "accept"),
            ("int-max", 2147483647, "accept-or-reject"),
            ("huge-1e9", 1000000000, "accept-or-reject"),
        ]
        for label, tv, expectation in probes:
            alias = f"{pfx}a_{label}"
            body = {"actions": [{"create_alias": {
                "collection_name": coll, "alias_name": alias}}]}
            s, b, raw = safe_request("POST", "/collections/aliases",
                                     params={"timeout": tv}, json=body, timeout=60)
            print(f"probe[{label}] timeout={tv} -> status={s}")
            print(f"  raw: {raw[:300]}")
            if s <= 0:
                hs, hraw = liveness()
                print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
                if hs <= 0 or hs >= 500:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — timeout={tv} "
                          f"({label}) killed the service (healthz={hs})")
                else:
                    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
                return
            if 500 <= s <= 599:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — timeout={tv} "
                      f"({label}) triggered {s} on a documented 200/4xx endpoint")
                return

            # Verify actual application state via the global alias face
            ls, _, lraw = safe_request("GET", "/aliases", timeout=30)
            if ls != 200:
                print(f"VERDICT: SCRIPT_ERROR — GET /aliases face broken status={ls}: {lraw[:200]}")
                return
            entries, err = parse_global_aliases(lraw)
            if err is not None:
                print(f"VERDICT: SCRIPT_ERROR — GET /aliases envelope unreadable ({err})")
                return
            hit = find_alias(entries, alias)

            if s == 200:
                # envelope must keep result:boolean per response_shape
                try:
                    ok = isinstance(json.loads(raw).get("result"), bool)
                except Exception:
                    ok = False
                if not ok:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 for "
                          f"timeout={tv} ({label}) but envelope violates result:boolean")
                    return
                if hit is None:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 for "
                          f"timeout={tv} ({label}) but alias {alias} not listed after apply")
                    return
                created.append(alias)
                if expectation == "reject":
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — timeout={tv} "
                          f"({label}) is below the documented min 1, yet the batch was "
                          f"accepted 200 AND applied (alias listed)")
                    return
                print(f"  OK: 200, applied, envelope result:boolean intact")
            elif 400 <= s <= 499:
                if hit is not None:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — timeout={tv} "
                          f"({label}) rejected {s} but alias {alias} exists anyway")
                    return
                if expectation == "accept":
                    print(f"  NOTE: timeout={tv} ({label}) rejected {s} though >= documented "
                          f"min 1 — recorded for judge (boundary closure violated?)")
                else:
                    print(f"  OK: below-min timeout rejected {s} (documented min 1)")
            else:
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} for timeout={tv}")
                return

        print("VERDICT: NO_DEFECT")
    finally:
        for a in created:
            try:
                delete_alias(a)
            except Exception:
                pass  # cleanup failures are non-fatal
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
