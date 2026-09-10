#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_telemetry_004
# strategy: count_consistency
# endpoint: cluster+telemetry
# constraint_ids: qdrant_range_cluster_telemetry_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-telemetry
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: state-view consistency matrix across the documented timeout query
  parameter family of GET /cluster/telemetry (cluster+telemetry; URL read
  verbatim from raw_knowledge api_endpoints[].url and registered into
  rt.PATHS). The range constraint fixes the family: timeout default 60,
  minimum 1. The timeout parameter is a wait budget, not a view selector —
  no deployment change occurs in this script — so every LEGAL family member
  must return the SAME disposition (200, per the behavioral face) with the
  SAME telemetry state-view fingerprint (result key set, cluster.enabled,
  cluster.number_of_peers); inconsistent disposition or view across legal
  members = Type4_StateLogicViolation (G9: same family, inconsistent
  handling). Positive legs (G4 boundary closure): absent param (default),
  timeout=60 (the documented default value), timeout=1 (the documented
  minimum itself — min closure must be ACCEPTED). Negative legs:
  timeout=0 and timeout=-1 (below the documented minimum 1) must be
  rejected 4xx; a 200 on a sub-minimum member is Type1_IllegalSuccess
  (not refusing when it should refuse), and if the illegally-accepted call
  additionally returns a DIFFERENT state view than the baseline, the
  stronger Type4_StateLogicViolation is recorded. 5xx anywhere = Type3 only
  after /healthz liveness; transport failure = inline /healthz probe. Tail:
  after the negative legs the default face must still be 200 with the
  baseline fingerprint — a read-only refused request must leave no state
  damage. R8 lesson applied: shape checks grade only materialized grid
  sections; the hard core is 200 + result-object envelope.
  [chunk_cluster+telemetry coverage: count_consistency (param-family
  state-view consistency matrix + sub-minimum refusal) x
  qdrant_range_cluster_telemetry_001 (timeout default 60 / minimum 1) with
  the 200 disposition face of qdrant_behavioral_cluster_telemetry_001]
Oracle: absent-param, timeout=60 and timeout=1 all return 200 with result
  an object whose fingerprint (result key set, cluster.enabled,
  cluster.number_of_peers) is identical across the three legal members
  (non-200 on a legal member, or fingerprint divergence =
  Type4_StateLogicViolation); timeout=0 and timeout=-1 return HTTP 4xx
  (200 = Type1_IllegalSuccess; a differing state view on an accepted
  sub-minimum call = Type4_StateLogicViolation; 5xx = Type3_RuntimeFailure
  only after /healthz 200); after the negative legs the default face
  returns 200 with the baseline fingerprint (state damage = Type4)
"""

import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p / "scripts")
            break
if not _sd or not Path(_sd, "runtime", "__init__.py").exists():
    print("VERDICT: SCRIPT_ERROR - runtime scripts dir not found (TESTVDB_SCRIPTS_DIR unset)")
    sys.exit(2)
sys.path.insert(0, _sd)

if not os.environ.get("TESTVDB_TARGET"):
    for _p in Path(__file__).resolve().parents:
        _c = _p / "structured_contract.json"
        if _c.exists():
            try:
                _t = json.loads(_c.read_text(encoding="utf-8")).get("target", "")
                if _t:
                    os.environ["TESTVDB_TARGET"] = str(_t).lower()
            except Exception:
                pass
            break

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)


def load_telemetry_template():
    """Standing lesson: derive the URL only from raw_knowledge
    api_endpoints[].url (entry with path == "cluster+telemetry")."""
    for _p in Path(__file__).resolve().parents:
        _rk = _p / "raw_knowledge.json"
        if _rk.exists():
            try:
                for _e in json.loads(_rk.read_text(encoding="utf-8")).get("api_endpoints", []):
                    if _e.get("path") == "cluster+telemetry" and _e.get("url"):
                        return _e["url"]
            except Exception:
                return None
    return None


_TLM_TPL = load_telemetry_template()
if not _TLM_TPL:
    print("VERDICT: SCRIPT_ERROR - cluster+telemetry url not derivable from raw_knowledge api_endpoints[].url")
    sys.exit(2)
rt.PATHS["cluster_telemetry"] = _TLM_TPL
print(f"[url-derived] cluster+telemetry -> {_TLM_TPL} (raw_knowledge api_endpoints[].url)")


def safe_request(method, path_key, body=None, path_params=None,
                query_params=None, timeout=30):
    """All HTTP through the runtime; forwards timeout/path_params/body/
    query_params exactly (R7 standing lesson; the server-side timeout lives
    in query_params, the HTTP-client budget in the timeout kwarg — never
    conflated). Inline liveness probes (GET healthz) stay in this exact
    call form for static-check visibility."""
    return rt.request(method, path_key, body=body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def alive():
    """Liveness re-check via the lightweight documented health endpoint."""
    hs, hraw = safe_request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_view(raw):
    """result.<field> envelope (standing lesson)."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return None, f"unparseable body ({e})"
    if not isinstance(b, dict):
        return None, "top-level body not an object"
    node = b.get("result")
    if not isinstance(node, dict):
        return None, "result envelope not an object"
    return node, None


def fingerprint(node):
    """State-view fingerprint: (result key set, cluster.enabled,
    cluster.number_of_peers)."""
    keys = frozenset(node.keys()) if isinstance(node, dict) else None
    cl = node.get("cluster") if isinstance(node, dict) else None
    enabled = cl.get("enabled") if isinstance(cl, dict) else None
    npeers = cl.get("number_of_peers") if isinstance(cl, dict) else None
    return (keys, enabled, npeers)


def describe_fp(fp):
    if fp is None:
        return "None"
    return (f"keys={sorted(fp[0]) if fp[0] else None} "
            f"enabled={fp[1]!r} npeers={fp[2]!r}")


def probe(label, qp):
    """One family probe. Returns (status, raw, fp|None, fatal)."""
    s, raw = safe_request("GET", "cluster_telemetry", query_params=qp)
    print(f"[{label}] status={s} raw={raw[:300]}")
    if s == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[{label} transport] /healthz probe status={hs} "
              f"raw={str(hraw)[:120]}")
        return s, raw, None, hs != 200
    return s, raw, None, False


def main():
    DEFECTS = []

    # legal family members: absent param (default), documented default value,
    # documented minimum closure (G4: the min itself must be accepted)
    LEGAL = [
        ("default(absent)", None),
        ("timeout=60(documented default value)", {"timeout": "60"}),
        ("timeout=1(documented minimum closure)", {"timeout": "1"}),
    ]
    # sub-minimum members: below the documented minimum 1 -> must be refused
    NEG = [
        ("timeout=0(below documented minimum)", {"timeout": "0"}),
        ("timeout=-1(below documented minimum)", {"timeout": "-1"}),
    ]

    try:
        # ---- baseline: absent-param default face ----
        s0, raw0, _fp0, fatal0 = probe("baseline default(absent)", None)
        if fatal0:
            return "SCRIPT_ERROR"
        if s0 != 200:
            print(f"SETUP_ERROR: baseline telemetry = {s0}")
            return "SCRIPT_ERROR"
        node0, err0 = parse_view(raw0)
        if node0 is None:
            print(f"SETUP_ERROR: baseline result not an object: {err0}")
            return "SCRIPT_ERROR"
        base_fp = fingerprint(node0)
        print(f"[baseline fingerprint] {describe_fp(base_fp)}")

        # ---- positive legs: legal members must agree on disposition + view ----
        legal_fps = {}
        for label, qp in LEGAL[1:]:
            s, raw, _fp, fatal = probe(label, qp)
            if fatal:
                return "SCRIPT_ERROR"
            if 500 <= s <= 599:
                if alive():
                    DEFECTS.append(
                        f"({label}) legal in-range timeout returned {s} — "
                        f"validation failure surfaced as an internal error — "
                        f"Type3_RuntimeFailure — raw={raw[:200]}"
                    )
                else:
                    return "SCRIPT_ERROR"
                continue
            if s != 200:
                DEFECTS.append(
                    f"({label}) legal in-range timeout returned {s} — the "
                    f"family's documented disposition is 200 (absent-param "
                    f"baseline returned 200) — inconsistent family "
                    f"disposition — Type4_StateLogicViolation — "
                    f"raw={raw[:200]}"
                )
                continue
            node, err = parse_view(raw)
            if node is None:
                DEFECTS.append(
                    f"({label}) 200 but {err} — promised telemetry result "
                    f"object — Type4_StateLogicViolation — raw={raw[:200]}"
                )
                continue
            legal_fps[label] = fingerprint(node)
        for label, fp in legal_fps.items():
            if fp != base_fp:
                DEFECTS.append(
                    f"({label}) telemetry state-view fingerprint differs "
                    f"from the absent-param baseline (baseline "
                    f"{describe_fp(base_fp)} -> member {describe_fp(fp)}) — "
                    f"timeout is a wait budget, not a view selector, and no "
                    f"deployment change occurred — Type4_StateLogicViolation"
                )

        # ---- negative legs: sub-minimum members must be refused 4xx ----
        for label, qp in NEG:
            s, raw, _fp, fatal = probe(label, qp)
            if fatal:
                return "SCRIPT_ERROR"
            if 500 <= s <= 599:
                if alive():
                    DEFECTS.append(
                        f"({label}) sub-minimum timeout returned {s} — an "
                        f"input-validation failure surfaced as an internal "
                        f"error — Type3_RuntimeFailure — raw={raw[:200]}"
                    )
                else:
                    return "SCRIPT_ERROR"
                continue
            if 200 <= s < 300:
                DEFECTS.append(
                    f"({label}) sub-minimum timeout ACCEPTED with {s} — the "
                    f"constraint fixes minimum 1 (default 60); not refusing "
                    f"when it should refuse — Type1_IllegalSuccess — "
                    f"raw={raw[:200]}"
                )
                node, err = parse_view(raw)
                if node is not None and fingerprint(node) != base_fp:
                    DEFECTS.append(
                        f"({label}) illegally-accepted sub-minimum call "
                        f"additionally returned a DIFFERENT state view "
                        f"(baseline {describe_fp(base_fp)} -> "
                        f"{describe_fp(fingerprint(node))}) — "
                        f"Type4_StateLogicViolation"
                    )
            elif 400 <= s < 500:
                print(f"({label}) refused with {s} — consistent with the "
                      f"documented minimum")
            else:
                print(f"OBSERVATION ({label}): returned {s} — disposition "
                      f"outside the judged classes, recorded, not judged")

        # ---- tail: read-only refused calls must leave no state damage ----
        time.sleep(0.5)
        s, raw, _fp, fatal = probe("tail default(absent)", None)
        if fatal:
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(
                    f"(tail) default telemetry face returned {s} after the "
                    f"negative legs — service alive per /healthz — "
                    f"Type3_RuntimeFailure — raw={raw[:200]}"
                )
            else:
                return "SCRIPT_ERROR"
        elif s == 200:
            node, err = parse_view(raw)
            if node is None:
                DEFECTS.append(
                    f"(tail) 200 but {err} — Type4_StateLogicViolation — "
                    f"raw={raw[:200]}"
                )
            elif fingerprint(node) != base_fp:
                DEFECTS.append(
                    f"(tail) telemetry state-view fingerprint changed after "
                    f"the refused read-only legs (baseline "
                    f"{describe_fp(base_fp)} -> {describe_fp(fingerprint(node))}) "
                    f"— state damage from refused calls — "
                    f"Type4_StateLogicViolation"
                )
        else:
            print(f"OBSERVATION (tail): returned {s} — recorded, not judged")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        pass  # read-only matrix on the ops face — nothing to clean up


if __name__ == "__main__":
    try:
        _v = main()
    except Exception as _e:  # never exit without the strict VERDICT line
        print(f"FATAL: {_e}")
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
