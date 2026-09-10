#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value (alias-list size closure {0,1}) × qdrant_behavioral_aliases_collection_list_001 (endpoint aliases+collection+list; GET /collections/{collection_name}/aliases)
Oracle: existing collection with exactly 1 alias → GET returns 200 and its result list contains that alias bound to collection_name; existing collection with 0 aliases → GET returns 200 with an empty result list (both branches of the list-size boundary are accepted)
Constraint: qdrant_behavioral_aliases_collection_list_001 (behavioral assertion: "returns 200 with a list of {alias, collection_name}; 404 for an unknown collection")
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collection-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)
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


def safe_request(method, endpoint, json=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.request(
            method=method,
            url=url,
            json=json,
            headers=headers,
            timeout=timeout
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


def _result_list(raw):
    """Extract the alias list from a qdrant 200 envelope.

    Returns (records, parsed_ok): parsed_ok=False means non-JSON/unusable body;
    records=None means parsed but no 'result' list found.
    """
    try:
        b = json.loads(raw) if raw else {}
    except Exception:
        return None, False
    if not isinstance(b, dict):
        return None, False
    r = b.get("result")
    if isinstance(r, list):
        return r, True
    return None, True


def has_alias_entry(entries, collection, alias):
    """True if entries contain {collection_name: collection} + alias under alias_name or alias key."""
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("collection_name") != collection:
            continue
        for k in ("alias_name", "alias"):
            if e.get(k) == alias:
                return True
    return False


def drop_collection(name):
    try:
        safe_request("DELETE", f"/collections/{name}", timeout=30)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    tag = uuid.uuid4().hex[:8]
    c1 = "bacl1c1" + tag          # collection WITH one alias
    c2 = "bacl1c2" + tag          # collection WITHOUT any alias
    alias = "bacl1al" + tag
    print(f"collections under test: {c1} (1 alias), {c2} (0 aliases)")

    # Arrange: two existing collections (valid 200-branch per assertion)
    s, _, raw = safe_request("PUT", f"/collections/{c1}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201, 409):
        print(f"setup create {c1} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request("PUT", f"/collections/{c2}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201, 409):
        print(f"setup create {c2} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # Arrange: bind alias -> c1 (the {alias, collection_name} list may not be empty on c1)
        s, _, raw = safe_request("POST", "/collections/aliases",
                                 json={"actions": [{"create_alias": {
                                     "collection_name": c1, "alias_name": alias}}]}, timeout=60)
        print(f"create alias status={s} raw={raw[:300]}")
        if s != 200:
            print("VERDICT: SCRIPT_ERROR — alias setup failed, no defect conclusion")
            return

        # Act: list aliases of c1 (promise: 200 with the alias listed)
        s1, _, raw1 = safe_request("GET", f"/collections/{c1}/aliases", timeout=30)
        print(f"GET /collections/{c1}/aliases -> status={s1}")
        print(f"raw: {raw1[:600]}")

        # Assert (branch 1: 1-alias collection)
        if s1 <= 0:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"transport failure on GET (healthz status={hs}: {hraw[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s1 <= 599:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — legal GET on existing "
                  f"collection returned {s1} instead of 200")
            return
        if s1 in (400, 422, 404):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal GET on existing "
                  f"collection with 1 alias wrongly rejected with {s1} (promise: 200 with list)")
            return
        if s1 != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal GET on existing "
                  f"collection returned unexpected status {s1} (promise: 200 with list)")
            return
        entries1, ok1 = _result_list(raw1)
        if not ok1:
            print(f"VERDICT: SCRIPT_ERROR — 200 but response body not usable JSON: {raw1[:300]}")
            return
        if entries1 is None:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 without the "
                  "documented result list of {alias, collection_name}")
            return
        if len(entries1) == 0:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — created alias not "
                  "listed for its collection (promise: list of {alias, collection_name})")
            return
        if not has_alias_entry(entries1, c1, alias):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias {alias} of "
                  f"{c1} missing from the listed entries: {json.dumps(entries1)[:300]}")
            return
        print(f"OK: alias {alias} listed for {c1} with collection_name (1-alias branch)")

        # Act: list aliases of c2 (promise: 200 with empty list — 0 is a legal list size)
        s2, _, raw2 = safe_request("GET", f"/collections/{c2}/aliases", timeout=30)
        print(f"GET /collections/{c2}/aliases -> status={s2}")
        print(f"raw: {raw2[:600]}")

        # Assert (branch 2: 0-alias collection)
        if s2 <= 0:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"transport failure on GET (healthz status={hs}: {hraw[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s2 <= 599:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — legal GET on existing "
                  f"alias-free collection returned {s2} instead of 200")
            return
        if s2 != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal GET on existing "
                  f"alias-free collection wrongly rejected with {s2} (promise: 200 with list)")
            return
        entries2, ok2 = _result_list(raw2)
        if not ok2:
            print(f"VERDICT: SCRIPT_ERROR — 200 but response body not usable JSON: {raw2[:300]}")
            return
        if entries2 is None:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 without the "
                  "documented result list of {alias, collection_name}")
            return
        if len(entries2) != 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias-free collection "
                  f"{c2} listed {len(entries2)} aliases (cross-collection leak or stale alias): "
                  f"{json.dumps(entries2)[:300]}")
            return
        print("OK: alias-free collection returned an empty result list (0-alias branch)")

        print("VERDICT: NO_DEFECT")
    finally:
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
