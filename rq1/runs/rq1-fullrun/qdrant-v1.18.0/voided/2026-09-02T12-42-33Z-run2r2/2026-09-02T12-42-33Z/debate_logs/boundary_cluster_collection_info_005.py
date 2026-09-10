#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy5 error-message quality (Type-2) on the documented 404 of cluster+collection+info (GET /cluster/collection/{collection_name}) x qdrant_behavioral_cluster_collection_info_001 — paired positive control (existing collection -> 200) then unknown-name probe: the 404 diagnostics must let a developer locate the problem, i.e. the raw response text must reference the offending collection name (case-insensitive) OR carry an explicit not-found phrase ("not found" / "doesn't exist" / "does not exist" / "not exist" / "no such" / "unknown"). By-design guard (threat model): error ENVELOPE field names (status/time/error) are NOT part of the contract — adjudication scans the raw text only and demands no specific field structure.
Oracle: positive control existing collection -> 200 (else SCRIPT_ERROR); unknown collection -> HTTP 404 whose raw text contains the queried collection name (case-insensitive) or a not-found phrase — an empty body, or a 404 text naming neither the collection nor the not-found condition, = Type2_PoorDiagnostics (error cannot help locate the violated parameter); 200 on the unknown name = Type1_IllegalSuccess (assertion documents 404); 5xx = Type3_RuntimeFailure (healthz rechecked).
Constraint: qdrant_behavioral_cluster_collection_info_001 (expected_behavior: "unknown collection: HTTP 404") + strategy-5 diagnostics criterion (error should name the violated parameter or state the problem)
Blindspot: BS-02 Error Message Negligence (generic/empty not-found bodies considered acceptable; 404 is treated as self-explanatory even when several path parameters could be at fault)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven path derivation (no hardcoding from memory):
  contract.api_endpoints[]: path="cluster+collection+info", method="GET",
  category=admin, parameters=[{name: collection_name, type: string,
  required: true, description: "path"}]
  -> /cluster/collection/{collection_name}
Setup face (collections+create) from contract: PUT /collections/{name}
with vectors = VectorParams{size, distance}; delete face DELETE /collections/{name}.
R3 lessons applied: envelope nests at result.<field>; unique per-script
ownership prefix; no list.remove() bookkeeping.
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

# Not-found phrase lexicon for the strategy-5 scan (raw-text scan only; the
# threat model marks error-envelope field names as non-contract, so no field
# structure is demanded).
NOT_FOUND_PHRASES = [
    "not found",
    "doesn't exist",
    "does not exist",
    "not exist",
    "no such",
    "unknown",
]


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


def drop_collection(name):
    try:
        safe_request("DELETE", f"/collections/{name}", params={"timeout": 60}, timeout=60)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bcci5" + tag
    coll = pfx + "c1"
    missing = pfx + "_no_such_collection"
    print(f"ownership prefix: {pfx}")

    # Arrange: existing collection as positive control
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # Positive control: endpoint alive and answering 200 for existing name
        s, _, raw = safe_request("GET", f"/cluster/collection/{coll}", timeout=30)
        print(f"positive control [{coll}] -> status={s}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"transport failure (healthz status={hs}: {str(hraw)[:200]})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if s != 200:
            print(f"VERDICT: SCRIPT_ERROR — existing-collection face returned {s}; "
                  f"diagnostics probe not meaningful")
            return
        print("  OK: existing collection answered 200")

        # Act: unknown collection -> documented 404; adjudicate its diagnostics
        s, _, raw = safe_request("GET", f"/cluster/collection/{missing}", timeout=30)
        print(f"unknown [{missing}] -> status={s}")
        print(f"  raw: {raw[:400]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"transport failure (healthz status={hs}: {str(hraw)[:200]})")
            if hs <= 0 or hs >= 500:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — unknown-name "
                      f"lookup killed the service (healthz={hs})")
            else:
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            hs, hraw = liveness()
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — unknown collection "
                  f"yielded {s} (healthz={hs})")
            return
        if s == 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — unknown collection "
                  f"'{missing}' answered 200 where the assertion documents 404")
            return
        if s != 404:
            print(f"NOTE(judge): unknown collection answered {s}, not the documented "
                  f"404 — adjudicating diagnostics on the returned refusal body")
            if not (400 <= s <= 499):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s}")
                return

        # Assert (strategy 5): can a developer locate the problem from the text?
        text = (raw or "").strip().lower()
        if not text:
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — {s} refusal has an "
                  f"EMPTY body: names neither the collection nor the not-found "
                  f"condition (strategy-5 criterion violated)")
            return
        names_param = missing.lower() in text
        has_phrase = any(p in text for p in NOT_FOUND_PHRASES)
        if names_param or has_phrase:
            how = "names the collection" if names_param else "carries a not-found phrase"
            print(f"  OK: {s} diagnostics {how} — locatable")
        else:
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — {s} refusal body "
                  f"names neither the queried collection nor a not-found condition; "
                  f"a developer cannot locate the violated parameter from: "
                  f"{raw[:200]}")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
