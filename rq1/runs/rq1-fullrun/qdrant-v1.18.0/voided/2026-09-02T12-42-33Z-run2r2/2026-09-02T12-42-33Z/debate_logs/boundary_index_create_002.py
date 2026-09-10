#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_create_002
# strategy: strategy2_type_confusion
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001, qdrant_behavioral_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — near-domain strings for the
#            field_schema type enum are assumed refused; case-variants / padded /
#            plausible-but-unknown values slipping through with 2xx would mean the
#            enum boundary is enforced by string-contains rather than exact match)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1/2 out-of-domain near-miss x qdrant_type_index_create_001 — values JUST
OUTSIDE the declared field_schema type domain {keyword, integer, float, geo, text, bool,
datetime, uuid}: case variants "Keyword"/"INTEGER" (case sensitivity), " keyword"
(leading whitespace), "" (empty string), "nested"/"vector" (plausible enum names that are
NOT members — the classic enum-boundary near-miss), each PUT on its own field of a live
bic002_* collection must be rejected 400/422 (the documented "400 on an invalid field
schema" face of qdrant_behavioral_index_create_001). Any 2xx acceptance is adjudicated by
describe readback (result.payload_schema): persisted as-is = Type1_IllegalSuccess,
normalized to an in-domain member = Type2-signal (silent normalize), absent = silent-drop
signal — both printed for the judge (Pattern B' discipline: expect_rejected alone is
forbidden when the field is schema-class). Legal control keyword index first (G4 pairing).
[chunk_index+create coverage: strategy1 near-domain + strategy2 enum-boundary x
qdrant_type_index_create_001 (field_schema.type out-of-domain values) + 400 face of
qdrant_behavioral_index_create_001]
Oracle: on the live bic002_* collection, the legal control {"field_schema":
{"type": "keyword"}} returns 200 with the control key present in readback
result.payload_schema; each of the six near-domain probes returns HTTP 400/422 with a
non-empty diagnostic body (empty 4xx body = Type2_PoorDiagnostics; 2xx = readback
adjudication — key persisted with the out-of-domain echo = Type1_IllegalSuccess; 404 on
the live collection = SCRIPT_ERROR; 5xx/transport = Type3_RuntimeFailure with /healthz
re-check)
Constraint: qdrant_type_index_create_001 (bare id) — "field_schema IN {keyword, integer,
float, geo, text, bool, datetime, uuid}"; qdrant_behavioral_index_create_001 (bare id) —
"400 on an invalid field schema" (both evidence_tier: explicit; level: endpoint)

Shape anchor (D3b): collections+get declares result.payload_schema: object — used for the
readback adjudication; index+create rejection legs print raw text (error-message
structure is not contract per threat-model by-design list; only non-emptiness asserted).
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

COLL = "bic002_" + uuid.uuid4().hex[:10]  # unique-prefix discipline
DIM = 4

# Near-domain probes: values just outside the declared enum (name -> (field, value)).
NEAR_DOMAIN = [
    ("case-variant 'Keyword'", ("t_case", "Keyword")),
    ("uppercase 'INTEGER'", ("t_upper", "INTEGER")),
    ("leading-whitespace ' keyword'", ("t_pad", " keyword")),
    ("empty string ''", ("t_empty", "")),
    ("plausible non-member 'nested'", ("t_nested", "nested")),
    ("plausible non-member 'vector'", ("t_vector", "vector")),
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


def put_index(field_name, field_schema, timeout=60):
    """index+create face. wait is a QUERY parameter (placement check) — never body."""
    return safe_request("PUT", PATH_INDEX.format(collection_name=quote(COLL, safe="")),
                        json={"field_name": field_name, "field_schema": field_schema},
                        timeout=timeout, params={"wait": "true"})


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
    findings = []  # (rank, msg); rank 0 = defect, 2 = Type4/Type2-signal, 3 = script-error

    # ---- Arrange: live collection ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # ---- Legal control first (G4: prove the face accepts valid input) ----
    st, _, raw = put_index("t_ctrl", {"type": "keyword"})
    print(f"[control type=keyword] PUT index t_ctrl -> status={st} raw={str(raw)[:200]}")
    if st <= 0 or 500 <= st <= 599:
        print("VERDICT: " + transport_verdict("legal control", st, raw)[1])
        return
    if st != 200:
        print(f"VERDICT: SCRIPT_ERROR - legal control rejected {st}; rejection legs would be "
              f"indistinguishable from a broken 200 face: {str(raw)[:200]}")
        return
    ps, err = read_payload_schema()
    if ps is None or "t_ctrl" not in ps:
        print(f"VERDICT: SCRIPT_ERROR - control 200 but readback unreadable/lacking key ({err})")
        return
    print("OK(control): valid keyword index accepted and persisted")

    # ---- Act + Assert: each near-domain value must be rejected ----
    for label, (field, value) in NEAR_DOMAIN:
        st, body, raw = put_index(field, {"type": value})
        print(f"[probe {label}] field={field} -> status={st} raw={str(raw)[:250]}")
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
                print(f"  OK(reject): '{label}' -> {st} (documented invalid-schema 400 face)")
            continue
        if 200 <= st < 300:
            # 2xx on out-of-domain: adjudicate persistence (Pattern B' discipline)
            ps, err = read_payload_schema()
            if ps is None:
                findings.append((3, f"readback unreadable after 2xx on '{label}': {err}"))
                continue
            echo = ps.get(field)
            if echo is None:
                print(f"  [measure] '{label}' accepted with {st} but silent-dropped "
                      f"(key '{field}' absent from payload_schema) — lenient path, judge "
                      f"to adjudicate against the 400 face")
            else:
                dump = json.dumps(echo, ensure_ascii=False)
                if str(value).lower() in dump.lower():
                    findings.append((0, f"Type1_IllegalSuccess - out-of-domain value "
                                        f"'{label}' accepted with {st} AND persisted "
                                        f"as-is: payload_schema[{field!r}]={dump!r}"))
                else:
                    print(f"  [measure] '{label}' accepted with {st} and normalized: "
                          f"payload_schema[{field!r}]={dump!r} (silent normalize, "
                          f"Type2-signal — judge to adjudicate)")
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
    print("OK: control persisted; all 6 near-domain values rejected with 400/422")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
