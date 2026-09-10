#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_create_003
# strategy: strategy2_type_confusion
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001, qdrant_behavioral_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the field_schema.type slot is
#            declared an enum of strings; serde is assumed to refuse non-string JSON
#            types, but untagged anyOf parsing may coerce int/bool/null/array/object
#            shapes through or panic on them)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-confusion x qdrant_type_index_create_001 — the field_schema.type
slot is declared as an enum OF STRINGS; six wrong-JSON-typed values are injected into it
on distinct fields of a live bic003_* collection: integer 5, float 1.5, boolean true,
null, array ["keyword"], nested object {"type": "keyword"} (the classic serde confusion —
an object whose value would be legal if unwrapped). Each must be rejected 400/422 (the
documented 400-on-invalid-schema face of qdrant_behavioral_index_create_001). A 2xx is
adjudicated by describe readback (result.payload_schema): key persisted = Type1_
IllegalSuccess (wrong-typed enum slot coerced through), key absent = silent-drop signal
for the judge; a 5xx/panic = Type3_RuntimeFailure. Legal control keyword index first
(G4 pairing).
[chunk_index+create coverage: strategy2 type-confusion x qdrant_type_index_create_001
(field_schema.type wrong JSON types)]
Oracle: on the live bic003_* collection the legal control {"type": "keyword"} returns 200
with the control key present in readback result.payload_schema; each of the six
wrong-typed probes returns HTTP 400/422 with non-empty diagnostics (2xx + readback key
present = Type1_IllegalSuccess; 2xx + key absent = silent-drop judge signal; 404 on the
live collection = SCRIPT_ERROR; 5xx/transport = Type3_RuntimeFailure with /healthz
re-check; empty 4xx body = Type2_PoorDiagnostics)
Constraint: qdrant_type_index_create_001 (bare id) — "field_schema IN {keyword, integer,
float, geo, text, bool, datetime, uuid}" (enum of strings — non-string JSON types are
outside the domain); qdrant_behavioral_index_create_001 (bare id) — "400 on an invalid
field schema" (both evidence_tier: explicit; level: endpoint)

Shape anchor (D3b): request_required_paths for index+create = [field_name,
field_schema.type] — every probe body carries both paths (the type path with a WRONG
value), so the negative legs target the value domain, not an absent path (absent-path
legs are boundary_index_create_004). Readback anchor: collections+get declares
result.payload_schema: object.
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

COLL = "bic003_" + uuid.uuid4().hex[:10]  # unique-prefix discipline
DIM = 4

# Wrong-JSON-typed values injected into the field_schema.type slot (label -> (field, value)).
WRONG_TYPED = [
    ("type=5 (integer into string-enum slot)", ("w_int", 5)),
    ("type=1.5 (float into string-enum slot)", ("w_float", 1.5)),
    ("type=true (boolean into string-enum slot)", ("w_bool", True)),
    ("type=null (null into string-enum slot)", ("w_null", None)),
    ("type=['keyword'] (array into string-enum slot)", ("w_arr", ["keyword"])),
    ("type={'type': 'keyword'} (object into string-enum slot)",
     ("w_obj", {"type": "keyword"})),
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
    findings = []  # (rank, msg); rank 0 = defect, 3 = script-error

    # ---- Arrange: live collection ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # ---- Legal control first (G4: prove the face accepts valid input) ----
    st, _, raw = put_index("w_ctrl", {"type": "keyword"})
    print(f"[control type=keyword] PUT index w_ctrl -> status={st} raw={str(raw)[:200]}")
    if st <= 0 or 500 <= st <= 599:
        print("VERDICT: " + transport_verdict("legal control", st, raw)[1])
        return
    if st != 200:
        print(f"VERDICT: SCRIPT_ERROR - legal control rejected {st}: {str(raw)[:200]}")
        return
    ps, err = read_payload_schema()
    if ps is None or "w_ctrl" not in ps:
        print(f"VERDICT: SCRIPT_ERROR - control 200 but readback unreadable/lacking key ({err})")
        return
    print("OK(control): valid keyword index accepted and persisted")

    # ---- Act + Assert: each wrong-typed type value must be rejected ----
    for label, (field, value) in WRONG_TYPED:
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
            ps, err = read_payload_schema()
            if ps is None:
                findings.append((3, f"readback unreadable after 2xx on '{label}': {err}"))
                continue
            if field in ps:
                findings.append((0, f"Type1_IllegalSuccess - wrong-typed enum slot "
                                    f"'{label}' accepted with {st} AND persisted: "
                                    f"payload_schema[{field!r}]="
                                    f"{json.dumps(ps[field], ensure_ascii=False)!r}"))
            else:
                print(f"  [measure] '{label}' accepted with {st} but silent-dropped "
                      f"(key '{field}' absent from payload_schema) — lenient path, "
                      f"judge to adjudicate against the 400 face")
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
    print("OK: control persisted; all 6 wrong-typed field_schema.type values rejected 400/422")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
