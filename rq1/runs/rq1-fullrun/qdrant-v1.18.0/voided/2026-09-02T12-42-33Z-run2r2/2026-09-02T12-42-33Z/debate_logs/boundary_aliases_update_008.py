#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: both-direction atomicity on aliases+update (POST /collections/aliases) x qdrant_state_aliases_update_001 — positive: [create a1, create a2] valid multi-action batch -> 200 and BOTH applied; negative order 1: [create_alias(valid), create_alias(missing-collection)] -> rejected and NEITHER applied; negative order 2 (destructive): established alias a_del + batch [delete_alias(a_del), create_alias(missing-collection)] -> rejected and a_del STILL EXISTS (delete must not have applied); negative order 3: [delete_alias(unknown), create_alias(valid)] -> rejected and valid alias NOT created
Oracle: a batch containing ANY failing action is rejected (404/4xx/500-family all acceptable as the rejection) AND leaves ZERO observable state change attributable to that batch in GET /aliases — the pre-existing alias survives untouched and the would-be-created aliases are absent; any partially-applied state (first action applied despite batch rejection, established alias vanished after a rejected delete+create) = Type4_StateLogicViolation directly contradicting the constraint "alias changes are ATOMIC: no collection modifications can happen between the alias operations of one request"; positive batch returning 200 with both aliases present = required promise exercise; 5xx handled with healthz recheck (Type3 only if service degraded)
Constraint: qdrant_state_aliases_update_001 (state constraint: alias operations in one request are applied atomically; level=system, evidence_tier=explicit)
Blindspot: BS-03 Concurrency State Blindness (sequential analogue: intermediate/partial state must never be observable even when a later action in the same batch fails)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

G6 mutation justification: the failing-second-action batch is the sharpest
mutation of the ATOMIC promise — implementations that validate-and-apply
action-by-action instead of staging the whole batch will have already applied
action 1 when action 2 fails; the destructive direction (valid delete first,
failing create second) would additionally DESTROY an established alias, i.e.
a rejected request causing state loss.
R1 lesson applied: envelope nests at result (boolean); ownership by unique
per-script prefix bau8<uuid>.
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


def alias_present(name):
    """GET /aliases -> is alias_name present? (contract: result.aliases)."""
    s, _, raw = safe_request("GET", "/aliases", timeout=30)
    if s != 200:
        return None, f"status={s}"
    try:
        b = json.loads(raw)
        for e in b["result"]["aliases"]:
            if isinstance(e, dict) and e.get("alias_name") == name:
                return True, None
        return False, None
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
    pfx = "bau8" + tag
    coll = pfx + "c1"
    missing_coll = pfx + "nope"
    a1, a2, a_del = pfx + "a1", pfx + "a2", pfx + "adel"
    print(f"ownership prefix: {pfx}")

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    def update(actions):
        return safe_request("POST", "/collections/aliases", params={"timeout": 60},
                            json={"actions": actions}, timeout=60)

    def check_untouched(label, must_exist, must_absent):
        """After a rejected batch: must_exist all present, must_absent all absent."""
        for n in must_exist:
            present, err = alias_present(n)
            if err is not None:
                print(f"VERDICT: SCRIPT_ERROR — GET /aliases unreadable ({err})")
                return False
            if not present:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — rejected batch "
                      f"[{label}] still DESTROYED pre-existing alias {n} "
                      f"(non-atomic: delete applied although the batch failed)")
                return False
        for n in must_absent:
            present, err = alias_present(n)
            if err is not None:
                print(f"VERDICT: SCRIPT_ERROR — GET /aliases unreadable ({err})")
                return False
            if present:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — rejected batch "
                      f"[{label}] still CREATED alias {n} "
                      f"(non-atomic: first action applied although the batch failed)")
                return False
        return True

    try:
        # Positive (G4): fully valid multi-action batch applies all
        s, _, raw = update([
            {"create_alias": {"collection_name": coll, "alias_name": a1}},
            {"create_alias": {"collection_name": coll, "alias_name": a2}},
        ])
        print(f"positive [create a1, create a2] -> status={s} raw={raw[:200]}")
        if s != 200:
            print("VERDICT: SCRIPT_ERROR — positive atomic batch failed, no defect conclusion")
            return
        for n in (a1, a2):
            present, err = alias_present(n)
            if err is not None or not present:
                print(f"VERDICT: SCRIPT_ERROR — positive batch did not apply {n} ({err})")
                return
        print("OK: positive batch applied both aliases")

        # Negative 1: valid create FIRST, failing create SECOND -> nothing applied
        s, _, raw = update([
            {"create_alias": {"collection_name": coll, "alias_name": pfx + "n1"}},
            {"create_alias": {"collection_name": missing_coll, "alias_name": pfx + "n2"}},
        ])
        print(f"negative1 [create valid, create missing-coll] -> status={s}")
        print(f"  raw: {raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s == 200:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — batch containing "
                  "create_alias on missing collection returned 200 (documented 404)")
            return
        if not check_untouched("neg1", [], [pfx + "n1", pfx + "n2"]):
            return
        print(f"OK: rejected {s}, zero partial application")

        # Negative 2 (destructive): established a_del + [delete a_del, create missing]
        s, _, raw = update([{"create_alias": {
            "collection_name": coll, "alias_name": a_del}}])
        if s != 200 or alias_present(a_del)[0] is not True:
            print("VERDICT: SCRIPT_ERROR — a_del setup failed, no defect conclusion")
            return
        s, _, raw = update([
            {"delete_alias": {"alias_name": a_del}},
            {"create_alias": {"collection_name": missing_coll, "alias_name": pfx + "n3"}},
        ])
        print(f"negative2 [delete a_del, create missing-coll] -> status={s}")
        print(f"  raw: {raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s == 200:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — batch containing "
                  "create_alias on missing collection returned 200 (documented 404)")
            return
        if not check_untouched("neg2", [a_del], [pfx + "n3"]):
            return
        print(f"OK: rejected {s}, established alias survived (atomic)")

        # Negative 3: [delete unknown, create valid] -> nothing applied
        s, _, raw = update([
            {"delete_alias": {"alias_name": pfx + "ghost"}},
            {"create_alias": {"collection_name": coll, "alias_name": pfx + "n4"}},
        ])
        print(f"negative3 [delete unknown, create valid] -> status={s}")
        print(f"  raw: {raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s == 200:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — batch containing "
                  "delete of unknown alias returned 200 (documented 404/500)")
            return
        if not check_untouched("neg3", [], [pfx + "n4"]):
            return
        print(f"OK: rejected {s}, zero partial application")

        print("VERDICT: NO_DEFECT")
    finally:
        for n in (a1, a2, a_del):
            try:
                delete_alias(n)
            except Exception:
                pass  # cleanup failures are non-fatal
        try:
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
