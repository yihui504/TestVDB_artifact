#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-input / character-boundary on the RAW REQUEST STREAM of
  cluster+collection+update (POST /collections/{collection_name}/cluster) x
  qdrant_behavioral_cluster_collection_update_001 (400 face). All probes are sent as raw
  bytes via data= (bypassing client-side JSON serialization — the safety wrapper required
  by the spec) so the DB's own parser behavior is what gets measured, on an EXISTING
  collection:
    truncated JSON | trailing comma | single-quoted keys | illegal escape \\q |
    JSON comment injection /* */ | bare NUL byte inside the stream |
    lone-surrogate escape \\ud800 (not a legal Unicode scalar) |
    overlong 1MB string value (resource-character boundary).
  The overlong probe has a widened legal oracle (4xx OR 2xx — no documented length limit;
  only a crash is a defect), the other seven demand a 4xx validation rejection.
  [chunk_cluster+collection+update coverage: strategy7 malformed-input x
   qdrant_behavioral_cluster_collection_update_001 — parser/character face]
Oracle: malformed-JSON/NUL/lone-surrogate probes -> 400/422 (robust 4xx handling); 2xx =
  Type1_IllegalSuccess (malformed input stream silently accepted); any 5xx / panic /
  internal-parser error leakage = Type3_RuntimeFailure with /healthz rechecked before the
  verdict; overlong-string probe -> 4xx or 2xx (both legal), 5xx = Type3; transport
  failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_behavioral_cluster_collection_update_001
Blindspot: BS-01 Parameter Type Coercion Trust (serde assumed to receive well-formed
  UTF-8 JSON; parser panic / silent-accept gaps at the encoding boundary)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+collection+update", method="POST",
  url="/collections/{collection_name}/cluster". Probe values are DB-neutral input-stream
  malformations (the generality red line: swapping targets keeps the construction valid).
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


# Declare-first oracle: malformed input streams must be 4xx-rejected, never 5xx/accepted.
EXPECT_STATUS = (400, 422)
CRASH_MARKERS = ("panic", "internal", "serde", "decode", "utf", "oom",
                 "out of memory", "capacity overflow")


def judge_probe(label, status, raw, widened=False):
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
                    f"and /healthz={hs} (service down); body: {str(raw)[:200]}")
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' got {status} "
                f"with /healthz={hs} alive; body: {str(raw)[:200]}")
    low = str(raw).lower()
    if any(k in low for k in CRASH_MARKERS):
        # Non-5xx body mentions parser/memory internals: recorded for the judge only —
        # a 4xx that names the parser is GOOD diagnostics, never a Type3 by itself.
        print(f"NOTE(judge): probe '{label}' body mentions parser/memory internals "
              f"(status={status}): {str(raw)[:200]}")
    if status in EXPECT_STATUS:
        return None  # robust 4xx handling of malformed input
    if 200 <= status < 300:
        if widened:
            print(f"NOTE: probe '{label}' accepted with 2xx (no documented length limit — "
                  f"legal handling, recorded for the judge)")
            return None
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) — probe '{label}': malformed input "
                f"stream silently accepted with 2xx {status}; body: {str(raw)[:200]}")
    if 400 <= status < 500:
        return None if widened else (
            f"DEFECT_FOUND (Type2_PoorDiagnostics) — probe '{label}': expected 400/422, "
            f"got {status}; body: {str(raw)[:200]}")
    return f"SCRIPT_ERROR — uninterpreted status {status} for probe '{label}'"


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bccu6" + tag
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
        # Act + Assert: raw malformed bodies via data= (bytes, client serializer bypassed).
        probes = [
            ("truncated JSON", False,
             b'{"move_shard": {"shard_id":'),
            ("trailing comma", False,
             b'{"move_shard": {"shard_id": 1,},}'),
            ("single-quoted keys", False,
             b"{'move_shard': {'shard_id': 1}}"),
            ("illegal escape \\q", False,
             b'{"move_shard": {"\\q": 1}}'),
            ("comment injection /* */", False,
             b'{"move_shard": /*comment*/ {"shard_id": 1}}'),
            ("bare NUL byte in stream", False,
             b'{"move_shard": {"shard_id\x00": 1}}'),
            ("lone-surrogate escape \\ud800", False,
             b'{"create_sharding_key": {"shard_key": "\\ud800"}}'),
            ("overlong 1MB string value", True,
             json.dumps({"create_sharding_key": {"shard_key": "x" * 1000000}}).encode("utf-8")),
        ]
        verdict = None
        for label, widened, body_bytes in probes:
            s, _, raw = safe_request("POST", f"/collections/{coll}/cluster",
                                     data=body_bytes, timeout=60)
            print(f"[probe {label}] -> status={s} raw={str(raw)[:200]}")
            v = judge_probe(label, s, raw, widened=widened)
            if v is not None and verdict is None:
                verdict = v

        if verdict is not None:
            print("VERDICT: " + verdict)
            return

        print("OK: malformed-input probes all handled with 4xx (no 5xx, no silent accept)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
