#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_facet_004
# strategy: type_coercion
# endpoint: facet
# constraint_ids: qdrant_range_facet_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/facet
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust - the facet limit parameter is
#           declared "integer|null" with minimum 1 in the versioned OpenAPI; a REST
#           layer that silently coerces string/float/bool into an integer limit would
#           accept inputs outside the declared type space with 200 OK, producing
#           undefined count semantics - the exact class serde-gap blindspot describes)
"""
Attack: type_coercion (strategy 4) x qdrant_range_facet_001 on facet (chunk_facet
  unit constraints::qdrant_range_facet_001 - "facet limit minimum 1 (default 10);
  the v-1-18-x spec documents no maximum", evidence_tier=explicit, level=endpoint).
  The declared limit type is integer|null (FacetRequest.limit: type ["integer",
  "null"], minimum 1); inputs OUTSIDE the integer type space must not be silently
  coerced into a working integer limit:
    T1 limit="5"    (JSON string of a legal integer - must NOT be parsed as 5)
    T2 limit=5.5    (JSON float - not an integer; the nearest-integer silent
                     truncation/rounding failure mode would change count semantics)
    T3 limit=true   (JSON bool - must NOT coerce to 1, a legal-but-wrong limit)
    T4 limit=[5]    (JSON array - shape confusion)
    T5 limit={"n":5}(JSON object - shape confusion)
  Expected for T1-T5: HTTP 400/422 validation rejection (the serde/validation layer
  enforcing the declared type). ANY 2xx acceptance of T1-T5 = Type1_IllegalSuccess
  (a value outside the declared type space accepted with 200 OK - G5: not refusing
  when it should refuse).
  Type-space controls (G4 positive pairing, boundary closure on the TYPE face):
    C1 limit=null  -> schema-declared legal ("integer|null") -> must be accepted
      (200), behaving as the omitted-limit default; C2 limit=5 (integer) -> 200 with
      <= 5 hits. C1/C2 prove the fixture and the endpoint are live, so a 4xx on any
      T-probe is attributable to the type space, not the collection state.
  R17 reconciliation (G10): the pure range face (limit=0/-1 below-min rejection and
  limit=1/10/omitted acceptance) is owned by boundary_facet_001; this script owns the
  TYPE face of the same parameter (values that violate the declared type, not the
  declared range).
Oracle: on a live sfa04_* collection with genre keyword-indexed holding 4 distinct
  values over 25 points: facet {key: genre, limit: "5"} / {limit: 5.5} / {limit:
  true} / {limit: [5]} / {limit: {"n": 5}} each return HTTP 400/422 (any 2xx on any
  of T1-T5 = Type1_IllegalSuccess); the type-space controls {limit: null} and
  {limit: 5} each return HTTP 200 (a 4xx on the schema-legal null or integer 5 =
  Type1_IllegalRejection); 5xx or transport failure with /healthz not alive =
  Type3_RuntimeFailure; setup/transport failure with /healthz alive = SCRIPT_ERROR
  (G8).

Constraint anchor qdrant_range_facet_001 (explicit, endpoint): "facet limit minimum 1
  (default 10); the v-1-18-x spec documents no maximum" - the OpenAPI FacetRequest
  limit property typed ["integer", "null"] (type-space face exercised here).

[chunk_facet coverage: type_coercion x qdrant_range_facet_001 (limit type-space
  probes T1-T5 + type controls C1-C2)]
"""
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

import requests

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ----
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    for _p in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or str(TARGET).lower() != "qdrant":
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap three-layer fallback failed)")
    sys.exit(2)

# URL registry - verbatim from raw_knowledge.json api_endpoints[].url
PATH_FACET = "/collections/{collection_name}/facet"
PATH_CREATE = "/collections/{collection_name}"
PATH_DELETE = "/collections/{collection_name}"
PATH_UPSERT = "/collections/{collection_name}/points"
PATH_INDEX = "/collections/{collection_name}/index"

PFX = uuid.uuid4().hex[:8]
COLL = "sfa04_" + PFX
DIM = 4
DIST = {"alpha": 10, "beta": 8, "gamma": 5, "delta": 2}  # 25 points, 4 distinct values


def safe_request(method, endpoint, json=None, timeout=30, params=None):
    """Safe HTTP wrapper per agents/_target_api_reference.md. Returns (status, body, raw)."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(method=method, url=url, json=json,
                                    headers=headers, timeout=timeout, params=params)
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
    """Lightweight liveness probe (G8)."""
    return safe_request("GET", "/healthz", timeout=5)


def cleanup():
    """Teardown: best-effort delete of ONLY the collection this script created."""
    try:
        safe_request("DELETE", PATH_DELETE.format(collection_name=quote(COLL, safe="")),
                     timeout=30, params={"timeout": 30})
    except Exception:
        pass  # cleanup failures are non-fatal


def transport_or_5xx(probe, status, raw):
    """Verdict text for transport failure / 5xx after /healthz re-check."""
    hs, _, hraw = healthz()
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    if status <= 0:
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) - probe '{probe}' transport "
                    f"failure and /healthz={hs} (service down)")
        return f"SCRIPT_ERROR - probe '{probe}' transport failure with /healthz={hs} alive"
    return (f"DEFECT_FOUND (Type3_RuntimeFailure) - probe '{probe}' got {status} "
            f"with /healthz={hs}")


def judge_type_probe(probe, attack_val, status, raw):
    """Type-space violation probe: 4xx expected; any 2xx = Type1_IllegalSuccess."""
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if 400 <= status < 500:
        print(f"OK(reject): '{probe}' limit={attack_val!r} -> {status}: {str(raw)[:250]}")
        return None
    if 200 <= status < 300:
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) - '{probe}' facet limit="
                f"{attack_val!r} (type outside the declared integer|null space) "
                f"accepted with {status} - silent type coercion: {str(raw)[:300]}")
    return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"


def judge_type_control(probe, attack_val, status, raw):
    """Schema-legal type control: 200 expected."""
    if status <= 0 or 500 <= status <= 599:
        return transport_or_5xx(probe, status, raw)
    if 400 <= status < 500:
        return (f"DEFECT_FOUND (Type1_IllegalRejection) - '{probe}' schema-legal "
                f"limit={attack_val!r} rejected with {status}: {str(raw)[:250]}")
    if status != 200:
        return f"SCRIPT_ERROR - uninterpreted status {status} for probe '{probe}'"
    print(f"OK(200): '{probe}' limit={attack_val!r} accepted")
    return None


def main():
    print(f"ownership prefix: {PFX} collection={COLL}")
    pts = []
    pid = 1
    for genre, cnt in DIST.items():
        for _ in range(cnt):
            pts.append({"id": pid, "vector": [0.1] * DIM, "payload": {"genre": genre}})
            pid += 1
    try:
        # ---- Arrange: collection + keyword index + fixture ----
        st, _, raw = safe_request("PUT", PATH_CREATE.format(collection_name=quote(COLL, safe="")),
                                  json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
        if st not in (200, 201):
            print(f"setup create {COLL} failed status={st}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
            return
        st, _, raw = safe_request("PUT", PATH_UPSERT.format(collection_name=quote(COLL, safe="")),
                                  json={"points": pts}, timeout=60, params={"wait": "true"})
        if st != 200:
            print(f"setup upsert {len(pts)} points failed status={st}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
            return
        st, _, raw = safe_request("PUT", PATH_INDEX.format(collection_name=quote(COLL, safe="")),
                                  json={"field_name": "genre", "field_schema": "keyword"},
                                  timeout=60, params={"wait": "true"})
        if st != 200:
            print(f"setup keyword index on genre failed status={st}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR - setup failure, no defect conclusion")
            return

        # ---- type controls first (positive pairing): schema-legal null and integer ----
        for probe, val in (("C1 limit=null", None), ("C2 limit=5", 5)):
            body = {"key": "genre"}
            if val is not None:
                body["limit"] = val
            else:
                body["limit"] = None  # explicit JSON null (integer|null space)
            st, _, raw = safe_request("POST",
                                      PATH_FACET.format(collection_name=quote(COLL, safe="")),
                                      json=body, timeout=60)
            print(f"[probe {probe}] -> status={st} raw={str(raw)[:300]}")
            v = judge_type_control(probe, val, st, raw)
            if v is not None:
                print("VERDICT: " + v)
                return

        # ---- type-space violation probes ----
        for probe, val in (("T1 str '5'", "5"), ("T2 float 5.5", 5.5),
                           ("T3 bool true", True), ("T4 array [5]", [5]),
                           ("T5 object {n:5}", {"n": 5})):
            st, _, raw = safe_request("POST",
                                      PATH_FACET.format(collection_name=quote(COLL, safe="")),
                                      json={"key": "genre", "limit": val}, timeout=60)
            print(f"[probe {probe}] limit={val!r} -> status={st} raw={str(raw)[:300]}")
            v = judge_type_probe(probe, val, st, raw)
            if v is not None:
                print("VERDICT: " + v)
                return

        print("OK: schema-legal null/integer limits accepted; string/float/bool/array/"
              "object limits all rejected 4xx (no silent type coercion of facet limit)")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
