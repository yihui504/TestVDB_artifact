#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: boundary/atomicity + missing-param (strategy 1/2) on aliases+update semantic edges
Constraint: qdrant_state_aliases_update_001 + qdrant_bc_alias_atomic_switch_001
Endpoint: POST /collections/aliases (contract path: aliases+update)
exploration_target: novel_candidate
Block: chunk_aliases+update
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
doc_version: 1.18.x (versioned)
By-design avoided: none of the listed by-design behaviors cover aliases.
"""

import requests
import json
import sys
import os

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
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else {}
        except (json.JSONDecodeError, ValueError):
            print(f"JSON_DECODE_ERROR: {text[:200]}")
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""


def cleanup():
    for c in ("bnd_ali_bd_c1", "bnd_ali_bd_c2"):
        try:
            safe_request("DELETE", f"/collections/{c}")
        except Exception:
            pass


def test_missing_and_atomicity():
    ok = True
    for c in ("bnd_ali_bd_c1", "bnd_ali_bd_c2"):
        s, _, raw = safe_request("PUT", f"/collections/{c}",
                                 json={"vectors": {"size": 4, "distance": "Cosine"}})
        if s not in (200, 201):
            print(f"setup create {c} failed: {s} {raw[:200]}")
            ok = False
    setup_ok = ok

    defect = False

    # missing required fields
    cases = [
        ("missing_body", None),
        ("empty_object", {}),
        ("action_missing_alias", {"actions": [{"create_alias": {"collection_name": "bnd_ali_bd_c1"}}]}),
        ("action_missing_collection", {"actions": [{"create_alias": {"alias": "bnd_ali_bd_x1"}}]}),
        ("rename_missing_new", {"actions": [{"rename_alias": {"old_alias": "nonexistent"}}]}),
        ("unknown_action_type", {"actions": [{"explode_alias": {"alias": "x"}}]}),
        ("empty_action_object", {"actions": [{}]}),
        # boundary: timeout values
        ("timeout=0", {"actions": [{"create_alias": {"collection_name": "bnd_ali_bd_c1", "alias": "bnd_ali_bd_t0"}}], "timeout": 0}),
        ("timeout=-1", {"actions": [{"create_alias": {"collection_name": "bnd_ali_bd_c1", "alias": "bnd_ali_bd_tm1"}}], "timeout": -1}),
    ]
    for name, payload in cases:
        kwargs = {} if payload is None else {"json": payload}
        status, body, raw = safe_request("POST", "/collections/aliases", **kwargs)
        print(f"CASE {name}: status={status} body={raw[:300]}")
        if status == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            return
        if status in (500, 502, 503) or "panic" in raw.lower():
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {name} triggered 5xx")
            defect = True

    # atomicity probe: batch with one invalid op — either all-or-nothing per doc
    if setup_ok:
        payload = {"actions": [
            {"create_alias": {"collection_name": "bnd_ali_bd_c1", "alias": "bnd_ali_bd_atom_ok"}},
            {"create_alias": {"collection_name": "no_such_collection_xyz", "alias": "bnd_ali_bd_atom_bad"}},
        ]}
        status, body, raw = safe_request("POST", "/collections/aliases", json=payload)
        print(f"CASE mixed_batch: status={status} body={raw[:300]}")
        if status in (200, 201):
            # check whether the valid op was applied despite batch failure semantics
            s2, b2, r2 = safe_request("GET", "/aliases")
            applied = "bnd_ali_bd_atom_ok" in r2
            print(f"NOTE mixed_batch: 200 with partial apply={applied} — atomic semantics check (judge-doc)")
            try:
                safe_request("POST", "/collections/aliases",
                             json={"actions": [{"delete_alias": {"alias": "bnd_ali_bd_atom_ok"}}]})
            except Exception:
                pass

    if not defect:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        test_missing_and_atomicity()
    finally:
        cleanup()
