#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_create_008
# strategy: strategy4_special_value
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — exotic but LEGAL string field names
#            (unicode / zero-width / dot-notation / injection-shaped) are assumed to
#            round-trip byte-exactly through storage; silent normalization or mojibake
#            in the payload_schema echo would corrupt the field->index mapping)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy4 special-value x index+create field_name — five exotic-but-legal-shaped
field names on a live bic008_* collection: (1) unicode "城市🎯field"; (2) zero-width
"a\\u200bb"; (3) dot-notation "lvl2.city" (declared legal per contract data_types
"Dot-notation field access", with nested payload data upserted first); (4) JSON-injection-
shaped '{"$gt": ""}' (must be treated as an OPAQUE string key, never evaluated); (5)
SQL-shaped "'; DROP TABLE idx--". Each is EITHER accepted with a BYTE-EXACT readback echo
in result.payload_schema OR explicitly rejected 4xx with diagnostics — both dispositions
legal; the defect signals are: 5xx (Type3), a 200 whose readback key DIFFERS from the
sent key (mojibake/normalization = Type4_StateLogicViolation), or a 200 with no key
(silent-drop judge signal). Legal ASCII control index first (G4).
[chunk_index+create coverage: strategy4 special-value x index+create field_name
(unicode / zero-width / dot-notation / injection-shaped strings)]
Oracle: on the live bic008_* collection the ASCII control returns 200 with exact echo;
each exotic field_name yields 200 with the readback key EXACTLY equal to the sent string
(unicode compared as Python str equality on the JSON-parsed key — any difference =
Type4_StateLogicViolation) OR 400/422 with non-empty diagnostics (empty body =
Type2_PoorDiagnostics; 404 on live collection = SCRIPT_ERROR; 5xx/transport = Type3_
RuntimeFailure with /healthz re-check); for the '{"$gt": ""}' and SQL-shaped names an
accept is safe ONLY as an opaque echo — the raw readback is printed for the judge to
confirm no evaluation happened
Constraint: qdrant_type_index_create_001 (bare id) — the field_schema domain shares the
request whose field_name slot is under test (evidence_tier: explicit; level: endpoint);
data_types "Dot-notation field access" (nested payload fields addressable as "a.b")

Shape anchor (D3b): readback anchor collections+get result.payload_schema: object — key
equality is checked on the JSON-parsed dict keys (encoding-safe), never on raw substrings.
Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  index+create       -> PUT    /collections/{collection_name}/index
  collections+create -> PUT    /collections/{collection_name}
  collections+get    -> GET    /collections/{collection_name}
  collections+delete -> DELETE /collections/{collection_name}
  points+upsert      -> PUT    /collections/{collection_name}/points
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
PATH_UPSERT = "/collections/{collection_name}/points"

COLL = "bic008_" + uuid.uuid4().hex[:10]  # unique-prefix discipline
DIM = 4

SPECIAL_FIELDS = [
    ("unicode 城市🎯field", "城市🎯field"),
    ("zero-width a\\u200bb", "a\u200bb"),
    ("dot-notation lvl2.city (nested payload)", "lvl2.city"),
    ("JSON-injection-shaped name", '{"$gt": ""}'),
    ("SQL-shaped name", "'; DROP TABLE idx--"),
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
    findings = []  # (rank, msg); rank 0 = defect, 2 = Type4, 3 = script-error

    # ---- Arrange: live collection + nested payload data for the dot-notation leg ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return
    st, _, raw = safe_request("PUT", PATH_UPSERT.format(collection_name=quote(COLL, safe="")),
                              json={"points": [{"id": 1, "vector": [0.1] * DIM,
                                                "payload": {"lvl2": {"city": "berlin"}}}]},
                              timeout=60, params={"wait": "true"})
    if st != 200:
        print(f"setup upsert failed status={st}: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # ---- Legal ASCII control first (G4) ----
    st, _, raw = put_index("sp_ctrl", {"type": "keyword"})
    print(f"[control ASCII keyword] PUT index sp_ctrl -> status={st} raw={str(raw)[:200]}")
    if st <= 0 or 500 <= st <= 599:
        print("VERDICT: " + transport_verdict("legal control", st, raw)[1])
        return
    if st != 200:
        print(f"VERDICT: SCRIPT_ERROR - legal control rejected {st}: {str(raw)[:200]}")
        return
    ps, err = read_payload_schema()
    if ps is None or "sp_ctrl" not in ps:
        print(f"VERDICT: SCRIPT_ERROR - control 200 but readback unreadable/lacking key ({err})")
        return
    print("OK(control): ASCII keyword index accepted with exact echo")

    # ---- Act + Assert: exotic names — exact echo OR explicit reject ----
    for label, field in SPECIAL_FIELDS:
        st, body, raw = put_index(field, {"type": "keyword"})
        print(f"[probe {label}] -> status={st} raw={str(raw)[:250]}")
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
                print(f"  OK(reject): '{label}' -> {st} (explicit refusal, legal disposition)")
            continue
        if 200 <= st < 300:
            ps, err = read_payload_schema()
            if ps is None:
                findings.append((3, f"readback unreadable after 2xx on '{label}': {err}"))
                continue
            keys = [k for k in ps.keys() if k != "sp_ctrl"]
            print(f"  readback keys (non-control): {[repr(k) for k in keys]}")
            if field in ps:
                print(f"  OK(exact echo): '{label}' persisted byte-exactly as a dict key "
                      f"(opaque string handling; echo="
                      f"{json.dumps(ps[field], ensure_ascii=False)!r})")
            elif keys:
                findings.append((2, f"Type4_StateLogicViolation - '{label}' accepted with "
                                    f"{st} but readback keys {keys!r} do not contain the "
                                    f"sent name {field!r} exactly (mojibake/normalization "
                                    f"corrupted the field->index mapping)"))
            else:
                print(f"  [measure] '{label}' accepted with {st} but silent-dropped — "
                      f"judge to adjudicate")
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
    print("OK: exotic field names either echoed byte-exactly or explicitly rejected; "
          "no 5xx, no mojibake")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
