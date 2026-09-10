#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy4 special-value readback fidelity on the aliases+list face (alias names carrying unicode 中文🎯 / JSON-injection {"$gt":""} / SQL-injection '; DROP TABLE-- / ~8KB overlong string / a name identical to another existing collection's name, all created via the aliases+update write face and then read back through GET /aliases) × qdrant_behavioral_aliases_list_001 (endpoint aliases+list; GET /aliases)
Oracle: for every alias name whose creation the write face accepted with 200, GET /aliases returns HTTP 200 and result.aliases contains exactly one entry with byte-exact alias_name equal to the created name and collection_name equal to the backing collection (dropped/mangled/wrongly-bound entry = Type4_StateLogicViolation); 5xx on the list = Type3; creation-side 4xx rejections are recorded and skipped (that is the write face's validation, not this unit); envelope nests at result.aliases per response_shape (constraint qdrant_behavioral_aliases_list_001)
Constraint: qdrant_behavioral_aliases_list_001 (behavioral assertion: "returns 200 with a list of {alias, collection_name} across all collections")
Blindspot: BS-04 Boundary Default Optimism (readback path assumed faithful for boundary-character names)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collections-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

The unit under attack is the LIST face: the write face (aliases+update) is
setup only, and a conditional oracle keeps the adjudication anchored here.
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


def find_by_alias(entries, alias_name):
    """All entries whose alias_name equals the requested string (byte-exact)."""
    return [e for e in entries
            if isinstance(e, dict) and e.get("alias_name") == alias_name]


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
    pfx = "bal4" + tag
    c1 = pfx + "c1"   # backing collection for all special-named aliases
    c2 = pfx + "c2"   # its NAME doubles as one probe alias name (namespace collision edge)
    print(f"ownership prefix: {pfx} (backing={c1}, name-collision-collection={c2})")

    for name in (c1, c2):
        s, _, raw = safe_request("PUT", f"/collections/{name}",
                                 json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
        if s not in (200, 201, 409):
            print(f"setup create {name} failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

    probes = [
        ("unicode", pfx + "-中文🎯-alias"),
        ("json-injection", pfx + '-{"$gt": ""}'),
        ("sql-injection", pfx + "-'; DROP TABLE aliases--"),
        ("overlong-8k", pfx + "-" + "a" * 8000),
        ("alias-equals-collection-name", c2),
    ]

    accepted = []   # (label, alias_name) that the write face accepted with 200
    rejected = []   # (label, status) rejected at creation — write-face behavior, not this unit
    try:
        # Arrange: attempt to create every special-named alias bound to c1
        for label, name in probes:
            s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                     json={"actions": [{"create_alias": {
                                         "collection_name": c1, "alias_name": name}}]},
                                     timeout=60)
            shown = name if len(name) <= 40 else name[:37] + "..."
            print(f"create[{label}] name={shown!r} -> status={s} raw={raw[:200]}")
            if s == 200:
                accepted.append((label, name))
            elif 400 <= s <= 499:
                rejected.append((label, s))
                print(f"  note: write face rejected [{label}] with {s} — recorded, not adjudicated here")
            else:
                print(f"VERDICT: SCRIPT_ERROR — alias setup for [{label}] returned "
                      f"unexpected {s}, no defect conclusion")
                return
        if not accepted:
            print("VERDICT: SCRIPT_ERROR — no special-named alias was accepted; "
                  "nothing to read back on the list face")
            return

        # Act: read the global list back
        s, _, raw = safe_request("GET", "/aliases", timeout=30)
        print(f"GET /aliases -> status={s}")
        print(f"raw: {raw[:800]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"transport failure on GET (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — legal GET /aliases "
                  f"with special-named aliases stored returned {s}")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — legal GET /aliases "
                  f"wrongly rejected with {s} (promise: 200 with list)")
            return
        entries, err = parse_alias_envelope(raw)
        if err == "non_json":
            print(f"VERDICT: SCRIPT_ERROR — 200 but body not usable JSON: {raw[:300]}")
            return
        if err is not None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 envelope "
                  f"violates response_shape ({err}); promise: result.aliases array of "
                  f"{{alias, collection_name}}")
            return

        # Assert: every accepted alias must appear byte-exact and bound to c1
        for label, name in accepted:
            shown = name if len(name) <= 40 else name[:37] + "..."
            hits = find_by_alias(entries, name)
            if len(hits) == 0:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — write face "
                      f"accepted alias [{label}] {shown!r} but GET /aliases does not list "
                      f"it byte-exact (dropped or mangled on readback)")
                return
            if len(hits) > 1:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias [{label}] "
                      f"listed {len(hits)} times in the global list")
                return
            if hits[0].get("collection_name") != c1:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — alias [{label}] "
                      f"{shown!r} listed with wrong collection_name="
                      f"{hits[0].get('collection_name')!r} (expected {c1})")
                return
            print(f"OK: [{label}] read back byte-exact, bound to {c1}")

        print(f"rejected-at-creation (write-face, not adjudicated): "
              f"{[(l, st) for l, st in rejected] or 'none'}")
        print("VERDICT: NO_DEFECT")
    finally:
        for _, name in accepted:
            try:
                delete_alias(name)
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
