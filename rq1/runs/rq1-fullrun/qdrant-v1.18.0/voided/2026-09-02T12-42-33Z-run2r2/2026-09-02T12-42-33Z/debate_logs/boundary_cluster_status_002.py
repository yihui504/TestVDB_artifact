#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-input / character-boundary fuzzing on EVERY input
  channel of cluster+status (GET /cluster) x qdrant_behavioral_cluster_status_001
  (verbatim: "returns 200 with cluster info; valid on single-node deployments";
  co-anchored to qdrant_type_cluster_status_001 for the 200-payload grid).
  The contract declares parameters:[] — NO body, NO query — so every input
  form below is out-of-contract and the documented 200 promise must hold
  under all of them (unconditional face). Matrix:
    documented no-input control (R7 lesson: decisive body-independence anchor)
    | malformed JSON bodies (truncated / trailing comma / single quotes /
      comment / extra brace) | NUL byte body | lone-surrogate escape body |
      1MB overlong body (resource-limit flavor — strategy6 has no standalone
      numeric-limit parameter on this endpoint, its resource face folds here)
    | query faces: peer_id=abc (BS-01 type confusion), peer_id=-1 (uint64
      boundary), commit_index=uint64+1 (18446744073709551616), RTL+BOM
      unicode, 100k overlong value, pre-encoded %00 NUL, pre-encoded lone
      surrogate %ED%A0%80.
  [chunk_cluster+status coverage: strategy7 malformed-input x
   qdrant_behavioral_cluster_status_001 (+ type co-anchor); strategy1/3 no
   applicable numeric/vector parameter on this endpoint]
Oracle: every probe -> 200 with result JSON-EQUAL to the no-input control
  (input-independence: no documented input exists to influence the result)
  OR a clean 4xx (e.g. 414 for the overlong query) — any 5xx = DEFECT_FOUND
  Type3_RuntimeFailure (healthz rechecked 3 attempts first); a 200 whose
  result DIFFERS from the control = DEFECT_FOUND Type4_StateLogicViolation
  (undocumented input-sensitivity of an input-free endpoint); transport
  failure with healthy /healthz = SCRIPT_ERROR; no 2xx/3xx/4xx/5xx
  interpretation = SCRIPT_ERROR honest exit.
Constraint: qdrant_behavioral_cluster_status_001 (+ qdrant_type_cluster_status_001)
Blindspot: BS-01 Parameter Type Coercion Trust (plausible-but-undocumented
  query fields may still reach internal deserialization; NUL/surrogate may
  hit unguarded serde paths — the R7 sibling face proved a 500 can hide here)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-status
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4/R5 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+status", method="GET",
  url="/cluster", parameters=[] — derived at runtime from raw_knowledge.json
  (parent walk, no hardcoded path). R7 lesson consumed verbatim: a documented
  no-input control probe beside every malformed matrix is the decisive
  evidence — on the sibling recover face it proved the 500 was body-
  independent; here the control anchors the result-equality oracle. Raw
  malformed bytes go through data= (never json=) so client-side serialization
  cannot pre-reject them; pre-encoded %00/%ED%A0%80 are appended to the
  endpoint string because requests cannot encode NUL/lone surrogates in params.
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


CLUSTER_STATUS_URL = derive_url("cluster+status")
if not CLUSTER_STATUS_URL:
    print("VERDICT: SCRIPT_ERROR — url not derivable from raw_knowledge api_endpoints[].url (cluster+status)")
    sys.exit(2)
print(f"[url-derived] cluster+status -> {CLUSTER_STATUS_URL}")


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
    conclusion (transport-branch probe; standing lesson). Returns a Type3
    verdict string if the service is down, else None."""
    for i in range(attempts):
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}': /healthz unreachable "
            f"after {attempts} attempts (service down)")


def parse_result(raw):
    """Envelope-aware result extraction; returns (result, None) or (None, error)."""
    try:
        node = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(node, dict) and "result" in node:
            return node["result"], None
        return None, f"200 without envelope result key: {str(raw)[:150]}"
    except Exception as e:
        return None, f"200 body not parseable JSON ({e}): {str(raw)[:150]}"


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: bcs2-{tag}")

    # Arrange: documented no-input control (R7 lesson — decisive anchor).
    cs, _, craw = safe_request("GET", CLUSTER_STATUS_URL, timeout=15)
    print(f"[control GET {CLUSTER_STATUS_URL}] status={cs} raw={str(craw)[:300]}")
    if cs <= 0:
        v = healthz_ladder("control GET /cluster")
        print("VERDICT: " + (v if v else "SCRIPT_ERROR — control transport failure with healthy /healthz (no defect conclusion)"))
        return
    if not (200 <= cs <= 299):
        # Non-200 control = the endpoint's documented face itself is broken; that
        # phenomenon belongs to boundary_cluster_status_001's grid script — here it
        # is a setup precondition, honest exit without a defect conclusion.
        print(f"VERDICT: SCRIPT_ERROR — control call returned {cs} (setup precondition failed; "
              f"the 200-face phenomenon is adjudicated by boundary_cluster_status_001)")
        return
    ctrl_result, err = parse_result(craw)
    if ctrl_result is None:
        print(f"VERDICT: SCRIPT_ERROR — control 200 body unusable as equality anchor ({err})")
        return
    print(f"[control result] {json.dumps(ctrl_result, ensure_ascii=False)[:200]}")

    # Act: malformed / out-of-contract input matrix on both input channels.
    body_probes = [
        ("malformed: truncated JSON", b'{"a":1'),
        ("malformed: trailing comma", b'{"a":1,}'),
        ("malformed: single quotes", b"{'a':1}"),
        ("malformed: comment", b'{"a":1} // x'),
        ("malformed: extra closing brace", b'{"a":1}}'),
        ("NUL byte in body", b'{"x":"a\x00b"}'),
        ("lone-surrogate escape in body", b'{"x":"\\ud800"}'),
        ("1MB overlong body", b'{"pad":"' + b"a" * 1_000_000 + b'"}'),
    ]
    query_probes = [
        ("query peer_id=abc (type confusion)", {"peer_id": "abc"}),
        ("query peer_id=-1 (uint64 boundary)", {"peer_id": "-1"}),
        ("query commit_index=uint64+1", {"commit_index": "18446744073709551616"}),
        ("query RTL+BOM unicode", {"k": "‮﻿"}),
        ("query 100k overlong value", {"pad": "a" * 100_000}),
    ]
    encoded_query_probes = [
        ("query NUL pre-encoded %00", CLUSTER_STATUS_URL + "?pad=%00A"),
        ("query lone-surrogate pre-encoded %ED%A0%80", CLUSTER_STATUS_URL + "?k=%ED%A0%80"),
    ]

    verdict = None
    notes = []

    def judge_probe(label, status, raw):
        """Declare-first adjudication for one probe. Returns verdict string or None."""
        nonlocal verdict
        if status <= 0:
            v = healthz_ladder(label)
            if v is not None:
                return v
            return "SCRIPT_ERROR — transport failure with healthy /healthz (no defect conclusion)"
        if 500 <= status <= 599:
            v = healthz_ladder(label)
            if v is not None:
                return v
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' got {status} with /healthz "
                    f"alive; the documented 200 face of cluster+status must hold for out-of-contract "
                    f"input too; body: {str(raw)[:200]}")
        if 200 <= status <= 299:
            res, err = parse_result(raw)
            if res is None:
                return (f"DEFECT_FOUND (Type4_StateLogicViolation) — probe '{label}' returned 200 but "
                        f"broke the envelope ({err})")
            if res != ctrl_result:
                return (f"DEFECT_FOUND (Type4_StateLogicViolation) — probe '{label}' returned 200 with a "
                        f"result DIFFERENT from the no-input control (undocumented input-sensitivity of an "
                        f"endpoint that documents zero parameters): control="
                        f"{json.dumps(ctrl_result, ensure_ascii=False)[:120]} vs probe="
                        f"{json.dumps(res, ensure_ascii=False)[:120]}")
            return None  # input-independent 200 — the promise held
        if 400 <= status <= 499:
            notes.append(f"'{label}' -> clean 4xx reject ({status})")
            return None
        return f"SCRIPT_ERROR — uninterpreted status {status} for probe '{label}' (honest exit)"

    for label, payload in body_probes:
        s, _, raw = safe_request("GET", CLUSTER_STATUS_URL, data=payload, timeout=60)
        print(f"[probe {label!r}] -> status={s} raw={str(raw)[:180]}")
        v = judge_probe(label, s, raw)
        if v is not None and verdict is None:
            verdict = v

    for label, qp in query_probes:
        s, _, raw = safe_request("GET", CLUSTER_STATUS_URL, params=qp, timeout=60)
        print(f"[probe {label!r}] -> status={s} raw={str(raw)[:180]}")
        v = judge_probe(label, s, raw)
        if v is not None and verdict is None:
            verdict = v

    for label, endpoint in encoded_query_probes:
        s, _, raw = safe_request("GET", endpoint, timeout=60)
        print(f"[probe {label!r}] -> status={s} raw={str(raw)[:180]}")
        v = judge_probe(label, s, raw)
        if v is not None and verdict is None:
            verdict = v

    if verdict is not None:
        print("VERDICT: " + verdict)
        return

    for n in notes:
        print(f"NOTE(legal-reject): {n}")
    print(f"OK: control + {len(body_probes) + len(query_probes) + len(encoded_query_probes)} "
          f"malformed/out-of-contract probes — every 200 result JSON-equal to the control, "
          f"every reject a clean 4xx, no 5xx (R7 control-probe methodology: result equality "
          f"probes input-independence deterministically)")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
