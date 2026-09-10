#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_create_005
# strategy: strategy2_type_confusion
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the text tokenizer sub-enum is
#            assumed validated only when present; case variants / unknown names /
#            non-string types may pass through the nested untagged struct silently)
#            + BS-04 (Boundary Default Optimism — tokenizer defaulting when absent is
#            assumed; the default member applied must be observable in the readback)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 closure + strategy2 type-confusion x qdrant_type_index_create_001 — the
SECOND half of the constraint: "text tokenizer IN {prefix, whitespace, word, multilingual}".
On a live bic005_* collection: (a) closure — every in-domain tokenizer is PUT as
{"type": "text", "tokenizer": <member>} on its own field and must return 200 with the
field persisted in readback result.payload_schema; (b) out-of-domain/wrong-typed —
tokenizer values "bogus" (unknown), "Word" (case variant), "" (empty), 123 (integer),
null, ["word"] (array) must each be rejected 400/422, any 2xx adjudicated by readback
(persisted = Type1_IllegalSuccess, dropped = judge signal); (c) measured legs —
{"type": "text"} with tokenizer absent (declared default path) and tokenizer attached to
a NON-text type {"type": "keyword", "tokenizer": "word"} (extra-field disposition;
measured-only, judge to adjudicate).
[chunk_index+create coverage: strategy1 closure + strategy2 type-confusion x
qdrant_type_index_create_001 (field_schema.text tokenizer enum)]
Oracle: on the live bic005_* collection each of the 4 in-domain tokenizers returns HTTP
200 with its tok_<member> key present in readback result.payload_schema (4xx on an
in-domain tokenizer = disposition-conflict Type1-signal; 200 without the readback key =
Type4_StateLogicViolation); each of the 6 out-of-domain/wrong-typed tokenizer probes
returns HTTP 400/422 with non-empty diagnostics (2xx + persisted key = Type1_
IllegalSuccess; 2xx + no key = silent-drop judge signal; 404 on live collection =
SCRIPT_ERROR; 5xx/transport = Type3_RuntimeFailure with /healthz re-check; empty 4xx
body = Type2_PoorDiagnostics); the two measured legs print their readback echo verbatim
for the judge (no hard claim)
Constraint: qdrant_type_index_create_001 (bare id) — "field_schema IN {keyword, integer,
float, geo, text, bool, datetime, uuid}; text tokenizer IN {prefix, whitespace, word,
multilingual}" (evidence_tier: explicit; level: endpoint)

Shape anchor (D3b): request_required_paths [field_name, field_schema.type] satisfied by
every probe (type: "text" or "keyword" present as a string); readback anchor
collections+get result.payload_schema: object — inner tokenizer echo is a measured-only
zone (grid types it only as object).
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

COLL = "bic005_" + uuid.uuid4().hex[:10]  # unique-prefix discipline
DIM = 4

# In-domain tokenizer members, quoted verbatim from the constraint assertion text
TOKENIZERS = ["prefix", "whitespace", "word", "multilingual"]

# Out-of-domain / wrong-typed tokenizer values (label -> (field, value))
BAD_TOKENIZERS = [
    ("tokenizer='bogus' (unknown member)", ("tok_bad_name", "bogus")),
    ("tokenizer='Word' (case variant)", ("tok_case", "Word")),
    ("tokenizer='' (empty string)", ("tok_empty", "")),
    ("tokenizer=123 (integer into string-enum slot)", ("tok_int", 123)),
    ("tokenizer=null", ("tok_null", None)),
    ("tokenizer=['word'] (array into string-enum slot)", ("tok_arr", ["word"])),
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

    # ---- Arrange: live collection + one text-bearing point ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return
    st, _, raw = safe_request("PUT", PATH_UPSERT.format(collection_name=quote(COLL, safe="")),
                              json={"points": [{"id": 1, "vector": [0.1] * DIM,
                                                "payload": {"body": "hello world"}}]},
                              timeout=60, params={"wait": "true"})
    if st != 200:
        print(f"setup upsert failed status={st}: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # ---- (a) Closure: every in-domain tokenizer must be accepted and persisted ----
    for member in TOKENIZERS:
        field = f"tok_{member}"
        st, body, raw = put_index(field, {"type": "text", "tokenizer": member})
        print(f"[probe tokenizer={member}] PUT index {field} -> status={st} "
              f"raw={str(raw)[:250]}")
        if st <= 0 or 500 <= st <= 599:
            findings.append(transport_verdict(f"tokenizer={member}", st, raw))
            continue
        if 400 <= st < 500:
            findings.append((0, f"Type1-signal (disposition conflict) - in-domain tokenizer "
                                f"'{member}' rejected with {st}: {str(raw)[:200]}"))
            continue
        if st != 200:
            findings.append((3, f"uninterpreted status {st} for tokenizer '{member}'"))
            continue
        ps, err = read_payload_schema()
        if ps is None:
            findings.append((3, f"readback unreadable for tokenizer '{member}': {err}"))
            continue
        if field not in ps:
            findings.append((2, f"Type4_StateLogicViolation - tokenizer '{member}' returned "
                                f"200 but readback lacks key '{field}'"))
        else:
            echo = json.dumps(ps[field], ensure_ascii=False)
            print(f"  OK(persist): '{field}' echoed {echo!r}")

    # ---- (b) Out-of-domain / wrong-typed tokenizers must be rejected ----
    for label, (field, value) in BAD_TOKENIZERS:
        st, body, raw = put_index(field, {"type": "text", "tokenizer": value})
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
                print(f"  OK(reject): '{label}' -> {st} (tokenizer enum 400 face)")
            continue
        if 200 <= st < 300:
            ps, err = read_payload_schema()
            if ps is None:
                findings.append((3, f"readback unreadable after 2xx on '{label}': {err}"))
                continue
            if field in ps:
                findings.append((0, f"Type1_IllegalSuccess - '{label}' accepted with {st} "
                                    f"AND persisted: payload_schema[{field!r}]="
                                    f"{json.dumps(ps[field], ensure_ascii=False)!r}"))
            else:
                print(f"  [measure] '{label}' accepted with {st} but silent-dropped — "
                      f"lenient path, judge to adjudicate")
            continue
        findings.append((3, f"uninterpreted status {st} for probe '{label}'"))

    # ---- (c) Measured legs (no hard claim; echo printed for the judge) ----
    st, _, raw = put_index("tok_default_absent", {"type": "text"})
    ps, err = (None, None)
    if st == 200:
        ps, err = read_payload_schema()
    echo = ps.get("tok_default_absent") if isinstance(ps, dict) else None
    print(f"[measure tokenizer absent on type=text] status={st} "
          f"readback={json.dumps(echo, ensure_ascii=False) if echo is not None else err} "
          f"(declared default path — which member materialized?)")
    st, _, raw = put_index("tok_on_keyword", {"type": "keyword", "tokenizer": "word"})
    ps2, err2 = (None, None)
    if st == 200:
        ps2, err2 = read_payload_schema()
    echo2 = ps2.get("tok_on_keyword") if isinstance(ps2, dict) else None
    print(f"[measure tokenizer on non-text type=keyword] status={st} "
          f"readback={json.dumps(echo2, ensure_ascii=False) if echo2 is not None else err2} "
          f"(extra-field disposition — dropped or kept, judge to adjudicate)")

    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
        else:
            print(f"VERDICT: DEFECT_FOUND ({msg})")
        return
    print("OK: 4/4 in-domain tokenizers persisted; 6/6 bad tokenizers rejected 400/422")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
