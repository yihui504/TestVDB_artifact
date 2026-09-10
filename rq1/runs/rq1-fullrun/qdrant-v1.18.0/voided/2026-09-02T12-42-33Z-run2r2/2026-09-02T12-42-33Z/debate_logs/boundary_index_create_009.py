#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_create_009
# strategy: strategy1_behavioral_triangle
# endpoint: index+create
# constraint_ids: qdrant_behavioral_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the documented triangle "200 ok / 400
#            invalid schema / 404 missing collection" is assumed to hold exactly; the
#            404-vs-400 face split and the persistence behind the 200 face are the
#            untested edges of this face)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral triangle x qdrant_behavioral_index_create_001 — all three documented
faces of PUT /collections/{collection_name}/index in dependency order on one bic009_*
collection: FACE 200 (valid keyword index on a live collection, wait=true) must return
HTTP 200 AND actually persist — judged via collections+get readback
result.payload_schema (R20 lesson: persistence judged via describe readback / index
schema echo, never status alone); envelope result is spec-declared as an object with
result.status: string and result.operation_id: [integer, null] — the live envelope shape
is RECORDED measured-only because run2r #1 R9 found spec-shape issues on this exact face
(spec wins on paper; no defect claim from envelope shape alone). FACE 400 (invalid field
schema {"type": "bogus"} — an unknown enum member, the canonical "invalid field schema")
must return 400/422. FACE 404 (identical valid body against a MISSING collection) must
return 404 — 200/400 there break the documented face split; afterwards the missing
collection must still be missing (no phantom creation).
[chunk_index+create coverage: behavioral triangle (200/400/404 faces) x
qdrant_behavioral_index_create_001 + strategy5 error-diagnostics legs on the 400/404
rejections]
Oracle: FACE 200 returns HTTP 200 with the bic009_* field key present in readback
result.payload_schema (200 without the key = Type4_StateLogicViolation); envelope
result.status is a string and result.operation_id an integer-or-null when result is an
object (a boolean result is printed as an R9 measured shape-conflict note, NOT a defect
claim); FACE 400 returns HTTP 400/422 with non-empty diagnostics naming the invalid
schema (empty body = Type2_PoorDiagnostics; 2xx = Type1_IllegalSuccess); FACE 404 returns
HTTP 404 exactly (200 = Type1_IllegalSuccess index created against a missing collection;
400 = Type4_StateLogicViolation face-split violation; 5xx = Type3_RuntimeFailure with
/healthz re-check); post-condition: GET on the missing collection still 404 and healthz
alive
Constraint: qdrant_behavioral_index_create_001 (bare id) — "valid index creation returns
HTTP 200; invalid schema (e.g. unknown type) returns 400; missing collection returns
404" (evidence_tier: explicit; level: endpoint)

Shape anchor (D3b): api_endpoints[index+create].response_shape declares result: object,
result.status: string, result.operation_id: [integer, null] — the object-form envelope is
asserted softly (string status / int-or-null operation_id when result is an object) and
any boolean-result divergence is a measured-only conflict note (R9 lesson on this face).
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

COLL = "bic009_" + uuid.uuid4().hex[:10]          # unique-prefix discipline (live)
MISSING = "bic009_missing_" + uuid.uuid4().hex[:10]  # unique name, never created
DIM = 4


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


def put_index(collection, body, timeout=60):
    """index+create face against an arbitrary collection name.
    wait is a QUERY parameter (placement check) — never body."""
    return safe_request("PUT", PATH_INDEX.format(collection_name=quote(collection, safe="")),
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

    # ---- Arrange: live collection + one payload point ----
    st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                              json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if st not in (200, 201):
        print(f"setup create {COLL} failed status={st}: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return
    st, _, raw = safe_request("PUT", PATH_UPSERT.format(collection_name=quote(COLL, safe="")),
                              json={"points": [{"id": 1, "vector": [0.1] * DIM,
                                                "payload": {"city": "berlin"}}]},
                              timeout=60, params={"wait": "true"})
    if st != 200:
        print(f"setup upsert failed status={st}: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
        return

    # ---- FACE 200: valid index on live collection ----
    st, body, raw = put_index(COLL, {"field_name": "city",
                                     "field_schema": {"type": "keyword"}})
    print(f"[face 200 valid keyword on {COLL}] -> status={st} raw={str(raw)[:300]}")
    if st <= 0 or 500 <= st <= 599:
        print("VERDICT: " + transport_verdict("face-200 valid create", st, raw)[1])
        return
    if st != 200:
        findings.append((0, f"Type1-signal (illegal rejection) - documented-legal index "
                            f"creation returned {st}, not 200: {str(raw)[:200]}"))
    else:
        # envelope: spec grid result: object {status: string, operation_id: int|null};
        # R9 conflict zone -> object form asserted softly, divergence measured-only
        res = body.get("result") if isinstance(body, dict) else None
        if isinstance(res, dict):
            rstatus = res.get("status")
            ropid = res.get("operation_id")
            ok_status = isinstance(rstatus, str)
            ok_opid = isinstance(ropid, int) or ropid is None
            print(f"  envelope result.status={rstatus!r} (string={ok_status}) "
                  f"result.operation_id={ropid!r} (int|null={ok_opid})")
            if not (ok_status and ok_opid):
                findings.append((2, f"Type4_StateLogicViolation - 200 envelope violates the "
                                    f"declared result grid (status: string, operation_id: "
                                    f"integer|null): result={str(res)[:200]}"))
        else:
            print(f"  [measure R9] envelope result={res!r} — spec grid declares object "
                  f"(shape conflict zone on this face, measured-only)")
        # persistence: the hard oracle
        ps, err = read_payload_schema()
        if ps is None:
            findings.append((3, f"readback unreadable after face-200 create: {err}"))
        elif "city" not in ps:
            findings.append((2, f"Type4_StateLogicViolation - face-200 create returned 200 "
                                f"but readback result.payload_schema lacks 'city' "
                                f"(status-code-only ok; nothing persisted)"))
        else:
            print(f"  OK(persist): 'city' in payload_schema, echo="
                  f"{json.dumps(ps['city'], ensure_ascii=False)!r}")

    # ---- FACE 400: invalid field schema (unknown enum member) ----
    st, body, raw = put_index(COLL, {"field_name": "city2",
                                     "field_schema": {"type": "bogus"}})
    print(f"[face 400 invalid schema type=bogus on {COLL}] -> status={st} "
          f"raw={str(raw)[:300]}")
    if st <= 0 or 500 <= st <= 599:
        findings.append(transport_verdict("face-400 invalid schema", st, raw))
    elif st == 404:
        findings.append((3, "face-400 probe got 404 on the LIVE collection (setup lost?)"))
    elif 400 <= st < 500:
        if not str(raw).strip():
            findings.append((0, "Type2_PoorDiagnostics - face-400 rejected with EMPTY "
                                "diagnostic body"))
        else:
            low = str(raw).lower()
            names_schema = ("type" in low or "schema" in low or "bogus" in low
                            or "variant" in low)
            print(f"  OK(reject): face-400 -> {st}; diagnostics name the schema/enum "
                  f"domain: {names_schema} (raw above)")
            if not names_schema:
                print("  [measure strategy5] rejection text does not mention the schema "
                      "slot/enum/unknown value — judge to weigh diagnostics quality")
    elif 200 <= st < 300:
        findings.append((0, f"Type1_IllegalSuccess - face-400: invalid schema 'bogus' "
                            f"accepted with {st}: {str(raw)[:200]}"))
    else:
        findings.append((3, f"uninterpreted status {st} on face-400"))

    # ---- FACE 404: identical valid body against a MISSING collection ----
    st, body, raw = put_index(MISSING, {"field_name": "city",
                                        "field_schema": {"type": "keyword"}})
    print(f"[face 404 valid body on MISSING {MISSING}] -> status={st} "
          f"raw={str(raw)[:300]}")
    if st <= 0 or 500 <= st <= 599:
        findings.append(transport_verdict("face-404 missing collection", st, raw))
    elif st == 404:
        if not str(raw).strip():
            findings.append((0, "Type2_PoorDiagnostics - face-404 returned 404 with EMPTY "
                                "diagnostic body"))
        else:
            print("  OK(reject): face-404 -> 404 exactly (documented face split holds)")
    elif 400 <= st < 500:
        findings.append((2, f"Type4_StateLogicViolation - face-404 returned {st}, not 404 "
                            f"(face-split violation: invalid-schema face answered a "
                            f"missing-collection probe): {str(raw)[:200]}"))
    elif 200 <= st < 300:
        findings.append((0, f"Type1_IllegalSuccess - face-404: index creation against a "
                            f"MISSING collection accepted with {st}: {str(raw)[:200]}"))
    else:
        findings.append((3, f"uninterpreted status {st} on face-404"))

    # ---- Post-condition: no phantom collection; service alive ----
    st, _, raw = safe_request("GET", PATH_GET.format(collection_name=quote(MISSING, safe="")),
                              timeout=30)
    print(f"[post] GET {MISSING} -> status={st} raw={str(raw)[:150]}")
    if st != 404:
        findings.append((2, f"Type4_StateLogicViolation - missing collection probe target "
                            f"now answers GET with {st} (phantom state): {str(raw)[:150]}"))
    hs, _, hraw = healthz()
    print(f"[post] /healthz -> status={hs}")
    if hs != 200:
        findings.append((0, f"Type3_RuntimeFailure - /healthz={hs} after triangle probes"))

    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
        else:
            print(f"VERDICT: DEFECT_FOUND ({msg})")
        return
    print("OK: behavioral triangle holds — 200 persisted via readback, 400 on invalid "
          "schema, 404 on missing collection, no phantom state")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
