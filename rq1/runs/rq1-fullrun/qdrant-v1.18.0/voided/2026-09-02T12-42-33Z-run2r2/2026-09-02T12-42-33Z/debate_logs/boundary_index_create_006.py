#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_create_006
# strategy: strategy7_malformed_input
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001, qdrant_behavioral_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde assumed to reject encoding-
#            boundary input; NUL / lone surrogates / malformed JSON bodies may reach
#            deeper layers and panic instead of 400)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed input / character fuzzing x index+create (field_name is the
user-input string slot of this face) — five encoding-boundary probes on a live bic006_*
collection: (1) field_name containing a JSON-escaped NUL "a\\u0000b"; (2) field_name
containing a LONE SURROGATE escape "solo\\ud800end" (not a legal Unicode scalar; serde
must refuse it); (3) raw-body TRUNCATED JSON (cut mid-object, sent via data= bytes to
bypass client-side serialization); (4) raw-body TRAILING-COMMA JSON; (5) raw-body BARE
NUL byte inside the JSON string value (control char illegal in raw JSON text). Malformed
JSON (3)(4)(5) must be rejected 4xx — any 5xx/panic = Type3_RuntimeFailure. The NUL /
surrogate field_name legs (1)(2) are expected 4xx; a 2xx there is adjudicated by describe
readback: key round-trips the control char exactly = silent accept (docs constrain no
field_name charset — G3: measured, printed for judge; NO_DEFECT claim withheld), key
absent = silent-drop signal; any 5xx = Type3. Legal control index first (G4).
[chunk_index+create coverage: strategy7 malformed-input x index+create field_name slot +
type/behavioral constraints' robust-handling face]
Oracle: on the live bic006_* collection the legal control keyword index returns 200 with
the control key in readback result.payload_schema; probes (3)(4)(5) raw-body malformed
JSON each return HTTP 400/422 (5xx = Type3_RuntimeFailure; 2xx on unparseable JSON =
Type1_IllegalSuccess — a parser accepted syntactically invalid input); probes (1)(2)
NUL/surrogate field_name return 4xx with non-empty diagnostics OR 2xx with the exact
readback echo printed for the judge (docs declare no field_name charset — silent accept
is measured-only per G3; empty 4xx body = Type2_PoorDiagnostics; 404 on live collection =
SCRIPT_ERROR; transport failure = /healthz re-check then Type3 or SCRIPT_ERROR)
Constraint: qdrant_type_index_create_001 (bare id) — field_schema domain (robust handling
of the surrounding request); qdrant_behavioral_index_create_001 (bare id) — 400 on
invalid input (both evidence_tier: explicit; level: endpoint)

Shape anchor (D3b): raw-body probes use safe_request(..., data=<bytes>) so client
serialization cannot pre-reject the malformed input (strategy-7 safety wrapper rule);
json= probes carry the escapes in-band. Readback anchor: collections+get
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

COLL = "bic006_" + uuid.uuid4().hex[:10]  # unique-prefix discipline
DIM = 4

NUL_FIELD = "a\x00b"          # JSON-escaped on the wire by json= serialization
SURROGATE_FIELD = "solo\ud800end"  # lone surrogate escape — not a legal Unicode scalar

# Raw malformed JSON bodies (bytes; sent via data= to bypass client serialization)
RAW_MALFORMED = [
    ("truncated JSON (cut mid-object)",
     b'{"field_name": "mf_trunc", "field_schema"'),
    ("trailing comma after object member",
     b'{"field_name": "mf_comma", "field_schema": {"type": "keyword"},}'),
    ("bare NUL byte inside JSON string value",
     b'{"field_name": "a\x00b", "field_schema": {"type": "keyword"}}'),
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


def put_index_json(field_name, field_schema, timeout=60):
    """index+create face, json= body. wait is a QUERY parameter — never body."""
    return safe_request("PUT", PATH_INDEX.format(collection_name=quote(COLL, safe="")),
                        json={"field_name": field_name, "field_schema": field_schema},
                        timeout=timeout, params={"wait": "true"})


def put_index_raw(raw_bytes, timeout=60):
    """index+create face, RAW body via data= (malformed-input safety wrapper)."""
    return safe_request("PUT", PATH_INDEX.format(collection_name=quote(COLL, safe="")),
                        data=raw_bytes, timeout=timeout, params={"wait": "true"},
                        headers={"Content-Type": "application/json"})


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

    # ---- Legal control first (G4) ----
    st, _, raw = put_index_json("mf_ctrl", {"type": "keyword"})
    print(f"[control keyword] PUT index mf_ctrl -> status={st} raw={str(raw)[:200]}")
    if st <= 0 or 500 <= st <= 599:
        print("VERDICT: " + transport_verdict("legal control", st, raw)[1])
        return
    if st != 200:
        print(f"VERDICT: SCRIPT_ERROR - legal control rejected {st}: {str(raw)[:200]}")
        return
    print("OK(control): valid keyword index accepted")

    # ---- (1)(2) Escaped control chars in field_name (json= carries the escapes) ----
    for label, field in (("field_name with escaped NUL a\\u0000b", NUL_FIELD),
                         ("field_name with lone surrogate \\ud800", SURROGATE_FIELD)):
        st, body, raw = put_index_json(field, {"type": "keyword"})
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
                print(f"  OK(reject): '{label}' -> {st} (encoding boundary refused)")
            continue
        if 200 <= st < 300:
            ps, err = read_payload_schema()
            if ps is None:
                findings.append((3, f"readback unreadable after 2xx on '{label}': {err}"))
                continue
            hit = [k for k in ps.keys() if k not in ("mf_ctrl",)]
            print(f"  [measure] '{label}' accepted with {st}; readback keys besides "
                  f"control: {hit!r} (docs declare no field_name charset — silent accept "
                  f"is judge material per G3; raw echo printed above)")
            continue
        findings.append((3, f"uninterpreted status {st} for probe '{label}'"))

    # ---- (3)(4)(5) Raw-body malformed JSON: parser MUST reject with 4xx ----
    for label, raw_body in RAW_MALFORMED:
        st, body, raw = put_index_raw(raw_body)
        print(f"[probe {label}] raw body {len(raw_body)}B -> status={st} "
              f"raw={str(raw)[:250]}")
        if st <= 0 or 500 <= st <= 599:
            findings.append(transport_verdict(label, st, raw))
            continue
        if st == 404:
            findings.append((3, f"probe '{label}' got 404 on live collection {COLL}"))
            continue
        if 400 <= st < 500:
            print(f"  OK(reject): '{label}' -> {st} (malformed JSON refused)")
            continue
        if 200 <= st < 300:
            findings.append((0, f"Type1_IllegalSuccess - '{label}' (syntactically invalid "
                                f"JSON) accepted with {st}: {str(raw)[:200]}"))
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
    print("OK: control accepted; NUL/surrogate refused or measured; 3/3 malformed JSON "
          "bodies rejected 4xx")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
