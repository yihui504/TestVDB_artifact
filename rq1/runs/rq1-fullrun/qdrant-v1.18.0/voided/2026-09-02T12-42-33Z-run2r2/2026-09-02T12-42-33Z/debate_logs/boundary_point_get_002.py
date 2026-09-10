#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_point_get_002
# strategy: strategy2 type-boundary attack (id path param: string forms that are neither uint64 nor UUID)
# endpoint: point+get
# constraint_ids: qdrant_behavioral_point_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/get-point
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the id wire value is a
#            string; the server must parse it as uint64 OR UUID and reject
#            everything else instead of coercing loose numeric string forms)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_behavioral_point_get_001 — the
  PointId domain is oneOf unsigned-integer(uint64) / UUID string
  [versioned OpenAPI]; every other wire form in the {id} path segment is
  out of domain. Faces (all on an existing collection holding points 5
  and 7): (A) non-numeric garbage "abc"; (B) float form "1.5"; (C)
  scientific form "1e3"; (D) hex form "0x10"; (E) empty id -> URL
  /collections/{c}/points/ (segment absent). For A-E the promise space:
  400/422 = clean domain rejection; 404 = tolerant-parse NOTE (an
  unparseable id denotes no existing point — truthful under the
  assertion's 404 leg); 200 = Type1_IllegalSuccess (a Record served for
  an id that is not a PointId — these were never created, so 200 also
  fakes existence); 5xx = Type3. Faces F/G/H are lenient-numeric-coercion
  probes (leading-space " 7", plus-sign "+7", leading-zero "007" with
  point 7 PRESENT): a 200 whose Record id == 7 means the server coerced
  a non-canonical numeric string — NOTE for the judge (point 7 exists,
  so the existence legs are not violated; the question is PointId
  string-branch leniency, UUID-only per the OpenAPI pattern); 400/404 =
  strict posture, clean. Control face Z: id "5" -> must be 200 with
  result.id == 5 (pins the promise so rejections above cannot be
  wholesale 404 sloppiness). Error-naming quality on 4xx is NOTE only
  (R29).
  [chunk_point+get coverage: strategy2 type-boundary x
  qdrant_behavioral_point_get_001, id non-UUID string-form faces (this
  script; id uint64 closure in boundary_point_get_001, id UUID-branch
  faces in boundary_point_get_003, id malformed/character faces in
  boundary_point_get_004, collection_name faces in boundary_point_get_005)]
Oracle: faces A-E (never-created, out-of-domain string ids) -> 400/422
  clean or 404 tolerant NOTE; 200 with any Record = Type1_IllegalSuccess;
  5xx with /healthz alive = Type3_RuntimeFailure. Faces F/G/H
  (non-canonical numeric strings, point 7 present) -> 200 with
  result.id == 7 = lenient-coercion NOTE for the judge; 400/404 = strict
  clean; 200 with a DIFFERENT id = Type1_IllegalSuccess; 5xx = Type3.
  Control Z -> 200 with result.id == 5 (anything else =
  Type1_IllegalSuccess promise face); transport failures -> /healthz
  liveness re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_point_get_001).
Constraint: qdrant_behavioral_point_get_001 (bare id) — "returns 200
  with the Record; 404 when the point or the collection does not exist"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  point+get            -> GET  /collections/{collection_name}/points/{id}
  points+upsert        -> PUT  /collections/{collection_name}/points
  collections+create   -> PUT  /collections/{collection_name}
  collections+delete   -> DELETE /collections/{collection_name}
  healthz              -> GET  /healthz
  (wait is a query parameter on the upsert face — passed via params=)
"""

import json
import os
import sys
import uuid
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap: three-layer fallback (env -> upward walk -> contract target) ---
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
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)


def safe_request(method, endpoint, json=None, timeout=30, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Path segments are embedded in `endpoint`; query params via params=.
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, headers=headers,
            timeout=timeout, params=params,
        )
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except Exception:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def transport_dead(where):
    """Liveness re-check on the lightweight healthz face (transport branch)."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    print(f"transport failure on {where} (healthz status={hs}: {str(hraw)[:200]})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return False


def record_id_of(body):
    """Envelope result.<field>: pull the Record's id from the 200 body."""
    if not isinstance(body, dict):
        return None
    rec = body.get("result")
    if not isinstance(rec, dict) and "id" in body:
        rec = body  # bare-record tolerance; Record always carries id
    if isinstance(rec, dict):
        return rec.get("id")
    return None


def ids_equal(got, want):
    try:
        return int(got) == int(want)
    except (TypeError, ValueError):
        return str(got) == str(want)


def base_branch(label, s, raw, body):
    """Faces A-E: never-created, out-of-domain string ids.
    400/422 clean; 404 tolerant NOTE; 200 = Type1; 5xx = Type3."""
    if s == -1:
        return transport_dead(label)
    if 500 <= s <= 599:
        hs, _, _ = safe_request("GET", "/healthz", timeout=10)
        if hs == 200:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: server "
                  f"error {s} with service alive: {raw[:300]}")
        else:
            print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
        return False
    if 200 <= s <= 299:
        rid = record_id_of(body)
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: 2xx with "
              f"Record id={rid!r} for a string id that is neither uint64 nor "
              f"UUID (never created — 200 also fakes existence): {raw[:300]}")
        return False
    if s == 404:
        print(f"{label}: 404 tolerant-parse posture (acceptable)")
        return True
    if s in (400, 422):
        print(f"{label}: {s} clean domain rejection (error-naming NOTE only, R29)")
        return True
    print(f"NOTE: {label} returned unexpected status {s}; recorded for the judge: {raw[:200]}")
    return True


def coercion_branch(label, s, raw, body):
    """Faces F/G/H: non-canonical numeric strings with point 7 present.
    200+id7 = lenient-coercion NOTE; 200+other-id = Type1; 4xx strict clean."""
    if s == -1:
        return transport_dead(label)
    if 500 <= s <= 599:
        hs, _, _ = safe_request("GET", "/healthz", timeout=10)
        if hs == 200:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: server "
                  f"error {s} with service alive: {raw[:300]}")
        else:
            print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
        return False
    if 200 <= s <= 299:
        rid = record_id_of(body)
        if ids_equal(rid, 7):
            print(f"NOTE: {label}: 200 with Record id={rid!r} — the server coerced "
                  f"a non-canonical numeric string to point 7 (PointId string "
                  f"branch is UUID-only per the OpenAPI pattern; leniency "
                  f"recorded for the judge — existence legs not violated)")
            return True
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: 200 with "
              f"Record id={rid!r} != 7 (record served for a different id): {raw[:300]}")
        return False
    if s in (400, 404, 422):
        print(f"{label}: {s} strict-parse posture (clean)")
        return True
    print(f"NOTE: {label} returned unexpected status {s}; recorded for the judge: {raw[:200]}")
    return True


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpg2" + tag

    # Arrange: data-bearing collection (own data, own cleanup)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    pts = [{"id": 5, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"n": 5}},
           {"id": 7, "vector": [0.2, 0.3, 0.4, 0.5], "payload": {"n": 7}}]
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": pts}, params={"wait": "true"}, timeout=60)
    if s not in (200, 201):
        print(f"setup upsert failed status={s}: {raw[:300]}")
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # ---- Control Z: canonical numeric id 5 -> must be 200 with its Record ----
        s, body, raw = safe_request("GET", f"/collections/{coll}/points/5", timeout=30)
        print(f"control Z canonical id 5 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            if not transport_dead("control Z"):
                return
        elif s == 200 and ids_equal(record_id_of(body), 5):
            print("control Z OK: 200 with Record result.id == 5")
        else:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — control Z: "
                  f"existing point 5 read returned {s} "
                  f"(id={record_id_of(body)!r}); promise: 200 with Record: {raw[:300]}")
            return

        # ---- Faces A-E: out-of-domain string ids (never created) ----
        for label, pid in (
            ("face A non-numeric 'abc'", "abc"),
            ("face B float form '1.5'", "1.5"),
            ("face C scientific '1e3'", "1e3"),
            ("face D hex form '0x10'", "0x10"),
            ("face E empty id (segment absent)", ""),
        ):
            s, body, raw = safe_request("GET", f"/collections/{coll}/points/{pid}", timeout=30)
            print(f"\n{label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if not base_branch(label, s, raw, body):
                return

        # ---- Faces F/G/H: lenient-numeric-coercion probes (point 7 present) ----
        for label, pid in (
            ("face F leading-space ' 7'", " 7"),
            ("face G plus-sign '+7'", "+7"),
            ("face H leading-zero '007'", "007"),
        ):
            s, body, raw = safe_request("GET", f"/collections/{coll}/points/{pid}", timeout=30)
            print(f"\n{label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if not coercion_branch(label, s, raw, body):
                return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
