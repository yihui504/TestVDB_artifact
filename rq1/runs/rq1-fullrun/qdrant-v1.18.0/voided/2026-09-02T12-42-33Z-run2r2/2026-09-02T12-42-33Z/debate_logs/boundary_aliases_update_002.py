#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary on the `actions` container/element structure of aliases+update (POST /collections/aliases) x request_required_paths (actions; actions[].create_alias.{alias_name,collection_name}; actions[].delete_alias.alias_name; actions[].rename_alias.{old,new}_alias_name) + qdrant_behavioral_aliases_update_001 — probes: actions missing / null / string / object / int / empty array / [null] / [string] / [{}] / unknown action key / double-key element / create_alias as scalar string
Oracle: positive control (one well-formed create_alias then delete_alias) returns 200 both times with envelope result:boolean and the alias appearing/disappearing in GET /aliases; every structurally invalid actions probe (missing/null/non-array/scalar-element/null-element/empty-object-element/unknown-action-key/double-key/scalar-payload) is rejected 4xx with a non-empty diagnostic body; 200 on any invalid shape = Type1_IllegalSuccess (plus state check), empty-array [] accepted 200 with ZERO state change or rejected 4xx both fine, 5xx = Type3_RuntimeFailure (healthz rechecked), 4xx with empty body = Type2_PoorDiagnostics (constraint qdrant_behavioral_aliases_update_001 + request_required_paths)
Constraint: qdrant_behavioral_aliases_update_001 + aliases+update request_required_paths (actions[] oneOf create_alias|delete_alias|rename_alias)
Blindspot: BS-01 Parameter Type Coercion Trust (serde assumed to validate the nested actions array; null/object/scalar mutations must not pass silently)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R1 lesson applied: envelope nests at result (boolean); ownership by unique
per-script prefix bau2<uuid>.
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


def alias_names(raw):
    entries, err = parse_global_aliases(raw)
    if err is not None:
        return None, err
    return [e.get("alias_name") for e in entries if isinstance(e, dict)], None


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
    pfx = "bau2" + tag
    coll = pfx + "c1"
    print(f"ownership prefix: {pfx}")

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    pos_alias = pfx + "pos"
    try:
        # Positive control (G4): well-formed create then delete, both must 200
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [{"create_alias": {
                                     "collection_name": coll, "alias_name": pos_alias}}]},
                                 timeout=60)
        print(f"positive create -> status={s} raw={raw[:200]}")
        if s != 200:
            print("VERDICT: SCRIPT_ERROR — positive control create failed, no defect conclusion")
            return
        ls, _, lraw = safe_request("GET", "/aliases", timeout=30)
        names, err = alias_names(lraw)
        if ls != 200 or err is not None or pos_alias not in names:
            print(f"VERDICT: SCRIPT_ERROR — positive control alias not observable ({err})")
            return
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [{"delete_alias": {
                                     "alias_name": pos_alias}}]}, timeout=60)
        print(f"positive delete -> status={s} raw={raw[:200]}")
        if s != 200:
            print("VERDICT: SCRIPT_ERROR — positive control delete failed, no defect conclusion")
            return

        # Act: structurally invalid `actions` shapes
        probes = [
            ("actions-missing", {}),
            ("actions-null", {"actions": None}),
            ("actions-string", {"actions": "create_alias"}),
            ("actions-object", {"actions": {}}),
            ("actions-int", {"actions": 42}),
            ("actions-empty-array", {"actions": []}),
            ("element-null", {"actions": [None]}),
            ("element-string", {"actions": ["create_alias"]}),
            ("element-empty-object", {"actions": [{}]}),
            ("unknown-action-key", {"actions": [{"unknown_op": {
                "collection_name": coll, "alias_name": pfx + "x"}}]}),
            ("double-key-element", {"actions": [
                {"create_alias": {"collection_name": coll, "alias_name": pfx + "y"},
                 "delete_alias": {"alias_name": pfx + "y"}}]}),
            ("scalar-payload", {"actions": [{"create_alias": "notanobject"}]}),
        ]
        for label, body in probes:
            s, _, raw = safe_request("POST", "/collections/aliases",
                                     params={"timeout": 60}, json=body, timeout=60)
            print(f"probe[{label}] -> status={s}")
            print(f"  raw: {raw[:300]}")
            if s <= 0:
                hs, hraw = liveness()
                print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
                if hs <= 0 or hs >= 500:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — body[{label}] "
                          f"killed the service (healthz={hs})")
                else:
                    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
                return
            if 500 <= s <= 599:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — invalid actions shape "
                      f"[{label}] triggered {s}")
                return
            if 400 <= s <= 499:
                if not raw.strip():
                    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — [{label}] "
                          f"rejected {s} with empty diagnostic body")
                    return
                print(f"  OK: rejected {s} with non-empty diagnostics")
                continue
            if s != 200:
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} for [{label}]")
                return
            # 200: allowed only for the no-op empty array; any state change is a defect
            ls, _, lraw = safe_request("GET", "/aliases", timeout=30)
            names, err = alias_names(lraw)
            if ls != 200 or err is not None:
                print(f"VERDICT: SCRIPT_ERROR — GET /aliases face unreadable ({err})")
                return
            leaked = [n for n in (names or [])
                      if isinstance(n, str) and n.startswith(pfx) and n != pos_alias]
            if label == "actions-empty-array":
                if leaked:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — empty batch "
                          f"applied state: {leaked[:3]}")
                    return
                print("  OK: empty batch 200 no-op, zero state change")
                continue
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — invalid actions shape "
                  f"[{label}] accepted 200 (silently passed serde validation); "
                  f"prefix-owned state now: {leaked[:3]}")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        # defensive cleanup: sweep any prefix-owned alias created by a rogue 200
        try:
            ls, _, lraw = safe_request("GET", "/aliases", timeout=30)
            names, err = alias_names(lraw)
            if err is None:
                for n in (names or []):
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
