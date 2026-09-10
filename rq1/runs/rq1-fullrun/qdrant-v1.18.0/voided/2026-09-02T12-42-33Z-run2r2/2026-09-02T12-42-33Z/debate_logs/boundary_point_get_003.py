#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_point_get_003
# strategy: strategy2 type-boundary attack (id path param: the UUID branch of the PointId oneOf)
# endpoint: point+get
# constraint_ids: qdrant_behavioral_point_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/get-point
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the PointId oneOf's
#            string branch accepts UUID only; near-UUID strings must be
#            rejected, not fuzzy-matched to a stored point)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_behavioral_point_get_001 —
  exercising the UUID branch of PointId (oneOf uint64 / UUID string)
  on the single-point read face. Faces (collection holds one point
  stored under a lowercase UUIDv4 and integer point 9): (A) positive
  UUID branch: GET the stored UUID -> 200 with its Record, result.id
  equal to the stored UUID string (envelope result.<field>); (B)
  missing-point leg on the UUID branch: a different, well-formed
  random UUIDv4 -> 404 promised; (C) malformed UUID (invalid hex char
  Z in the last group, never created) -> 400/422 clean domain
  rejection, or 404 tolerant NOTE; a 200 = Type1_IllegalSuccess (a
  Record served for a malformed UUID — also fakes existence); 5xx =
  Type3; (D) near-miss UUID: the stored UUID with its LAST hex digit
  incremented (well-formed, does not exist) -> 404 promised (200 =
  Type1 zombie / fuzzy match); (E) case face: the stored UUID in
  UPPERCASE -> trichotomy NOTE (200-with-matching-uuid = tolerant
  case normalization, 404/400 = strict posture — the versioned
  OpenAPI pattern is lowercase; no documented case contract, so no
  defect claim, recorded for the judge); control face Z: integer id 9
  -> 200 with result.id == 9 (pins the promise). Error-naming on 4xx
  is NOTE only (R29).
  [chunk_point+get coverage: strategy2 type-boundary x
  qdrant_behavioral_point_get_001, id UUID-branch faces (this script;
  id uint64 closure in boundary_point_get_001, id non-UUID string
  forms in boundary_point_get_002, id malformed/character faces in
  boundary_point_get_004, collection_name faces in boundary_point_get_005)]
Oracle: face A -> 200 with result.id == stored UUID (non-200 or
  mismatched id = Type1_IllegalSuccess promise face); face B/D ->
  404 (200 with any Record = Type1_IllegalSuccess zombie; 5xx with
  /healthz alive = Type3_RuntimeFailure; 400/422 = strict NOTE);
  face C -> 400/422 clean or 404 tolerant NOTE, 200 =
  Type1_IllegalSuccess, 5xx = Type3; face E -> any of 200-with-
  matching-uuid / 404 / 400 (all NOTE — no documented case contract;
  200 with a DIFFERENT id = Type1); control Z -> 200 with
  result.id == 9; transport failures -> /healthz liveness re-check
  then SCRIPT_ERROR (constraint qdrant_behavioral_point_get_001).
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
        return str(got).lower() == str(want).lower()


def judge_missing(label, s, raw, body):
    """Well-formed UUID that was never stored -> 404 promised.
    200 = Type1 zombie; 5xx (healthz-gated) = Type3; 400/422 strict NOTE."""
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
              f"Record id={rid!r} for a never-stored UUID (zombie/fuzzy match): "
              f"{raw[:300]}")
        return False
    if s == 404:
        print(f"{label}: 404 — promise kept")
        return True
    if s in (400, 422):
        print(f"{label}: {s} strict-validation NOTE (error-naming NOTE only, R29)")
        return True
    print(f"NOTE: {label} returned unexpected status {s}; recorded for the judge: {raw[:200]}")
    return True


def judge_malformed(label, s, raw, body):
    """Malformed UUID (invalid hex) -> 400/422 clean; 404 tolerant NOTE;
    200 = Type1; 5xx = Type3."""
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
              f"Record id={rid!r} for a MALFORMED UUID (not a PointId at all; "
              f"also fakes existence): {raw[:300]}")
        return False
    if s == 404:
        print(f"{label}: 404 tolerant-parse posture (acceptable)")
        return True
    if s in (400, 422):
        print(f"{label}: {s} clean domain rejection (error-naming NOTE only, R29)")
        return True
    print(f"NOTE: {label} returned unexpected status {s}; recorded for the judge: {raw[:200]}")
    return True


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpg3" + tag
    stored_uuid = str(uuid.uuid4())           # lowercase canonical
    other_uuid = str(uuid.uuid4())            # well-formed, never stored
    last = stored_uuid[-1]
    bumped = (str(int(last, 16) + 1), "0")[last == "f"]
    near_uuid = stored_uuid[:-1] + bumped     # well-formed near miss
    malformed_uuid = stored_uuid[:-1] + "Z"   # invalid hex char

    # Arrange: data-bearing collection (own data, own cleanup)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    pts = [{"id": stored_uuid, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"n": "uuid"}},
           {"id": 9, "vector": [0.2, 0.3, 0.4, 0.5], "payload": {"n": 9}}]
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
        # ---- Face A: positive UUID branch ----
        s, body, raw = safe_request("GET", f"/collections/{coll}/points/{stored_uuid}", timeout=30)
        print(f"face A stored UUID -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            if not transport_dead("face A"):
                return
        elif s == 200 and ids_equal(record_id_of(body), stored_uuid):
            print("face A OK: 200 with Record result.id == stored UUID")
        else:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — face A: stored "
                  f"UUID point read returned {s} (id={record_id_of(body)!r}); "
                  f"promise: 200 with its Record: {raw[:300]}")
            return

        # ---- Face B: different well-formed UUID (never stored) -> 404 ----
        s, body, raw = safe_request("GET", f"/collections/{coll}/points/{other_uuid}", timeout=30)
        print(f"\nface B other random UUID -> status={s}")
        print(f"raw: {raw[:400]}")
        if not judge_missing("face B other UUID", s, raw, body):
            return

        # ---- Face C: malformed UUID (invalid hex) ----
        s, body, raw = safe_request("GET", f"/collections/{coll}/points/{malformed_uuid}", timeout=30)
        print(f"\nface C malformed UUID (hex Z) -> status={s}")
        print(f"raw: {raw[:400]}")
        if not judge_malformed("face C malformed UUID", s, raw, body):
            return

        # ---- Face D: near-miss UUID (last digit bumped, never stored) -> 404 ----
        s, body, raw = safe_request("GET", f"/collections/{coll}/points/{near_uuid}", timeout=30)
        print(f"\nface D near-miss UUID -> status={s}")
        print(f"raw: {raw[:400]}")
        if not judge_missing("face D near-miss UUID", s, raw, body):
            return

        # ---- Face E: stored UUID in UPPERCASE (case face, NOTE only) ----
        s, body, raw = safe_request("GET", f"/collections/{coll}/points/{stored_uuid.upper()}", timeout=30)
        print(f"\nface E uppercase UUID -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            if not transport_dead("face E"):
                return
        elif 500 <= s <= 599:
            hs, _, _ = safe_request("GET", "/healthz", timeout=10)
            if hs == 200:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — face E: 5xx {s} with service alive")
                return
            print("VERDICT: SCRIPT_ERROR — face E 5xx and healthz down")
            return
        elif 200 <= s <= 299:
            rid = record_id_of(body)
            if ids_equal(rid, stored_uuid):
                print("NOTE: face E: 200 with matching Record — tolerant "
                      "case-normalization of the UUID string branch (RFC 4122 "
                      "case-insensitivity; no documented case contract — for the judge)")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — face E: 200 "
                      f"with Record id={rid!r} != stored UUID: {raw[:300]}")
                return
        elif s in (400, 404, 422):
            print(f"NOTE: face E: {s} strict-case posture (OpenAPI pattern is "
                  f"lowercase; no documented case contract — for the judge)")
        else:
            print(f"NOTE: face E returned unexpected status {s}; recorded for the judge")

        # ---- Control Z: integer branch still healthy ----
        s, body, raw = safe_request("GET", f"/collections/{coll}/points/9", timeout=30)
        print(f"\ncontrol Z integer id 9 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            if not transport_dead("control Z"):
                return
        elif s == 200 and ids_equal(record_id_of(body), 9):
            print("control Z OK: 200 with Record result.id == 9")
        else:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — control Z: "
                  f"existing integer point 9 read returned {s} "
                  f"(id={record_id_of(body)!r}): {raw[:300]}")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
