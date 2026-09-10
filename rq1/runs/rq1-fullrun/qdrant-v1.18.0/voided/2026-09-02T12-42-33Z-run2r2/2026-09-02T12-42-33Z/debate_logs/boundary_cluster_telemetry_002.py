#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary attack (query-parameter serde coercion face) +
  strategy5 error-diagnostics quality on the timeout query parameter of
  cluster+telemetry (GET /cluster/telemetry) x qdrant_range_cluster_telemetry_001
  (evidence_tier explicit; parameter typing corroborated by the versioned
  v-1-18-x OpenAPI schema {type: integer, minimum: 1, default: 60}). The
  constraint's assertion, quoted verbatim:
    "timeout default 60, minimum 1"
  Class A (non-coercible type-invalid tokens): "abc", "", "1.5", "true",
  "1e3", " 1", "0x10" — each must be rejected 4xx; any 2xx means a
  type-invalid token was silently coerced = Type1_IllegalSuccess (BS-01
  parameter-coercion trust).
  Class B (sign-form "+1"): parses to the in-domain integer 1 under lenient
  integer grammars — declared conforming outcomes are 4xx (strict grammar) or
  200 (lenient grammar mapping to in-domain 1); ONLY 5xx is a defect there
  (no coercion claim is fabricated for a value that is in-domain either way).
  strategy5 leg: every class-A 4xx body must name the violated parameter
  ('timeout', case-insensitive); a generic unnamed rejection = Type2
  diagnostics finding.
[chunk_cluster+telemetry coverage: strategy2 type-confusion +
 strategy5 error-quality x qdrant_range_cluster_telemetry_001(timeout);
 strategy1 boundary matrix is covered by boundary_cluster_telemetry_001]
Oracle: class-A tokens {abc, empty, 1.5, true, 1e3, ' 1', 0x10} -> 4xx each;
  any 2xx = DEFECT_FOUND (Type1_IllegalSuccess — type-invalid timeout token
  silently coerced); class-B '+1' -> 4xx or 200 both conform, 5xx = DEFECT
  (Type3_RuntimeFailure with /healthz recheck); any class-A 4xx whose body
  does not mention 'timeout' = DEFECT_FOUND (Type2_PoorDiagnostics); 5xx on
  class A with /healthz alive = DEFECT (Type3_RuntimeFailure); transport
  failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_range_cluster_telemetry_001
Blindspot: BS-01 Parameter Type Coercion Trust (serde-based query parsing
  trusted to reject non-integer tokens; validation gaps admit them silently)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-telemetry
doc_version: 1.18.x (versioned v-1-18-x api-reference)
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

AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")


def derive_url(path_key):
    """R5/R6 standing lesson: URLs come only from raw_knowledge api_endpoints[].url."""
    for _p in Path(__file__).resolve().parents:
        _rk = _p / "raw_knowledge.json"
        if _rk.exists():
            try:
                for _e in json.loads(_rk.read_text(encoding="utf-8")).get("api_endpoints", []):
                    if _e.get("path") == path_key and _e.get("url"):
                        return _e["url"]
            except Exception:
                return None
            return None
    return None


CLUSTER_TELEMETRY_URL = derive_url("cluster+telemetry")
if not CLUSTER_TELEMETRY_URL:
    print("VERDICT: SCRIPT_ERROR — url not derivable from raw_knowledge api_endpoints[].url (cluster+telemetry)")
    sys.exit(2)
print(f"[url-derived] cluster+telemetry -> {CLUSTER_TELEMETRY_URL}")


def safe_request(method, endpoint, json=None, params=None, data=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md).
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
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


def healthz_ladder(label, attempts=3, delay=2):
    """G8 liveness re-check: /healthz gets 3 attempts 2s apart before any Type3
    conclusion (transport-branch probe; standing lesson)."""
    for i in range(attempts):
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    # NOTE: returns a BARE Type3 message (no DEFECT_FOUND prefix — the caller's
    # verdict wrapper adds it exactly once).
    return (f"Type3_RuntimeFailure(service-down) — '{label}': /healthz unreachable "
            f"after {attempts} attempts")


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: bct2-{tag}")
    print("[constraint quote] timeout default 60, minimum 1 — parameter typing per "
          "OpenAPI {type: integer, minimum: 1, default: 60}")

    class_a = ["abc", "", "1.5", "true", "1e3", " 1", "0x10"]  # non-coercible type-invalid tokens
    class_b = ["+1"]                                           # sign form, in-domain either way

    findings = []  # (rank, message); 0 = Type1, 1 = Type3, 2 = Type2
    type2_missing = []

    for token in class_a:
        s, b, r = safe_request("GET", CLUSTER_TELEMETRY_URL, params={"timeout": token}, timeout=15)
        print(f"[class-A timeout={token!r}] status={s} raw={str(r)[:300]}")
        if s <= 0:
            v = healthz_ladder(f"class-A {token!r}")
            if v:
                findings.append((1, v))
                break
            findings.append((3, f"SCRIPT-ERROR-transport: class-A {token!r} transport failure with healthy /healthz"))
            break
        if 500 <= s <= 599:
            v = healthz_ladder(f"class-A {token!r}")
            findings.append((1, v if v else f"Type3_RuntimeFailure: class-A {token!r} got {s} with /healthz alive; body: {str(r)[:200]}"))
            continue
        if 200 <= s <= 299:
            findings.append((0, f"Type1_IllegalSuccess: timeout={token!r} ACCEPTED with {s} — type-invalid "
                                f"token for the documented integer parameter silently coerced; raw: {str(r)[:200]}"))
            continue
        if 400 <= s <= 499:
            print(f"[conform] timeout={token!r} rejected with {s}")
            if "timeout" not in str(r).lower():
                type2_missing.append(f"timeout={token!r} -> {s}: {str(r)[:120]}")
        else:
            findings.append((3, f"SCRIPT-ERROR-status: class-A {token!r} uninterpreted status {s}"))

    for token in class_b:
        s, b, r = safe_request("GET", CLUSTER_TELEMETRY_URL, params={"timeout": token}, timeout=15)
        print(f"[class-B timeout={token!r}] status={s} raw={str(r)[:300]}")
        if s <= 0:
            v = healthz_ladder(f"class-B {token!r}")
            if v:
                findings.append((1, v))
            else:
                findings.append((3, f"SCRIPT-ERROR-transport: class-B {token!r} transport failure with healthy /healthz"))
        elif 500 <= s <= 599:
            v = healthz_ladder(f"class-B {token!r}")
            findings.append((1, v if v else f"Type3_RuntimeFailure: class-B {token!r} got {s} with /healthz alive; body: {str(r)[:200]}"))
        elif 200 <= s <= 299 or 400 <= s <= 499:
            print(f"[conform-record] class-B {token!r} disposition {s} (strict 4xx / lenient-200 both "
                  f"declared conforming — sign grammar is not a contract claim)")
        else:
            findings.append((3, f"SCRIPT-ERROR-status: class-B {token!r} uninterpreted status {s}"))

    if type2_missing:
        findings.append((2, "Type2_PoorDiagnostics: 4xx rejections of type-invalid timeout tokens do not "
                            "name the violated parameter ('timeout' absent from body): "
                            + " | ".join(type2_missing)))

    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR — {msg}")
        else:
            print(f"VERDICT: DEFECT_FOUND ({msg})")
        return
    print("OK: every type-invalid token rejected 4xx with parameter-naming diagnostics; sign form disposed without crash")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
