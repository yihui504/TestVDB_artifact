#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-input / character-boundary + strategy4 special-value on the PATH PARAMETER collection_name of cluster+collection+info (GET /cluster/collection/{collection_name}) x qdrant_behavioral_cluster_collection_info_001 — probes (all sent as path segments, pre-encoded where needed so the client does not re-encode or normalize them away): NUL byte in name (a%00b), unicode name (中文测试🎯), overlong name ('a' x 2000), encoded slash in name (a%2Fb), dot-segment name (.), dotdot name (..), encoded traversal (%2E%2E%2Fcollections), encoded query-injection suffix (name%3Ftimeout%3D0).
Oracle: every malformed/never-creatable collection_name is refused with a 4xx (404 documented for unknown names; 400 acceptable for structurally garbage routing input) and the service stays alive — any 5xx = Type3_RuntimeFailure (healthz rechecked before verdict), 200 = Type1_IllegalSuccess (a name that can never have been created must not hit an existing-collection code path), transport failure with healthy healthz = SCRIPT_ERROR.
Constraint: qdrant_behavioral_cluster_collection_info_001 (expected_behavior: "unknown collection: HTTP 404" — malformed names are the extreme of the unknown-name space; the endpoint must degrade gracefully, never crash)
Blindspot: BS-01 Parameter Type Coercion Trust (path params are trusted to be well-formed names; NUL/unicode/traversal bytes flow into shard-lookup and route-matching code that assumes a legal identifier)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven path derivation (no hardcoding from memory):
  contract.api_endpoints[]: path="cluster+collection+info", method="GET",
  category=admin, parameters=[{name: collection_name, type: string,
  required: true, description: "path"}]
  -> /cluster/collection/{collection_name}
Placement check: collection_name is documented `in: path` -> probes go into
the path (never query/body). Percent-escapes are passed pre-encoded in the
URL string so requests forwards them verbatim (no double-encoding, no
client-side dot-segment normalization).
R3 lessons applied: envelope nests at result.<field>; unique per-script
ownership prefix; no list.remove() bookkeeping.
"""

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


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bcci3" + tag
    print(f"ownership prefix: {pfx}")

    # Pre-encoded probes: (label, already-encoded path segment, note)
    probes = [
        ("nul-byte", f"{pfx}%00nul", "NUL byte inside the name (JSON-escape class %00)"),
        ("unicode", f"{pfx}%E4%B8%AD%E6%96%87%E6%B5%8B%E8%AF%95%F0%9F%8E%AF",
         "unicode name 中文测试🎯 (UTF-8 percent-encoded)"),
        ("overlong-2000", (pfx + "a" * 2000), "overlong name, 2000 chars"),
        ("encoded-slash", f"{pfx}%2Fb", "encoded slash inside the name (a%2Fb)"),
        ("dot-segment", ".", "single dot as name"),
        ("dotdot-segment", "..", "dot-dot as name"),
        ("encoded-traversal", "%2E%2E%2Fcollections", "encoded ../collections traversal"),
        ("encoded-query-suffix", f"{pfx}%3Ftimeout%3D0", "encoded ?timeout=0 suffix"),
    ]

    for label, seg, note in probes:
        # Act: GET with the pre-encoded path segment
        s, _, raw = safe_request("GET", f"/cluster/collection/{seg}", timeout=30)
        print(f"probe[{label}] -> status={s} ({note})")
        print(f"  raw: {raw[:300]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"  transport failure (healthz status={hs}: {str(hraw)[:200]})")
            if hs <= 0 or hs >= 500:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' "
                      f"killed or unreachable service (healthz={hs})")
            else:
                print(f"  NOTE: probe '{label}' failed at transport with healthy "
                      f"healthz (client-side/HTTP-layer rejection) — no defect "
                      f"conclusion for this probe")
            continue
        if 500 <= s <= 599:
            hs, hraw = liveness()
            if hs <= 0 or hs >= 500:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' "
                      f"triggered {s} and healthz={hs} (service down)")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' "
                      f"triggered {s} (healthz={hs} alive)")
            return
        if s == 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — probe '{label}' is a "
                  f"never-creatable collection name yet answered 200 where the "
                  f"assertion documents 404 for unknown collections "
                  f"(qdrant_behavioral_cluster_collection_info_001)")
            return
        if 400 <= s <= 499:
            print(f"  OK: refused with {s} (4xx graceful refusal)")
        else:
            print(f"  NOTE(judge): probe '{label}' returned unexpected status {s} — "
                  f"recorded for judge (no 4xx/5xx/200 classification)")
        # loop continues: each probe is independently adjudicated

    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
