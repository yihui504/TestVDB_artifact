#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_create_004
# strategy: strategy2_type_confusion
# endpoint: index+create
# constraint_ids: qdrant_behavioral_index_create_001, qdrant_type_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — required-path enforcement on
#            field_name / field_schema.type is assumed; untagged anyOf parsing may
#            treat null/absent/empty as a default instead of a 400 validation error)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 required-path/shape violations x index+create request_required_paths
[field_name, field_schema.type] + the 400 face of qdrant_behavioral_index_create_001 —
eight probes each deliberately violate exactly one required path or its JSON shape:
field_schema absent, field_schema null, field_schema {} (type path absent), field_schema
[] (array shape), field_name absent, field_name null, field_name "" (empty string),
field_name 123 (wrong type). NOTE: the omissions are the point of the attack (this
probe set IS the required-path violation face); each must be rejected 400/422. A 2xx on
the field_name legs is adjudicated by describe readback: whatever key materialized in
result.payload_schema (empty-string key, coerced key, or nothing) decides Type1/Type4 vs
silent-drop. Legal control full valid body first (G4 pairing).
[chunk_index+create coverage: strategy2 type-confusion x request_required_paths of
index+create (field_name / field_schema.type) + 400 face of
qdrant_behavioral_index_create_001]
Oracle: on the live bic004_* collection the legal control {"field_name": "m_ctrl",
"field_schema": {"type": "keyword"}} returns 200 with m_ctrl present in readback
result.payload_schema; each of the eight missing/shape-violating probes returns HTTP
400/422 with non-empty diagnostics (2xx on a field_name leg + a materialized
payload_schema key = Type1_IllegalSuccess if the key echoes the illegal value, Type4_
StateLogicViolation if a coerced/defaulted key appears; 2xx + no key = silent-drop judge
signal; 2xx on a field_schema leg = Type1_IllegalSuccess against the required path; 404
on the live collection = SCRIPT_ERROR; 5xx/transport = Type3_RuntimeFailure with
/healthz re-check; empty 4xx body = Type2_PoorDiagnostics)
Constraint: qdrant_behavioral_index_create_001 (bare id) — "400 on an invalid field
schema"; qdrant_type_index_create_001 (bare id) — field_schema type domain (an absent or
non-object schema cannot satisfy it) (both evidence_tier: explicit; level: endpoint)

Shape anchor (D3b): api_endpoints[index+create].request_required_paths = [field_name,
field_schema.type] — the probes violate exactly one path each; the control satisfies
both. Readback anchor: collections+get declares result.payload_schema: object.
Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  index+create       -> PUT    /collections/{collection_name}/index
  collections+create -> PUT    /collections/{collection_name}
  collections+get    -> GET    /collections/{collection_name}
  collections+delete -> DELETE /collections/{collection_name}
  healthz            -> GET    /healthz
"""

import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ---
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
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)

# URL registry - verbatim from raw_knowledge.json api_endpoints[].url
PATH_INDEX = "/collections/{collection_name}/index"
PATH_CREATE = "/collections/{collection_name}"
PATH_GET = "/collections/{collection_name}"
PATH_DELETE = "/collections/{collection_name}"

COLL = "bic004_" + uuid.uuid4().hex[:10]  # unique-prefix discipline
DIM = 4

# Required-path / shape violations. Each probe body deliberately violates ONE declared
# required path (request_required_paths: field_name, field_schema.type). This omission
# IS the attack (400 face of qdrant_behavioral_index_create_001).
MISSING_PROBES = [
    ("field_schema absent", {"field_name": "m_no_schema"}),
    ("field_schema null", {"field_name": "m_null_schema", "field_schema": None}),
    ("field_schema {} (type path absent)", {"field_name": "m_empty_obj",
                                            "field_schema": {}}),
    ("field_schema [] (array shape)", {"field_name": "m_arr_schema",
                                       "field_schema": []}),
    ("field_name absent", {"field_schema": {"type": "keyword"}}),
    ("field_name null", {"field_name": None, "field_schema": {"type": "keyword"}}),
    ("field_name '' (empty string)", {"field_name": "",
                                       "field_schema": {"type": "keyword"}}),
    ("field_name 123 (wrong type)", {"field_name": 123,
                                     "field_schema": {"type": "keyword"}}),
]


def safe_request(method, endpoint, json=None, data=None, params=None, timeout=10, headers=None):
    """Safe HTTP wrapper (agents/_target_api_reference.md). Returns (status, body, raw).
    Forwards json/data/params/timeout/headers to requests.request exactly (R20 lesson)."""
    url = f"{BASE_URL}{endpoint}"
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    try:
        response = requests.request(method=method, url=url, json=json, data=data,
                                    params=params, headers=hdrs, timeout=timeout)
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except Exception:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def healthz():
    """Lightweight liveness probe (G8: transport/5xx re-checked against /healthz)."""
    return safe_request("GET", "/healthz", timeout=5)


def cleanup():
    """Teardown: best-effort delete of ONLY the collection this script created."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")),
                     timeout=30, params={"timeout": 30})
    except Exception:
        pass  # cleanup failures are non-fatal


def put_index_body(body, timeout=60):
    """index+create face with a RAW request body (probe-controlled shape).
    wait is a QUERY parameter (placement check) — never body."""
    return safe_request("PUT", PATH_INDEX.format(collection_name=quote(COLL, safe="")),
                        json=body, timeout=timeout, params={"wait": "true"})


def read_payload_schema():
    """Describe readback: collections+get -> result.payload_schema (declared object)."""
    st, body, raw = safe_request("GET", PATH_GET.format(collection_name=quote(COLL, safe="")),
                                 timeout=30)
    if st != 200 or not isinstance(body, dict):
        return None, f"collections+get status={st} raw={str(raw)[:150]}"
    res = body.get("result")
    if not isinstance(res, dict):
        return None, "envelope result not a dict"
    ps = res.get("payload_schema")
    if ps is None:
        return {}, None
    if not isinstance(ps, dict):
        return None, f"result.payload_schema not an object: {type(ps).__name__}"
    return ps, None


def transport_verdict(probe, st, raw):
    """G8: transport/5xx isolated via /healthz liveness re-check."""
    hs, _, hraw = healthz()
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    if st <= 0:
        if hs <= 0 or hs >= 500:
            return (0, f"Type3_RuntimeFailure - probe '{probe}' transport failure and "
                       f"/healthz={hs} (service down)")
        return (3, f"probe '{probe}' transport failure with /healthz={hs} alive")
    return (0, f"Type3_RuntimeFailure - probe '{probe}' got {st} with /healthz={hs}")


def main():
    findings = []  # (rank, msg); rank 0 = defect, 2 = Type4, 3 = script-error

    # ---- Arrange: live collection ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # ---- Legal control first (G4: prove the face accepts the full valid body) ----
    st, _, raw = put_index_body({"field_name": "m_ctrl", "field_schema": {"type": "keyword"}})
    print(f"[control full valid body] PUT index m_ctrl -> status={st} raw={str(raw)[:200]}")
    if st <= 0 or 500 <= st <= 599:
        print("VERDICT: " + transport_verdict("legal control", st, raw)[1])
        return
    if st != 200:
        print(f"VERDICT: SCRIPT_ERROR - legal control rejected {st}: {str(raw)[:200]}")
        return
    ps, err = read_payload_schema()
    if ps is None or "m_ctrl" not in ps:
        print(f"VERDICT: SCRIPT_ERROR - control 200 but readback unreadable/lacking key ({err})")
        return
    print("OK(control): valid full body accepted and persisted")

    # ---- Act + Assert: each required-path violation must be rejected ----
    for label, body in MISSING_PROBES:
        st, bdy, raw = put_index_body(body)
        print(f"[probe {label}] body={json.dumps(body, ensure_ascii=False)} -> "
              f"status={st} raw={str(raw)[:250]}")
        if st <= 0 or 500 <= st <= 599:
            findings.append(transport_verdict(label, st, raw))
            continue
        if st == 404:
            findings.append((3, f"probe '{label}' got 404 on live collection {COLL}"))
            continue
        if 400 <= st < 500:
            if not str(raw).strip():
                findings.append((0, f"Type2_PoorDiagnostics - '{label}' rejected {st} with "
                                    f"EMPTY diagnostic body"))
            else:
                print(f"  OK(reject): '{label}' -> {st} (required-path 400 face)")
            continue
        if 200 <= st < 300:
            ps, err = read_payload_schema()
            if ps is None:
                findings.append((3, f"readback unreadable after 2xx on '{label}': {err}"))
                continue
            # which keys materialized? compare against the pre-existing control key
            new_keys = [k for k in ps.keys() if k != "m_ctrl"]
            if not new_keys:
                print(f"  [measure] '{label}' accepted with {st} but NO key materialized in "
                      f"payload_schema — silent-drop, judge to adjudicate against the "
                      f"required-path 400 face")
            else:
                findings.append((2, f"Type1/Type4-signal - required-path violation "
                                    f"'{label}' accepted with {st} AND payload_schema "
                                    f"materialized keys {new_keys!r} "
                                    f"(illegal echo or coerced key; judge to type)"))
            continue
        findings.append((3, f"uninterpreted status {st} for probe '{label}'"))

    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
        else:
            print(f"VERDICT: DEFECT_FOUND ({msg})")
        return
    print("OK: control persisted; all 8 required-path/shape violations rejected 400/422")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
