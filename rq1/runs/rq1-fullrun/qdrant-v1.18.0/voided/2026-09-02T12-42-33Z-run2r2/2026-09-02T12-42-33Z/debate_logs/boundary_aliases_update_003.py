#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary on the typed leaf fields of aliases+update actions (POST /collections/aliases) x request_required_paths — create_alias.alias_name typed values {int 123, float 1.5, bool true, null, [], {}, nested object}, create_alias.collection_name {null, [], 123}, create_alias missing alias_name, create_alias missing collection_name, delete_alias missing alias_name, rename_alias missing new_alias_name, rename_alias missing old_alias_name
Oracle: positive control (valid create then delete) returns 200 with envelope result:boolean and observable state change in GET /aliases; every wrong-typed or missing required leaf field is rejected 4xx with non-empty diagnostic body; 200 on any wrong-typed/missing-leaf probe = Type1_IllegalSuccess (cross-checked that no coerced alias name polluted GET /aliases), 5xx = Type3_RuntimeFailure (healthz rechecked), empty-body 4xx = Type2_PoorDiagnostics (request_required_paths: actions[].create_alias.alias_name + collection_name, actions[].delete_alias.alias_name, actions[].rename_alias.{new,old}_alias_name)
Constraint: qdrant_behavioral_aliases_update_001 + aliases+update request_required_paths (all action leaves typed string and required)
Blindspot: BS-01 Parameter Type Coercion Trust (string-typed names assumed validated; int/bool/null/array/object mutations must not coerce through)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R1 lesson applied: envelope nests at result (boolean); ownership by unique
per-script prefix bau3<uuid>.
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


def alias_names():
    """GET /aliases -> list of alias names (contract: result.aliases[].alias_name)."""
    s, _, raw = safe_request("GET", "/aliases", timeout=30)
    if s != 200:
        return None, f"status={s}"
    try:
        b = json.loads(raw)
        names = [e.get("alias_name") for e in b["result"]["aliases"]
                 if isinstance(e, dict)]
        return names, None
    except Exception as e:
        return None, f"envelope:{e}"


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
    pfx = "bau3" + tag
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
        # Positive control (G4)
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [{"create_alias": {
                                     "collection_name": coll, "alias_name": pos_alias}}]},
                                 timeout=60)
        print(f"positive create -> status={s} raw={raw[:200]}")
        names, err = alias_names()
        if s != 200 or err is not None or pos_alias not in (names or []):
            print(f"VERDICT: SCRIPT_ERROR — positive control failed ({err})")
            return
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [{"delete_alias": {
                                     "alias_name": pos_alias}}]}, timeout=60)
        print(f"positive delete -> status={s} raw={raw[:200]}")
        if s != 200:
            print("VERDICT: SCRIPT_ERROR — positive control delete failed")
            return

        # Act: wrong-typed / missing leaf fields. Each probe mutates exactly one leaf.
        def create_body(alias_name="__KEEP__", collection_name="__KEEP__"):
            act = {}
            if alias_name != "__KEEP__":
                act["alias_name"] = alias_name
            if collection_name != "__KEEP__":
                act["collection_name"] = collection_name
            return {"actions": [{"create_alias": act}]}

        probes = [
            ("alias_name-int", create_body(alias_name=123, collection_name=coll)),
            ("alias_name-float", create_body(alias_name=1.5, collection_name=coll)),
            ("alias_name-bool", create_body(alias_name=True, collection_name=coll)),
            ("alias_name-null", create_body(alias_name=None, collection_name=coll)),
            ("alias_name-array", create_body(alias_name=[], collection_name=coll)),
            ("alias_name-object", create_body(alias_name={"a": 1}, collection_name=coll)),
            ("collection_name-null", create_body(alias_name=pfx + "n1", collection_name=None)),
            ("collection_name-array", create_body(alias_name=pfx + "n2", collection_name=[])),
            ("collection_name-int", create_body(alias_name=pfx + "n3", collection_name=123)),
            ("create-missing-alias_name", create_body(collection_name=coll)),
            ("create-missing-collection_name", create_body(alias_name=pfx + "n4")),
            ("delete-missing-alias_name", {"actions": [{"delete_alias": {}}]}),
            ("rename-missing-new", {"actions": [{"rename_alias": {
                "old_alias_name": pfx + "never"}}]}),
            ("rename-missing-old", {"actions": [{"rename_alias": {
                "new_alias_name": pfx + "nn"}}]}),
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
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leaf probe "
                          f"[{label}] killed the service (healthz={hs})")
                else:
                    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
                return
            if 500 <= s <= 599:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leaf probe "
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
            # 200 on a wrong-typed/missing required leaf = illegal success
            names, err = alias_names()
            if err is not None:
                print(f"VERDICT: SCRIPT_ERROR — GET /aliases face unreadable ({err})")
                return
            coerced = [repr(n) for n in (names or [])
                       if not isinstance(n, str) or
                       (isinstance(n, str) and n.startswith(pfx) and n != pos_alias)]
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — wrong-typed/missing "
                  f"leaf [{label}] accepted 200; prefix-owned/non-string aliases now: "
                  f"{coerced[:5]}")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            names, err = alias_names()
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
