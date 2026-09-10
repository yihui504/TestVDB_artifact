#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1/5 both-direction on the documented status contract of aliases+update (POST /collections/aliases) x qdrant_behavioral_aliases_update_001 — positive: valid multi-action batch [create a1, create a2] -> 200 with envelope result:boolean; negative 1: create_alias on a MISSING collection -> documented 404; negative 2: delete_alias of an UNKNOWN alias -> documented 404 or 500; negative 3: rename_alias of an UNKNOWN alias -> documented 404 or 500; plus strategy-5 diagnostic-quality check on every observed 4xx
Oracle: positive multi-action batch returns 200 with result:boolean=true and BOTH aliases observable in GET /aliases (under-application = Type4_StateLogicViolation); create_alias on missing collection returns 404 (400/422 accepted-with-note as diagnostics-bearing rejection; 200 = Type1_IllegalSuccess with dangling-binding check; 502/503 = Type3 healthz-rechecked); delete/rename of unknown alias returns 404 or 500 per the assertion (200 = Type1_IllegalSuccess; other 4xx accepted-with-note); any 404/422 with an EMPTY diagnostic body = Type2_PoorDiagnostics (constraint qdrant_behavioral_aliases_update_001: "valid alias batch returns HTTP 200; create_alias on a missing collection returns 404; delete/rename of an unknown alias returns 404 or 500")
Constraint: qdrant_behavioral_aliases_update_001 (behavioral assertion, endpoint aliases+update)
Blindspot: BS-04 Boundary Default Optimism (documented error statuses assumed delivered without probing)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R1 lesson applied: envelope nests at result (boolean); ownership by unique
per-script prefix bau4<uuid>.
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
    pfx = "bau4" + tag
    coll = pfx + "c1"
    missing_coll = pfx + "nope"
    a1, a2 = pfx + "a1", pfx + "a2"
    print(f"ownership prefix: {pfx}")

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # Positive: valid multi-action batch must 200 and apply BOTH actions
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [
                                     {"create_alias": {"collection_name": coll, "alias_name": a1}},
                                     {"create_alias": {"collection_name": coll, "alias_name": a2}},
                                 ]}, timeout=60)
        print(f"positive multi-create -> status={s} raw={raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"transport failure (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — valid alias batch "
                  f"documented as 200 returned {s}")
            return
        try:
            result_ok = isinstance(json.loads(raw).get("result"), bool)
        except Exception:
            result_ok = False
        if not result_ok:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 but envelope "
                  f"violates response_shape result:boolean: {raw[:200]}")
            return
        names, err = alias_names()
        if err is not None:
            print(f"VERDICT: SCRIPT_ERROR — GET /aliases face unreadable ({err})")
            return
        missing_apply = [a for a in (a1, a2) if a not in (names or [])]
        if missing_apply:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 batch "
                  f"under-applied; missing: {missing_apply}")
            return
        print("OK: positive batch 200, both aliases applied, envelope intact")

        # Negative 1: create_alias on a MISSING collection -> documented 404
        bad = pfx + "dangling"
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [{"create_alias": {
                                     "collection_name": missing_coll, "alias_name": bad}}]},
                                 timeout=60)
        print(f"negative create-on-missing-collection -> status={s}")
        print(f"  raw: {raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s == 200:
            names, _ = alias_names()
            bound = bad in (names or [])
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — create_alias on missing "
                  f"collection {missing_coll} returned 200 (documented 404); "
                  f"dangling binding present in global list: {bound}")
            return
        if s == 500:
            print("  OK: 500 observed (within documented 404/500 family for this endpoint)")
        elif s in (400, 404, 422):
            if not raw.strip():
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — create-on-missing "
                      f"rejected {s} with empty diagnostic body")
                return
            if s != 404:
                print(f"  NOTE: {s} instead of documented 404 but diagnostics-bearing — "
                      f"recorded for judge")
            else:
                print("  OK: 404 as documented, non-empty diagnostics")
        elif 502 <= s <= 503:
            hs, hraw = liveness()
            if hs == 200:
                print(f"  NOTE: {s} with healthz alive — recorded for judge")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — create-on-missing "
                      f"triggered {s} and healthz={hs}")
                return
        else:
            print(f"  NOTE: unexpected status {s} — recorded for judge")

        # Negative 2: delete_alias of an UNKNOWN alias -> documented 404 or 500
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [{"delete_alias": {
                                     "alias_name": pfx + "ghost"}}]}, timeout=60)
        print(f"negative delete-unknown-alias -> status={s}")
        print(f"  raw: {raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s == 200:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — delete of unknown alias "
                  "returned 200 (documented 404 or 500)")
            return
        if s in (404, 500):
            print(f"  OK: {s} within documented 404/500")
        elif 400 <= s <= 499:
            if not raw.strip():
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — delete-unknown "
                      f"rejected {s} with empty diagnostic body")
                return
            print(f"  NOTE: {s} instead of documented 404/500 but diagnostics-bearing — "
                  f"recorded for judge")
        elif 502 <= s <= 599:
            hs, hraw = liveness()
            if hs == 200:
                print(f"  NOTE: {s} with healthz alive — recorded for judge")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — delete-unknown "
                      f"triggered {s} and healthz={hs}")
                return

        # Negative 3: rename_alias of an UNKNOWN alias -> documented 404 or 500
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [{"rename_alias": {
                                     "old_alias_name": pfx + "ghost",
                                     "new_alias_name": pfx + "ghost2"}}]}, timeout=60)
        print(f"negative rename-unknown-alias -> status={s}")
        print(f"  raw: {raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s == 200:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — rename of unknown alias "
                  "returned 200 (documented 404 or 500)")
            return
        if s in (404, 500):
            print(f"  OK: {s} within documented 404/500")
        elif 400 <= s <= 499:
            if not raw.strip():
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — rename-unknown "
                      f"rejected {s} with empty diagnostic body")
                return
            print(f"  NOTE: {s} instead of documented 404/500 but diagnostics-bearing — "
                  f"recorded for judge")
        elif 502 <= s <= 599:
            hs, hraw = liveness()
            if hs == 200:
                print(f"  NOTE: {s} with healthz alive — recorded for judge")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — rename-unknown "
                      f"triggered {s} and healthz={hs}")
                return

        print("VERDICT: NO_DEFECT")
    finally:
        for a in (a1, a2):
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
