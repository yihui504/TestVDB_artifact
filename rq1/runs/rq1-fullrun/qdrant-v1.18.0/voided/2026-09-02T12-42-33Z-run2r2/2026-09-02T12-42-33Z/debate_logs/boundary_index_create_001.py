#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_create_001
# strategy: strategy1_enum_domain_closure
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the enum's own members are assumed
#            accepted end-to-end; a member rejected at creation, or accepted with no
#            payload_schema echo, would mean the closure of the declared type domain
#            is not actually honored on this face)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary closure x qdrant_type_index_create_001 (field_schema type
domain) — the G4 positive branch: EVERY in-domain member of the declared PayloadSchemaType
enum [keyword, integer, float, geo, text, bool, datetime, uuid] (members quoted verbatim
from the constraint assertion) is PUT as {"field_schema": {"type": <member>}} on its own
field of a live bic001_* collection (wait=true query param, per placement check), each
must return HTTP 200 and must persist — read back via collections+get
result.payload_schema, the field key must be present for all 8 members (status-code-only
adjudication is forbidden on this face per R20 lesson: persistence judged via describe
readback / index_schema echo). The dual legal encoding field_schema="keyword" (bare enum
string, the other PayloadSchemaParams branch) is exercised as a 9th measured leg.
[chunk_index+create coverage: strategy1 boundary-closure x qdrant_type_index_create_001
(field_schema.type in-domain members)]
Oracle: on a live bic001_* collection holding one point whose payload carries all 8
payload-type fields, each of the 8 members PUT to index+create returns HTTP 200 AND the
collections+get readback result.payload_schema contains all 8 f_<member> keys (a 4xx on an
in-domain member = disposition conflict against the declared domain - printed as Type1
signal; a 200 whose field key is missing from the readback = Type4_StateLogicViolation;
5xx/transport = Type3_RuntimeFailure with /healthz re-check; bare-string "keyword" leg:
200 + readback key = conform, anything else measured and printed for the judge)
Constraint: qdrant_type_index_create_001 (bare id) — "field_schema IN {keyword, integer,
float, geo, text, bool, datetime, uuid}; text tokenizer IN {prefix, whitespace, word,
multilingual}" (evidence_tier: explicit; level: endpoint)

Shape anchor (D3b): index+create response_shape declares result: object with
result.status: string and result.operation_id: [integer, null]; collections+get declares
result.payload_schema: object — the hard readback oracle is KEY PRESENCE in that object;
the inner echo (data_type casing/tokenizer keys) is a measured-only zone (response grid
types the value only as object), printed raw for the judge. R9 spec-shape conflict zone:
if the live envelope returns result as boolean instead of the declared object, it is
recorded measured-only (spec wins on paper; no defect claim from envelope shape alone).
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

COLL = "bic001_" + uuid.uuid4().hex[:10]  # unique-prefix discipline
DIM = 4

# In-domain members, quoted verbatim from the constraint assertion text
# (qdrant_type_index_create_001). Each member is exercised on its own field.
MEMBERS = ["keyword", "integer", "float", "geo", "text", "bool", "datetime", "uuid"]

# One payload fixture point typed per member (data_types: "Payload JSON types
# (filterable)" — keyword string / integer / float / bool / geo {lon,lat} /
# datetime RFC 3339 / uuid / text string)
FIXTURE = {
    "f_keyword": "kwd",
    "f_integer": 42,
    "f_float": 0.5,
    "f_geo": {"lon": 13.4, "lat": 52.5},
    "f_text": "hello incremental world",
    "f_bool": True,
    "f_datetime": "2026-01-01T00:00:00Z",
    "f_uuid": "550e8400-e29b-41d4-a716-446655440000",
}


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
        return {}, None  # declared object; absent means empty (measured)
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

    # ---- Arrange: live collection + one fully-typed fixture point ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return
    st, _, raw = safe_request("PUT", PATH_UPSERT.format(collection_name=quote(COLL, safe="")),
                              json={"points": [{"id": 1, "vector": [0.1] * DIM,
                                                "payload": FIXTURE}]},
                              timeout=60, params={"wait": "true"})
    if st != 200:
        print(f"setup upsert failed status={st}: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # ---- Act: every in-domain member, own field, wait=true ----
    for member in MEMBERS:
        field = f"f_{member}"
        st, body, raw = put_index(field, {"type": member})
        print(f"[probe type={member}] PUT index f_{member} -> status={st} raw={str(raw)[:250]}")
        if st <= 0 or 500 <= st <= 599:
            findings.append(transport_verdict(f"type={member}", st, raw))
            continue
        if 400 <= st < 500:
            findings.append((0, f"Type1-signal (disposition conflict) - in-domain member "
                                f"'{member}' rejected with {st} (declared domain member; "
                                f"200 face of qdrant_behavioral_index_create_001 also "
                                f"broken): {str(raw)[:200]}"))
            continue
        if st != 200:
            findings.append((3, f"uninterpreted status {st} for member '{member}'"))
            continue
        # 200: envelope shape measured (spec declares result object with status string)
        if isinstance(body, dict):
            res = body.get("result")
            if isinstance(res, dict):
                print(f"  envelope result.status={res.get('status')!r} "
                      f"result.operation_id={res.get('operation_id')!r} (spec grid: object)")
            else:
                print(f"  [measure] envelope result={res!r} — spec grid declares object "
                      f"(R9 shape conflict zone, measured-only)")
        # persistence: hard oracle = key present in payload_schema readback
        ps, err = read_payload_schema()
        if ps is None:
            findings.append((3, f"readback unreadable for '{member}': {err}"))
            continue
        if field not in ps:
            findings.append((2, f"Type4_StateLogicViolation - '{member}' returned 200 but "
                                f"readback result.payload_schema lacks key '{field}' "
                                f"(status-code-only ok; nothing persisted): ps={str(ps)[:200]}"))
        else:
            echo = json.dumps(ps[field], ensure_ascii=False)
            match = member.lower() in echo.lower()
            print(f"  OK(persist): '{field}' in payload_schema, echo={echo!r} "
                  f"(member-echo {'matches' if match else 'DIFFERS — measured for judge'})")

    # ---- Dual-encoding measured leg: bare-string PayloadSchemaParams branch ----
    st, body, raw = put_index("f_bare_string", "keyword")
    print(f"[probe field_schema='keyword' (bare-string encoding)] -> status={st} "
          f"raw={str(raw)[:250]}")
    if st <= 0 or 500 <= st <= 599:
        findings.append(transport_verdict("bare-string encoding", st, raw))
    elif st == 200:
        ps, err = read_payload_schema()
        if ps is None:
            findings.append((3, f"readback unreadable for bare-string leg: {err}"))
        elif "f_bare_string" not in ps:
            print("  [measure] bare-string 200 but readback lacks key — judge material")
        else:
            print(f"  OK(persist): bare-string encoding echoed: "
                  f"{json.dumps(ps['f_bare_string'], ensure_ascii=False)!r}")
    else:
        print(f"  [measure] bare-string encoding got {st} (other spec branch; judge material)")

    # ---- Assert ----
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
        else:
            print(f"VERDICT: DEFECT_FOUND ({msg})")
        return
    print("OK: all 8 in-domain members accepted with 200 and persisted in payload_schema")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
