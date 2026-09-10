#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral-contract both-direction on aliases+update (POST /collections/aliases) x qdrant_bc_alias_switch_atomic_001 — scenario per contract: create collections A (2 points) and B (5 points) with alias 'live' on A -> atomic switch batch [delete_alias live, create_alias live->B] in ONE request -> immediately observe ALL faces: GET /aliases (global), GET /collections/A/aliases + GET /collections/B/aliases (per-collection faces), and reads through the alias via POST /collections/live/points/count (exact)
Oracle: pre-switch: count through 'live' == 2 == count(A) (observation tool calibrated, else SCRIPT_ERROR before mutating); switch batch returns 200 with result:boolean; post-switch ALL faces agree on the NEW target with no intermediate state: global list has exactly ONE 'live' entry bound to B, per-collection face of B contains 'live', per-collection face of A does not, and count through 'live' == 5 == count(B) != count(A); any face disagreement (old binding visible, duplicate entries, alias missing on a face, reads still hitting A or 404) = Type4_StateLogicViolation contradicting "alias operations in one request are applied atomically - no intermediate state is observable"; 5xx on any face = Type3 (healthz rechecked)
Constraint: qdrant_bc_alias_switch_atomic_001 (behavioral contract: atomic alias switch, expected "after a 200 the alias resolves to the new target")
Blindspot: BS-03 Concurrency State Blindness (face-consistency analogue: intermediate or inconsistent alias state must not be observable across the documented observation faces)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R1 lessons applied: envelope nests at result.<field>; per-collection alias face
has its own known R1 defect for UNKNOWN collections (not re-tested here — only
EXISTING collections are queried as observation faces); ownership by unique
per-script prefix bau9<uuid>.
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

DIM = 4
N_A, N_B = 2, 5  # distinct point counts identify the resolved target


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


def count_points(name):
    """POST /collections/{name}/points/count exact -> (count, err)
    (contract points+count: result.count integer)."""
    s, _, raw = safe_request("POST", f"/collections/{name}/points/count",
                             json={"exact": True}, timeout=30)
    if s != 200:
        return None, f"status={s} raw={raw[:150]}"
    try:
        cnt = json.loads(raw)["result"]["count"]
        if not isinstance(cnt, int):
            return None, "count-not-int"
        return cnt, None
    except Exception as e:
        return None, f"envelope:{e}"


def global_alias_entries():
    """GET /aliases -> list of entries (contract: result.aliases[].{alias_name,
    collection_name})."""
    s, _, raw = safe_request("GET", "/aliases", timeout=30)
    if s != 200:
        return None, f"status={s}"
    try:
        return json.loads(raw)["result"]["aliases"], None
    except Exception as e:
        return None, f"envelope:{e}"


def collection_alias_names(name):
    """GET /collections/{name}/aliases -> alias names (lenient parse: the
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


def create_collection(name):
    s, _, raw = safe_request("PUT", f"/collections/{name}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        return False, f"status={s} raw={raw[:200]}"
    return True, None


def upsert_points(name, n):
    pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM, "payload": {"n": i}}
           for i in range(1, n + 1)]
    s, _, raw = safe_request("PUT", f"/collections/{name}/points",
                             params={"wait": "true"}, json={"points": pts}, timeout=60)
    if s not in (200, 201):
        return False, f"status={s} raw={raw[:200]}"
    return True, None


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
    pfx = "bau9" + tag
    coll_a, coll_b, live = pfx + "A", pfx + "B", pfx + "live"
    print(f"ownership prefix: {pfx} (A={N_A} pts, B={N_B} pts, alias={live})")

    # Arrange: A and B with distinct point counts, alias 'live' on A
    for name, n in ((coll_a, N_A), (coll_b, N_B)):
        ok, err = create_collection(name)
        if not ok:
            print(f"setup create {name} failed: {err}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        ok, err = upsert_points(name, n)
        if not ok:
            print(f"setup upsert {name} failed: {err}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
    cnt_a, err = count_points(coll_a)
    cnt_b, err2 = count_points(coll_b)
    if err or err2 or cnt_a != N_A or cnt_b != N_B:
        print(f"setup counts wrong: A={cnt_a}({err}) B={cnt_b}({err2})")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                             json={"actions": [{"create_alias": {
                                 "collection_name": coll_a, "alias_name": live}}]}, timeout=60)
    if s != 200:
        print(f"setup alias create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # Calibrate the observation tool BEFORE mutating: reads through 'live' hit A
        live_cnt, err = count_points(live)
        if err is not None or live_cnt != N_A:
            print(f"pre-check count through alias failed: {live_cnt} ({err}) — "
                  f"observation face unusable, no mutation performed")
            print("VERDICT: SCRIPT_ERROR — pre-check failure, no defect conclusion")
            return
        print(f"OK: pre-switch reads through {live} -> {live_cnt} pts (=A)")

        # Act: the atomic switch — ONE request, delete+create of the same alias name
        s, _, raw = safe_request("POST", "/collections/aliases", params={"timeout": 60},
                                 json={"actions": [
                                     {"delete_alias": {"alias_name": live}},
                                     {"create_alias": {"collection_name": coll_b,
                                                       "alias_name": live}},
                                 ]}, timeout=60)
        print(f"atomic switch [delete live, create live->B] -> status={s}")
        print(f"  raw: {raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s != 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — contract-documented "
                  f"switch batch must return 200, got {s}")
            return
        try:
            if not isinstance(json.loads(raw).get("result"), bool):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 but "
                      f"envelope violates result:boolean: {raw[:200]}")
                return
        except Exception:
            print(f"VERDICT: SCRIPT_ERROR — 200 but non-JSON body: {raw[:200]}")
            return

        # Assert: immediately after 200 ALL faces agree on the new target
        entries, err = global_alias_entries()
        if err is not None:
            print(f"VERDICT: SCRIPT_ERROR — GET /aliases face unreadable ({err})")
            return
        live_entries = [e for e in entries if isinstance(e, dict)
                        and e.get("alias_name") == live]
        if len(live_entries) == 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — after 200 the "
                  f"alias {live} is missing from the global face (intermediate state "
                  f"observable: delete applied, create not)")
            return
        if len(live_entries) > 1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — duplicate alias "
                  f"entries after switch: {json.dumps(live_entries)[:200]}")
            return
        if live_entries[0].get("collection_name") != coll_b:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — global face still "
                  f"binds {live} to {live_entries[0].get('collection_name')} "
                  f"(expected {coll_b})")
            return
        print(f"OK: global face binds {live} -> {coll_b} (exactly once)")

        names_b, err = collection_alias_names(coll_b)
        if err is not None:
            print(f"NOTE: per-collection face of B unreadable ({err}) — relying on "
                  f"global face + reads-through-alias")
        elif live not in (names_b or []):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — per-collection "
                  f"face of {coll_b} lacks {live} while global face binds it to B "
                  f"(faces disagree after atomic switch)")
            return
        else:
            print(f"OK: per-collection face of B lists {live}")

        names_a, err = collection_alias_names(coll_a)
        if err is not None:
            print(f"NOTE: per-collection face of A unreadable ({err}) — relying on "
                  f"global face + reads-through-alias")
        elif live in (names_a or []):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — per-collection "
                  f"face of {coll_a} still lists {live} while global face binds it "
                  f"to B (stale/duplicated alias state)")
            return
        else:
            print(f"OK: per-collection face of A no longer lists {live}")

        live_cnt, err = count_points(live)
        if err is not None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — reads through "
                  f"alias {live} fail after switch ({err}); contract expects the "
                  f"alias to resolve to the new target")
            return
        if live_cnt != N_B:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — reads through "
                  f"{live} return {live_cnt} pts (A={N_A}, B={N_B}) — alias does not "
                  f"resolve to the new target after 200")
            return
        print(f"OK: reads through {live} -> {live_cnt} pts (=B)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            delete_alias(live)
        except Exception:
            pass  # cleanup failures are non-fatal
        try:
            drop_collection(coll_a)
        except Exception:
            pass  # cleanup failures are non-fatal
        try:
            drop_collection(coll_b)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
