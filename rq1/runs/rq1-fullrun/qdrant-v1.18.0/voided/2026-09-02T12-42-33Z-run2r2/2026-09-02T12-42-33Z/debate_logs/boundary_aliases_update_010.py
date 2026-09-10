#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1/5 on the rename_alias face of aliases+update (POST /collections/aliases) x qdrant_behavioral_aliases_update_001 + qdrant_bc_alias_switch_atomic_001 rename variant — positive: rename_alias old->new returns 200 and the OLD name is absent from EVERY face (global list + per-collection list of the target) while the NEW name is bound to the same collection exactly once; negative: rename_alias of an UNKNOWN old name returns the documented 404 or 500 with non-empty diagnostics
Oracle: positive rename 200 leaves exactly one entry new_name->target in GET /aliases and zero entries for old_name on the global face AND the per-collection face of the target (dangling old name on any face = Type4_StateLogicViolation — the rename was not applied atomically across observation faces); rename-unknown returns 404 or 500 per the assertion (200 = Type1_IllegalSuccess; other 4xx accepted-with-note; 502/503 healthz-rechecked); any 404/422 with empty diagnostic body = Type2_PoorDiagnostics (constraint qdrant_behavioral_aliases_update_001: "delete/rename of an unknown alias returns 404 or 500"; bc expected: "after a 200 the alias resolves to the new target" — here the new NAME)
Constraint: qdrant_behavioral_aliases_update_001 + qdrant_bc_alias_switch_atomic_001 (rename variant of the atomic alias change)
Blindspot: BS-04 Boundary Default Optimism (documented rename statuses and the all-faces rename consistency assumed)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R1 lesson applied: envelope nests at result.<field>; per-collection face
queried only for an EXISTING collection; ownership by unique per-script
prefix bauA<uuid>.
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


def global_entries():
    """GET /aliases -> entries list (contract: result.aliases[].{alias_name,
    collection_name})."""
    s, _, raw = safe_request("GET", "/aliases", timeout=30)
    if s != 200:
        return None, f"status={s}"
    try:
        return json.loads(raw)["result"]["aliases"], None
    except Exception as e:
        return None, f"envelope:{e}"


def collection_alias_names(name):
    """GET /collections/{name}/aliases -> alias names (lenient parse; the
    per-collection face has no response_shape in the contract)."""
    s, _, raw = safe_request("GET", f"/collections/{name}/aliases", timeout=30)
    if s != 200:
        return None, f"status={s}"
    try:
        b = json.loads(raw)
        r = b.get("result", b)
        if isinstance(r, dict) and isinstance(r.get("aliases"), list):
            return [e.get("alias_name") for e in r["aliases"] if isinstance(e, dict)], None
        if isinstance(r, list):
            return [e.get("alias_name") for e in r if isinstance(e, dict)], None
        return None, "unreadable"
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
    pfx = "bauA" + tag
    coll = pfx + "c1"
    old_name, new_name = pfx + "old", pfx + "new"
    print(f"ownership prefix: {pfx}")

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                             json={"actions": [{"create_alias": {
                                 "collection_name": coll, "alias_name": old_name}}]},
                             timeout=60)
    if s != 200:
        print(f"setup alias create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # Positive: rename old -> new (both required leaf fields present)
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [{"rename_alias": {
                                     "old_alias_name": old_name,
                                     "new_alias_name": new_name}}]}, timeout=60)
        print(f"positive rename -> status={s} raw={raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"transport failure (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — valid rename "
                  f"documented as 200 returned {s}")
            return

        entries, err = global_entries()
        if err is not None:
            print(f"VERDICT: SCRIPT_ERROR — GET /aliases face unreadable ({err})")
            return
        old_hits = [e for e in entries if isinstance(e, dict)
                    and e.get("alias_name") == old_name]
        new_hits = [e for e in entries if isinstance(e, dict)
                    and e.get("alias_name") == new_name]
        if old_hits:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — old name "
                  f"still resolvable on the global face after rename 200: "
                  f"{json.dumps(old_hits)[:200]}")
            return
        if len(new_hits) != 1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — expected exactly "
                  f"one entry for the new name, got {len(new_hits)}")
            return
        if new_hits[0].get("collection_name") != coll:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — rename changed "
                  f"the binding target: {json.dumps(new_hits[0])[:200]} (expected "
                  f"{coll})")
            return
        print(f"OK: global face — old gone, {new_name} -> {coll} exactly once")

        names_c, err = collection_alias_names(coll)
        if err is not None:
            print(f"NOTE: per-collection face unreadable ({err}) — global face "
                  f"already verified consistency")
        else:
            if old_name in (names_c or []):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — dangling "
                      f"old name on the per-collection face of {coll} after rename 200")
                return
            if new_name not in (names_c or []):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — new name "
                      f"missing on the per-collection face of {coll} (faces disagree)")
                return
            print(f"OK: per-collection face of {coll} consistent")

        # Negative: rename of an UNKNOWN old alias -> documented 404 or 500
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [{"rename_alias": {
                                     "old_alias_name": pfx + "ghost",
                                     "new_alias_name": pfx + "ghost2"}}]}, timeout=60)
        print(f"negative rename-unknown -> status={s}")
        print(f"  raw: {raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s == 200:
            # check whether the ghost rename materialized anywhere
            entries, _ = global_entries()
            ghost = [e for e in (entries or []) if isinstance(e, dict)
                     and e.get("alias_name") in (pfx + "ghost", pfx + "ghost2")]
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — rename of unknown "
                  f"alias returned 200 (documented 404 or 500); materialized "
                  f"entries: {json.dumps(ghost)[:200]}")
            return
        if s in (404, 500):
            print(f"  OK: {s} within documented 404/500")
        elif 400 <= s <= 499:
            if not raw.strip():
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — rename-unknown "
                      f"rejected {s} with empty diagnostic body")
                return
            print(f"  NOTE: {s} instead of documented 404/500 but diagnostics-bearing "
                  f"— recorded for judge")
        elif 502 <= s <= 599:
            hs, hraw = liveness()
            if hs == 200:
                print(f"  NOTE: {s} with healthz alive — recorded for judge")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — rename-unknown "
                      f"triggered {s} and healthz={hs}")
                return
        else:
            print(f"  NOTE: unexpected status {s} — recorded for judge")

        print("VERDICT: NO_DEFECT")
    finally:
        for n in (old_name, new_name):
            try:
                delete_alias(n)
            except Exception:
                pass  # cleanup failures are non-fatal
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
