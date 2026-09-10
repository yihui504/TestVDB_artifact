#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: state isolation via alias surface — delete collection that has an alias; delete via alias
Constraint: qdrant_bc_collection_delete_isolation_001 ("deleting a collection removes its points")
  + qdrant_state_collections_delete_001 (404 semantics for missing)
Endpoint: collections+delete (+ aliases+update, aliases+list, collections+get)
Round block: chunk_collections+delete
Coverage map: [alias isolation x bc_collection_delete_isolation_001 / state_collections_delete_001]
  part1: alias of deleted collection must not resurrect it
  part2: DELETE via alias of live collection deletes underlying consistently
Unit: behavioral_contracts::qdrant_bc_collection_delete_isolation_001
"""

import requests, json, sys, os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")


def safe_request(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    req_timeout = kwargs.pop("req_timeout", 60)
    try:
        resp = requests.request(method, url, headers=headers, timeout=req_timeout, **kwargs)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else {}
        except (json.JSONDecodeError, ValueError):
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""


A = "bd09_alias_src"
B = "bd09_via_alias"
ALIAS_A = "bd09_alias_a"
ALIAS_B = "bd09_alias_b"

def create_col(name):
    return safe_request("PUT", f"/collections/{name}",
                        json={"vectors": {"size": 4, "distance": "Cosine"}})

def alias_actions(actions):
    return safe_request("POST", "/collections/aliases", json={"actions": actions})

def alias_targets(alias):
    """Return list of collection names the alias currently points to (from /aliases)."""
    s, b, _ = safe_request("GET", "/aliases")
    out = []
    if s == 200 and isinstance(b, dict):
        for e in b.get("result", {}).get("aliases", []) or []:
            if e.get("alias") == alias:
                out.append(e.get("collection_name"))
    return s, out

try:
    defects = []

    # ---------- Part 1: alias must not resurrect deleted collection ----------
    s, _, raw = create_col(A)
    print(f"create {A}: {s}")
    if s not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — fixture A create failed")
        sys.exit(2)
    s, _, raw = alias_actions([{"create_alias": {"collection_name": A, "alias": ALIAS_A}}])
    print(f"create alias {ALIAS_A}: {s} raw={raw[:150]}")
    if s != 200:
        print("VERDICT: SCRIPT_ERROR — alias creation failed")
        sys.exit(2)

    # sanity: alias resolves before delete
    sg0, _, _ = safe_request("GET", f"/collections/{ALIAS_A}")
    print(f"GET via alias before delete: {sg0}")
    if sg0 != 200:
        defects.append(f"Type3_RuntimeFailure: alias GET sanity returned {sg0}, expected 200")

    s, _, raw = safe_request("DELETE", f"/collections/{A}")
    print(f"DELETE {A} (aliased): {s}")
    if s != 200:
        defects.append(f"Type3_RuntimeFailure: DELETE of aliased collection returned {s}")

    # alias GET after underlying delete -> must be 404 (no resurrection)
    sg1, _, rawg1 = safe_request("GET", f"/collections/{ALIAS_A}")
    print(f"GET via alias after underlying delete: {sg1} raw={rawg1[:200]}")
    if sg1 == 200:
        defects.append("Type1_IllegalSuccess: alias still resolves 200 after underlying "
                       "collection deleted (resurrection via alias)")

    # alias DELETE after underlying delete -> must be 404, must not resurrect
    sd1, _, rawd1 = safe_request("DELETE", f"/collections/{ALIAS_A}")
    print(f"DELETE via alias after underlying delete: {sd1} raw={rawd1[:200]}")
    if sd1 == 200:
        defects.append("Type1_IllegalSuccess: DELETE via dangling alias returned 200 "
                       "(constraint: missing collection => 404)")
    if sd1 >= 500:
        defects.append(f"Type3_RuntimeFailure: DELETE via dangling alias returned {sd1}")

    # does the alias remain listed? (observation for judge; contradiction only if listed AND resolves)
    sl, targets = alias_targets(ALIAS_A)
    print(f"alias list status={sl}; {ALIAS_A} still listed -> {targets}")

    # underlying name must be gone
    sgA, _, _ = safe_request("GET", f"/collections/{A}")
    print(f"GET {A} after all: {sgA}")
    if sgA == 200:
        defects.append("Type1_IllegalSuccess: underlying collection still 200 after delete")

    # ---------- Part 2: DELETE via alias of a LIVE collection (consistency) ----------
    s, _, _ = create_col(B)
    print(f"create {B}: {s}")
    if s in (200, 201):
        s, _, raw = alias_actions([{"create_alias": {"collection_name": B, "alias": ALIAS_B}}])
        print(f"create alias {ALIAS_B}: {s}")
        if s == 200:
            sg2, _, _ = safe_request("GET", f"/collections/{ALIAS_B}")
            print(f"GET via {ALIAS_B} before delete: {sg2}")
            sd2, _, rawd2 = safe_request("DELETE", f"/collections/{ALIAS_B}")
            print(f"DELETE via {ALIAS_B}: {sd2} raw={rawd2[:200]}")
            if sd2 == 200:
                # underlying must be gone
                sgB, _, _ = safe_request("GET", f"/collections/{B}")
                print(f"GET underlying {B} after alias-delete: {sgB}")
                if sgB == 200:
                    defects.append("Type4_StateLogicViolation: DELETE via alias returned 200 "
                                   "but underlying collection still exists")
            elif sg2 == 200 and sd2 == 404:
                defects.append("Type1_IllegalSuccess/Inconsistency: GET via alias = 200 but "
                               "DELETE via same alias = 404 (read/delete disagree on alias target)")
            elif sd2 >= 500:
                defects.append(f"Type3_RuntimeFailure: DELETE via live alias returned {sd2}")
            else:
                print(f"NOTE: DELETE via alias returned {sd2}; judge to weigh vs alias semantics")
        else:
            print("NOTE: alias B creation failed; part2 partially skipped")
    else:
        print("NOTE: fixture B create failed; part2 skipped")

    if defects:
        print("VERDICT: DEFECT_FOUND — " + " | ".join(defects))
    else:
        print("VERDICT: NO_DEFECT — dangling alias 404s on GET/DELETE; "
              "delete-via-live-alias consistent with underlying state")
except SystemExit:
    raise
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR — unhandled exception: {e}")
    sys.exit(2)
finally:
    for c in (A, B, ALIAS_A, ALIAS_B):
        try:
            safe_request("DELETE", f"/collections/{c}")
        except Exception:
            pass
    try:
        alias_actions([{"delete_alias": {"collection_name": A, "alias": ALIAS_A}},
                       {"delete_alias": {"collection_name": B, "alias": ALIAS_B}}])
    except Exception:
        pass
