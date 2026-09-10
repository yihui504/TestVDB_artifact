#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy4 special-value on the QUERY PARAMETER `timeout` of
  cluster+collection+update (POST /collections/{collection_name}/cluster) x
  qdrant_behavioral_cluster_collection_update_001. The contract parameter list documents
  timeout as "query: min 1" — a numeric range constraint on a QUERY parameter (placement
  check per spec: query params ride params=, never the body; v34 R1 lesson). Both-direction
  pairing (G4): (a) positive control = timeout=60 (legal closure, well above min 1) with an
  acceptable carrier operation must return 200, proving the carrier itself is acceptable on
  this deployment; (b) negative probes = the sub-minimum boundary values {0, -1} and the
  type-confused value "abc" with the SAME carrier — any acceptance would mean the
  documented minimum is not enforced. Isolation: each probe uses a FRESH shard id so
  acceptance of one probe can never be masked by a collision with an earlier one.
  [chunk_cluster+collection+update coverage: strategy4 special-value(timeout) x
   qdrant_behavioral_cluster_collection_update_001 — query-parameter range face]
Oracle: timeout=0 / timeout=-1 / timeout="abc" -> 400 or 422 (documented min 1 / type
  validation); 2xx on any sub-minimum probe = Type1_IllegalSuccess (documented minimum not
  enforced — operation executed with an illegal timeout); 4xx other than 400/422 =
  Type2_PoorDiagnostics; 5xx = Type3_RuntimeFailure with /healthz rechecked; carrier
  control not 2xx on this deployment = SCRIPT_ERROR (timeout cannot be isolated).
Constraint: qdrant_behavioral_cluster_collection_update_001
Blindspot: BS-04 Boundary Default Optimism (query-parameter minimum assumed defaulted or
  clamped rather than validated) + BS-01 (string-typed numeric query param coercion trust)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+collection+update", method="POST",
  url="/collections/{collection_name}/cluster", parameters include
  {name: timeout, type: integer, required: false, description: "query: min 1"} ->
  timeout rides the query string (params=), never the body.
"""

import json
import os
import sys
import time
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
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md).
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


def drop_collection(name):
    try:
        safe_request("DELETE", f"/collections/{name}", params={"timeout": 60}, timeout=60)
    except Exception:
        pass  # cleanup failures are non-fatal


# Declare-first oracle: documented timeout minimum is 1 -> sub-minimum values are 400/422.
EXPECT_STATUS = (400, 422)


_fresh_counter = [0]


def fresh_shard_id():
    """Fresh, strictly-increasing explicit shard id (far above auto-assigned ids)."""
    _fresh_counter[0] += 1
    return 5100 + (int(time.time() * 1000) % 2900) + _fresh_counter[0]


def carrier_body(explicit=True):
    """Carrier operation body: create_sharding_key (accept-able on a single peer)."""
    if explicit:
        return {"create_sharding_key": {"shard_id": fresh_shard_id()}}
    return {"create_sharding_key": {}}


def judge_probe(label, status, raw):
    """Declare-first adjudication ladder for one probe. Returns verdict string or None."""
    if status <= 0:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' transport "
                    f"failure and /healthz={hs} (service down)")
        return "SCRIPT_ERROR — transport failure with healthy /healthz (no defect conclusion)"
    if 500 <= status <= 599:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' got {status} "
                    f"and /healthz={hs} (service down)")
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' got {status} "
                f"with /healthz={hs} alive")
    if status in EXPECT_STATUS:
        return None  # matches the documented min-1 validation face
    if 200 <= status < 300:
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) — probe '{label}': expected 400/422 "
                f"(timeout below documented minimum 1), got 2xx {status}; the operation "
                f"was executed with an illegal timeout value; body: {str(raw)[:200]}")
    if 400 <= status < 500:
        return (f"DEFECT_FOUND (Type2_PoorDiagnostics) — probe '{label}': expected 400/422, "
                f"got {status} (rejected on the wrong documented face); body: {str(raw)[:200]}")
    return f"SCRIPT_ERROR — uninterpreted status {status} for probe '{label}'"


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bccu5" + tag
    coll = pfx + "c"
    print(f"ownership prefix: {pfx}")

    # Arrange: create one collection (contract-required body: vectors VectorParams)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # Positive control: legal timeout (60 >= min 1) + acceptable carrier.
        # Try the explicit-shard carrier first, fall back to the auto-assign form;
        # whichever returns 200 becomes the carrier form for the isolation probes.
        carrier = None
        for form_name, body in (("explicit-shard", carrier_body(True)),
                                 ("auto-assign", carrier_body(False))):
            s, _, raw = safe_request("POST", f"/collections/{coll}/cluster",
                                     json=body, params={"timeout": 60}, timeout=30)
            print(f"[control timeout=60 carrier={form_name}] -> status={s} "
                  f"raw={str(raw)[:200]}")
            if s == 200:
                carrier = (form_name, body)
                break
            if 500 <= s <= 599:
                hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
                print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — control probe got "
                      f"{s} with /healthz={hs}")
                return
        if carrier is None:
            print("VERDICT: SCRIPT_ERROR — no acceptable carrier operation on this "
                  "deployment (both create_sharding_key forms non-2xx); timeout cannot "
                  "be isolated; no defect conclusion")
            return
        print(f"carrier validated: {carrier[0]} (200 at legal timeout=60)")

        # Act + Assert: sub-minimum / type-confused timeout values, same carrier form.
        verdict = None
        for label, tval in (("timeout=0 (min-1 boundary of documented minimum 1)", 0),
                            ("timeout=-1 (negative query value)", -1),
                            ("timeout='abc' (string-typed numeric query param)", "abc")):
            body = carrier_body(carrier[0] == "explicit-shard")
            s, _, raw = safe_request("POST", f"/collections/{coll}/cluster",
                                     json=body, params={"timeout": tval}, timeout=30)
            print(f"[probe {label}] -> status={s} raw={str(raw)[:200]}")
            v = judge_probe(label, s, raw)
            if v is not None and verdict is None:
                verdict = v

        if verdict is not None:
            print("VERDICT: " + verdict)
            return

        print("OK: timeout probes {0, -1, 'abc'} -> 400/422 (documented min 1 enforced)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
