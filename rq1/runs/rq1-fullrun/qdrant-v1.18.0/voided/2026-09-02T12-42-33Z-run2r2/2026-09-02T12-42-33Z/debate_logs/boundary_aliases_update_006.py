#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy4 special-value roundtrip on alias_name of aliases+update create_alias (POST /collections/aliases) x qdrant_behavioral_aliases_update_001 + qdrant_state_aliases_update_001 observation — probes: unicode/emoji name, RTL+zero-width marks, SQL-injection string, JSON-injection string, overlong 100k-char name; each create -> verify byte-exact roundtrip in GET /aliases -> delete
Oracle: for every special-value name the create either (a) returns 200 and GET /aliases lists the name bound to the owning collection BYTE-EXACTLY and the follow-up delete 200 removes it, or (b) rejects 4xx with non-empty diagnostics; roundtrip mismatch / name vanish / wrong collection binding = Type4_StateLogicViolation, 5xx = Type3_RuntimeFailure (healthz rechecked), 200-then-delete-404-permanently-stuck alias = Type4_StateLogicViolation (constraint qdrant_behavioral_aliases_update_001 "valid alias batch returns HTTP 200" + aliases+list response_shape result.aliases[].alias_name string)
Constraint: qdrant_behavioral_aliases_update_001 (behavioral assertion, endpoint aliases+update) observed via qdrant_behavioral_aliases_list_001 envelope
Blindspot: BS-01 Parameter Type Coercion Trust (special characters assumed to roundtrip losslessly through create/list/delete)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R1 lesson applied: envelope nests at result.aliases; ownership by unique
per-script prefix bau6<uuid>.
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


def find_alias_entry(name):
    """GET /aliases -> entry dict for alias_name or None (contract: result.aliases)."""
    s, _, raw = safe_request("GET", "/aliases", timeout=30)
    if s != 200:
        return "ERR", f"status={s}"
    try:
        b = json.loads(raw)
        for e in b["result"]["aliases"]:
            if isinstance(e, dict) and e.get("alias_name") == name:
                return e, None
        return None, None
    except Exception as e:
        return "ERR", f"envelope:{e}"


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
    pfx = "bau6" + tag
    coll = pfx + "c1"
    print(f"ownership prefix: {pfx}")

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        probes = [
            ("unicode-emoji", pfx + "-中文测试🎯"),
            ("rtl-zero-width", pfx + "-a‏b​c"),
            ("sql-injection", pfx + "-'; DROP TABLE aliases--"),
            ("json-injection", pfx + '-{"$gt": ""}'),
            ("overlong-100k", pfx + "-" + "a" * 100000),
        ]
        for label, name in probes:
            shown = name if len(name) <= 40 else name[:37] + "..."
            # create
            s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                     json={"actions": [{"create_alias": {
                                         "collection_name": coll, "alias_name": name}}]},
                                     timeout=120)
            print(f"probe[{label}] create -> status={s}")
            print(f"  raw: {raw[:300]}")
            if s <= 0:
                hs, hraw = liveness()
                print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
                return
            if 500 <= s <= 599:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — special value "
                      f"[{label}] create triggered {s}")
                return
            if 400 <= s <= 499:
                if not raw.strip():
                    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — [{label}] "
                          f"create rejected {s} with empty diagnostic body")
                    return
                print(f"  OK: create rejected {s} with non-empty diagnostics")
                continue
            if s != 200:
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} for [{label}] create")
                return

            # roundtrip check: byte-exact name bound to our collection
            entry, err = find_alias_entry(name)
            if err is not None:
                print(f"VERDICT: SCRIPT_ERROR — GET /aliases face unreadable ({err})")
                return
            if entry is None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — [{label}] "
                      f"create 200 but name not listed (silent vanish): {shown!r}")
                return
            if entry.get("collection_name") != coll:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — [{label}] "
                      f"roundtrip binding corrupted: {json.dumps(entry, ensure_ascii=False)[:200]}")
                return
            print(f"  OK: roundtrip byte-exact, bound to owning collection")

            # delete and confirm removal
            s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                     json={"actions": [{"delete_alias": {
                                         "alias_name": name}}]}, timeout=120)
            print(f"probe[{label}] delete -> status={s} raw={raw[:200]}")
            if s != 200:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — [{label}] "
                      f"created alias cannot be deleted (status {s}) — permanently stuck")
                return
            entry, err = find_alias_entry(name)
            if err is not None:
                print(f"VERDICT: SCRIPT_ERROR — GET /aliases face unreadable ({err})")
                return
            if entry is not None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — [{label}] "
                      f"delete 200 but alias still listed: {json.dumps(entry, ensure_ascii=False)[:200]}")
                return
            print(f"  OK: deleted cleanly")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            # defensive sweep: any prefix-owned alias left behind gets deleted
            s, _, raw = safe_request("GET", "/aliases", timeout=30)
            if s == 200:
                b = json.loads(raw)
                for e in b["result"]["aliases"]:
                    n = e.get("alias_name") if isinstance(e, dict) else None
                    if isinstance(n, str) and n.startswith(pfx):
                        delete_alias(n)
        except Exception:
            pass  # cleanup failures are non-fatal
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
