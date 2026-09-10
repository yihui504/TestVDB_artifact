#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value state closure on aliases+list (the {alias, collection_name} list must close back to the 0 side after (a) delete_alias of a listed alias and (b) DELETE of the backing collection — no stale or dangling pairs remain) × qdrant_behavioral_aliases_list_001 (endpoint aliases+list; GET /aliases)
Oracle: after delete_alias returns 200, GET /aliases returns 200 with the deleted alias absent from result.aliases (still listed = Type4_StateLogicViolation stale entry); after DELETE /collections/{c2} returns 200, GET /aliases returns 200 with no prefix-owned entry whose collection_name equals the dropped collection (dangling binding served = Type4_StateLogicViolation — a pair referencing a non-existent collection cannot be "across all collections"); 5xx on any legal GET = Type3; envelope nests at result.aliases per response_shape (constraint qdrant_behavioral_aliases_list_001)
Constraint: qdrant_behavioral_aliases_list_001 (behavioral assertion: "returns 200 with a list of {alias, collection_name} across all collections")
Blindspot: BS-04 Boundary Default Optimism (list assumed to track alias/collection lifecycle back to the 0-side boundary)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collections-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R1 context: the per-collection face (GET /collections/{name}/aliases) was
confirmed to lack collection-existence checks; this script probes the GLOBAL
face's counterpart — whether it keeps serving pairs whose backing collection
no longer exists. Ownership is decided by a per-script unique prefix.
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


def owned_entries(entries, prefix):
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


def get_owned_or_defect(prefix):
    """GET /aliases and return prefix-owned entries, printing a VERDICT and
    returning None when the response itself violates the promise."""
    s, _, raw = safe_request("GET", "/aliases", timeout=30)
    print(f"GET /aliases -> status={s}")
    print(f"raw: {raw[:600]}")
    if s <= 0:
        hs, hraw = liveness()
        print(f"transport failure on GET (healthz status={hs}: {str(hraw)[:200]})")
        print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
        return None
    if 500 <= s <= 599:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — legal GET /aliases "
              f"returned {s} instead of 200")
        return None
    if s != 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal GET /aliases "
              f"wrongly rejected with {s} (promise: 200 with list)")
        return None
    entries, err = parse_alias_envelope(raw)
    if err == "non_json":
        print(f"VERDICT: SCRIPT_ERROR — 200 but body not usable JSON: {raw[:300]}")
        return None
    if err is not None:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 envelope "
              f"violates response_shape ({err}); promise: result.aliases array of "
              f"{{alias, collection_name}}")
        return None
    return owned_entries(entries, prefix)


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bal5" + tag
    c1 = pfx + "c1"
    c2 = pfx + "c2"
    a1 = pfx + "a1"   # will be removed via delete_alias
    a2 = pfx + "a2"   # will be left dangling via DELETE of its backing collection
    print(f"ownership prefix: {pfx} (c1={c1}, c2={c2}, a1={a1}, a2={a2})")

    # Arrange: two collections, alias a1->c1 and a2->c2
    for name in (c1, c2):
        s, _, raw = safe_request("PUT", f"/collections/{name}",
                                 json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
        if s not in (200, 201, 409):
            print(f"setup create {name} failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
    for alias, coll in ((a1, c1), (a2, c2)):
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [{"create_alias": {
                                     "collection_name": coll, "alias_name": alias}}]},
                                 timeout=60)
        print(f"create alias {alias} -> {coll}: status={s} raw={raw[:200]}")
        if s != 200:
            print("VERDICT: SCRIPT_ERROR — alias setup failed, no defect conclusion")
            return

    try:
        # Precondition: both prefix-owned pairs are listed
        mine = get_owned_or_defect(pfx)
        if mine is None:
            return
        names = {e.get("alias_name") for e in mine}
        if a1 not in names or a2 not in names:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — freshly created "
                  f"aliases missing from the global list: have {json.dumps(mine, ensure_ascii=False)[:300]}")
            return
        print(f"OK: both pairs listed ({a1}->{c1}, {a2}->{c2})")

        # Act 1: delete a1 on the write face, then the list must close back to 0 for a1
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [{"delete_alias": {"alias_name": a1}}]},
                                 timeout=60)
        print(f"delete_alias {a1}: status={s} raw={raw[:200]}")
        if s != 200:
            print("VERDICT: SCRIPT_ERROR — delete_alias setup failed, no defect conclusion")
            return
        mine = get_owned_or_defect(pfx)
        if mine is None:
            return
        if any(e.get("alias_name") == a1 for e in mine):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias {a1} still "
                  f"listed by GET /aliases after a 200 delete_alias (stale entry; the list "
                  f"did not close back to the 0 side)")
            return
        if not any(e.get("alias_name") == a2 for e in mine):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — unrelated alias "
                  f"{a2} disappeared while deleting {a1}: "
                  f"{json.dumps(mine, ensure_ascii=False)[:300]}")
            return
        print(f"OK: {a1} gone after delete_alias; {a2} unaffected")

        # Act 2: drop c2 (a2's backing collection); the list must not keep serving
        # an {alias, collection_name} pair whose collection no longer exists
        s, _, raw = safe_request("DELETE", f"/collections/{c2}", params={"timeout": 60},
                                 timeout=60)
        print(f"DELETE /collections/{c2}: status={s} raw={raw[:200]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"transport failure on DELETE (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s not in (200, 404):
            print(f"VERDICT: SCRIPT_ERROR — unexpected {s} dropping {c2}, no defect conclusion")
            return
        mine = get_owned_or_defect(pfx)
        if mine is None:
            return
        dangling = [e for e in mine if e.get("collection_name") == c2]
        if dangling:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — GET /aliases keeps "
                  f"serving {json.dumps(dangling, ensure_ascii=False)[:300]} although "
                  f"collection {c2} no longer exists (dangling binding; the promise is a "
                  f"list across all collections, and {c2} is not among them)")
            return
        if any(e.get("alias_name") == a2 for e in mine):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias {a2} still "
                  f"listed after its backing collection {c2} was dropped: "
                  f"{json.dumps(mine, ensure_ascii=False)[:300]}")
            return
        print(f"OK: no dangling pair for dropped collection {c2}")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            delete_alias(a1)
        except Exception:
            pass  # cleanup failures are non-fatal
        try:
            delete_alias(a2)
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
