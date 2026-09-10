#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_create_007
# strategy: strategy6_resource_limit
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-07 (Resource Exhaustion Optimism — no documented upper bound on
#            field_name length; an unbounded allocator path could OOM/500/timeout on
#            a single huge string instead of rejecting it cheaply)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 resource-limit x index+create field_name (the only unbounded user
string on this face; index+create declares NO numeric parameter, so the string-size
resource face is the applicable target) — overlong field_name values 100_000 chars
(~100 KB) and 1_000_000 chars (~1 MB) are PUT on a live bic007_* collection. The
contract documents no length bound, so EITHER disposition is legal: graceful 200
(persisted, readback echo) OR explicit 4xx rejection — the defect signal is ONLY a
crash class outcome: 5xx, OOM/panic keywords, connection reset, or transport timeout.
After the probes a post-attack liveness leg re-PUTs a legal control index to prove the
face is not wedged (G8: crash vs reject vs accept isolation; 200-with-fewer-effects is
NOT a defect on a resource probe — strategy-6 key). Legal control index first (G4).
[chunk_index+create coverage: strategy6 resource-limit x index+create field_name
(string-size resource face; no numeric param exists on this endpoint in this chunk)]
Oracle: on the live bic007_* collection the legal control returns 200 with the control
key in readback result.payload_schema; each overlong field_name probe yields EITHER
200 with the readback key echo printed (graceful accept) OR 400/422 (explicit reject)
— BOTH are NO_DEFECT paths; 500/502/503/504 or panic/OOM keywords in the raw text or
transport failure re-checked against /healthz (down = Type3_RuntimeFailure, alive =
SCRIPT_ERROR for the transport branch) = DEFECT; the post-attack control index must
still return 200 (a wedged face after the probe = Type4_StateLogicViolation)
Constraint: qdrant_type_index_create_001 (bare id) — field_schema domain on the same
face (resource robustness of the surrounding request path; evidence_tier: explicit;
level: endpoint)

Shape anchor (D3b): no numeric parameter is declared on index+create in this chunk
(wait/timeout query params belong to faces outside the dispatched units) — the
resource face targets the unbounded string slot; readback anchor collections+get
result.payload_schema: object (huge keys printed length-only, never echoed raw).
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

COLL = "bic007_" + uuid.uuid4().hex[:10]  # unique-prefix discipline
DIM = 4

OVERLONG = [
    ("field_name 100_000 chars (~100 KB)", "big100k_" + "a" * 100_000),
    ("field_name 1_000_000 chars (~1 MB)", "big1m_" + "a" * 1_000_000),
]

CRASH_KEYWORDS = ("oom", "out of memory", "panic", "capacity overflow", "killed",
                  "allocation", "backtrace")


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
                                 timeout=60)
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

    # ---- Legal control first (G4) ----
    st, _, raw = put_index("res_ctrl", {"type": "keyword"})
    print(f"[control keyword] PUT index res_ctrl -> status={st} raw={str(raw)[:200]}")
    if st <= 0 or 500 <= st <= 599:
        print("VERDICT: " + transport_verdict("legal control", st, raw)[1])
        return
    if st != 200:
        print(f"VERDICT: SCRIPT_ERROR - legal control rejected {st}: {str(raw)[:200]}")
        return
    print("OK(control): valid keyword index accepted")

    # ---- Act + Assert: overlong field_name; only CRASH outcomes are defects ----
    for label, field in OVERLONG:
        st, body, raw = put_index(field, {"type": "keyword"}, timeout=120)
        low = str(raw).lower()
        print(f"[probe {label}] -> status={st} raw[:250]={str(raw)[:250]}")
        if any(k in low for k in CRASH_KEYWORDS) and st >= 500:
            findings.append((0, f"Type3_RuntimeFailure - probe '{label}' got {st} with "
                                f"crash keywords in body: {str(raw)[:200]}"))
            continue
        if st <= 0 or 500 <= st <= 599:
            findings.append(transport_verdict(label, st, raw))
            continue
        if st == 404:
            findings.append((3, f"probe '{label}' got 404 on live collection {COLL}"))
            continue
        if 400 <= st < 500:
            print(f"  OK(reject): '{label}' -> {st} (explicit length rejection, legal)")
            continue
        if 200 <= st < 300:
            ps, err = read_payload_schema()
            if ps is None:
                findings.append((3, f"readback unreadable after 2xx on '{label}': {err}"))
                continue
            hit = [k for k in ps.keys() if k.startswith("big") and len(k) > 1000]
            if hit:
                print(f"  OK(accept): '{label}' 200 and persisted "
                      f"(readback key len={len(hit[0])}) — graceful accept, not a defect")
            else:
                print(f"  [measure] '{label}' 200 but readback lacks the huge key "
                      f"(silent-drop; lengths present: "
                      f"{sorted(len(k) for k in ps.keys())[-3:]}) — judge material")
            continue
        findings.append((3, f"uninterpreted status {st} for probe '{label}'"))

    # ---- Post-attack liveness: the face must not be wedged ----
    st, _, raw = put_index("res_post", {"type": "integer"})
    print(f"[post-attack control integer] -> status={st} raw={str(raw)[:200]}")
    if st != 200:
        if st <= 0 or 500 <= st <= 599:
            findings.append(transport_verdict("post-attack control", st, raw))
        else:
            findings.append((2, f"Type4_StateLogicViolation - post-attack control index "
                                f"rejected with {st} after overlong probes (face wedged "
                                f"or state corrupted): {str(raw)[:200]}"))

    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
        else:
            print(f"VERDICT: DEFECT_FOUND ({msg})")
        return
    print("OK: no crash on overlong field_name (graceful accept or explicit reject only); "
          "face alive afterwards")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
