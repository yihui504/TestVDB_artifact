#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 resource-limit/batch-scale on the `actions` array of aliases+update (POST /collections/aliases) x qdrant_state_aliases_update_001 + qdrant_behavioral_aliases_update_001 — probe: ONE request carrying 1000 create_alias actions (all valid, unique names), then ONE request carrying 1000 matching delete_alias actions; verdict criteria are crash-free and all-or-nothing
Oracle: bulk 1000-action create returns either 200 with ALL 1000 aliases listed in GET /aliases (count delta exactly +1000 — under-application = Type4_StateLogicViolation) or a 4xx wholesale rejection with ZERO of the 1000 applied (any partial subset = Type4 non-atomic per the ATOMIC spec description); 5xx/OOM/hang = Type3_RuntimeFailure (healthz rechecked; client timeout 180s); the matching 1000-action delete then leaves zero prefix-owned aliases. NOTE (G6 mutation justification): bulk is the boundary where per-item validation loops, batch capacity limits and the all-or-nothing apply loop most plausibly surface — a mid-batch failure here is exactly where a non-atomic partial apply would be observable, so the same probe doubles as an atomicity check at resource scale (constraint qdrant_state_aliases_update_001: "alias operations in one request are applied atomically"; qdrant_behavioral_aliases_update_001: "valid alias batch returns HTTP 200")
Constraint: qdrant_state_aliases_update_001 (state constraint: alias changes ATOMIC) + qdrant_behavioral_aliases_update_001 (valid batch 200)
Blindspot: BS-07 Resource Exhaustion Optimism (batch endpoints assumed to handle any array length; no documented actions[] upper bound in the contract)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R1 lesson applied: envelope nests at result (boolean); ownership by unique
per-script prefix bau7<uuid>.
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

BULK = 1000


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


def prefix_aliases(pfx):
    """GET /aliases -> names owned by prefix (contract: result.aliases)."""
    s, _, raw = safe_request("GET", "/aliases", timeout=60)
    if s != 200:
        return None, f"status={s}"
    try:
        b = json.loads(raw)
        names = [e.get("alias_name") for e in b["result"]["aliases"]
                 if isinstance(e, dict) and isinstance(e.get("alias_name"), str)
                 and e["alias_name"].startswith(pfx)]
        return names, None
    except Exception as e:
        return None, f"envelope:{e}"


def drop_collection(name):
    try:
        safe_request("DELETE", f"/collections/{name}", params={"timeout": 60}, timeout=60)
    except Exception:
        pass  # cleanup failures are non-fatal


def bulk_delete(names):
    """Best-effort chunked deletion of leftover aliases (cleanup only)."""
    for i in range(0, len(names), 500):
        chunk = names[i:i + 500]
        try:
            safe_request("POST", "/collections/aliases", params={"timeout": 120},
                         json={"actions": [{"delete_alias": {"alias_name": n}} for n in chunk]},
                         timeout=180)
        except Exception:
            pass  # cleanup failures are non-fatal


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bau7" + tag
    coll = pfx + "c1"
    print(f"ownership prefix: {pfx} (bulk={BULK})")

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    names_before, err = prefix_aliases(pfx)
    if err is not None or names_before:
        print(f"VERDICT: SCRIPT_ERROR — dirty baseline for prefix ({err}): {names_before[:3]}")
        return

    expected = [f"{pfx}b{i:04d}" for i in range(BULK)]
    try:
        # Act: ONE request with BULK valid create_alias actions
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 120},
                                 json={"actions": [{"create_alias": {
                                     "collection_name": coll, "alias_name": n}}
                                     for n in expected]},
                                 timeout=180)
        print(f"bulk create({BULK}) -> status={s}")
        print(f"  raw: {raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
            if hs <= 0 or hs >= 500:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — bulk {BULK}-action "
                      f"batch killed/hung the service (healthz={hs})")
            else:
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            hs, hraw = liveness()
            print(f"  healthz after 5xx: {hs}")
            if hs == 200:
                print(f"  NOTE: {s} with healthz alive — partial apply check below decides")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — bulk batch triggered "
                      f"{s} and healthz={hs}")
                return

        applied, err = prefix_aliases(pfx)
        if err is not None:
            print(f"VERDICT: SCRIPT_ERROR — GET /aliases face unreadable ({err})")
            return
        applied_set = set(applied or [])
        expected_set = set(expected)
        n_applied = len(applied_set & expected_set)

        if s == 200:
            if n_applied != BULK:
                missing = BULK - n_applied
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — bulk 200 but only "
                      f"{n_applied}/{BULK} aliases applied ({missing} missing) — "
                      f"under-application of an acknowledged batch")
                return
            print(f"OK: bulk create 200, all {BULK} applied")
        elif 400 <= s <= 499 or 500 <= s <= 599:
            # rejected (or 5xx-but-alive): ATOMIC claim demands zero applied
            if n_applied != 0:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — batch rejected "
                      f"with {s} but {n_applied}/{BULK} aliases were applied anyway "
                      f"(non-atomic partial application; spec: alias changes are ATOMIC)")
                return
            if 500 <= s <= 599:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — bulk batch rejected "
                      f"with {s} (no crash, zero applied, but resource-limit 5xx)")
                return
            print(f"OK: wholesale rejection {s}, zero applied (atomic refusal)")
        else:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s}")
            return

        # Cleanup probe: ONE request with BULK matching delete_alias actions
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 120},
                                 json={"actions": [{"delete_alias": {"alias_name": n}}
                                                   for n in expected]},
                                 timeout=180)
        print(f"bulk delete({BULK}) -> status={s}")
        print(f"  raw: {raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
            if hs <= 0 or hs >= 500:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — bulk delete "
                      f"killed/hung the service (healthz={hs})")
            else:
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            hs, hraw = liveness()
            if hs != 200:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — bulk delete "
                      f"triggered {s} and healthz={hs}")
                return
            print(f"  NOTE: bulk delete {s} with healthz alive — leftover check below")
        elif s != 200:
            print(f"  NOTE: bulk delete returned {s} — leftover check below")

        left, err = prefix_aliases(pfx)
        if err is not None:
            print(f"VERDICT: SCRIPT_ERROR — GET /aliases face unreadable ({err})")
            return
        left_set = set(left or []) & expected_set
        if left_set:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — after bulk delete "
                  f"(status {s}) {len(left_set)} aliases remain (sample {sorted(left_set)[:3]})")
            return
        print("OK: bulk delete left zero prefix-owned aliases")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            left, err = prefix_aliases(pfx)
            if err is None and left:
                bulk_delete(left)
        except Exception:
            pass  # cleanup failures are non-fatal
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
