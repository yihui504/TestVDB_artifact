#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_point_get_001
# strategy: strategy1 boundary-value attack (uint64 id-domain closure + the assertion's core 200/404 promise)
# endpoint: point+get
# constraint_ids: qdrant_behavioral_point_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/get-point
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the corners of the PointId
#            uint64 domain: min 0 and max 2^64-1 must still read back 200,
#            and one-step-outside ids (-1, 2^64) must not turn into 200/5xx)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value x qdrant_behavioral_point_get_001 — the
  single-point read face's whole promise with the id parameter driven to
  its uint64 domain edges. PointId is oneOf unsigned-integer(uint64) /
  UUID string [versioned OpenAPI]. Faces: (A) positive core: point 1
  exists -> GET must be 200 with its Record (envelope result.<field>,
  result.id == 1); (B/C) min/max closure: points with id 0 (uint64 min)
  and id 18446744073709551615 (uint64 max) are created and read back ->
  200 with result.id equal (boundary closure: min/max themselves must be
  accepted, G4); (D) missing point: id 424242 never inserted -> 404
  promised; (E) below-domain id -1 and (F) above-domain id 2^64
  (18446744073709551616, outside uint64): a 400 is the clean
  strict-validation answer, a 404 is a tolerant-parse NOTE (an
  out-of-domain id denotes no existing point — truthful), a 200 is
  Type1_IllegalSuccess (a Record served for an id that cannot exist as
  a PointId), a 5xx is Type3; (G) missing-collection control: same GET
  on a never-created collection -> 404 promised (the assertion's third
  leg). 4xx error-naming quality is NOTE only (R29: Type2 error-naming
  has no anchor).
  [chunk_point+get coverage: strategy1 boundary-value x
  qdrant_behavioral_point_get_001, id uint64 closure + core 200/404/404
  promise (this script; id string-form type faces in
  boundary_point_get_002, id UUID-branch faces in boundary_point_get_003,
  id malformed/character faces in boundary_point_get_004,
  collection_name promise/lifecycle faces in boundary_point_get_005)]
Oracle: face A/C/D existing points -> HTTP 200 with result.id equal to
  the requested id (non-200 on an existing point or 200 without the
  promised Record = promise violation, Type1_IllegalSuccess per the
  assertion's defect_type_if_violated); face E missing point -> 404
  (200 = Type1_IllegalSuccess zombie record; 5xx with /healthz alive =
  Type3_RuntimeFailure); faces F/G out-of-domain ids (-1, 2^64) ->
  400 clean / 404 tolerant NOTE / 200 = Type1_IllegalSuccess / 5xx =
  Type3; face H missing collection -> 404 (200 = Type1_IllegalSuccess;
  5xx = Type3); transport failures -> /healthz liveness re-check then
  SCRIPT_ERROR, no defect conclusion (constraint
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
    """Envelope result.<field>: pull the Record's id from the 200 body.
    Returns None when no decodable Record is present."""
    if not isinstance(body, dict):
        return None
    rec = body.get("result")
    if not isinstance(rec, dict) and "id" in body:
        rec = body  # bare-record tolerance; Record always carries id
    if isinstance(rec, dict):
        return rec.get("id")
    return None


def ids_equal(got, want):
    """Normalize numeric ids (int or digit-string) before comparing."""
    if got is None:
        return False
    try:
        return int(got) == int(want)
    except (TypeError, ValueError):
        return str(got) == str(want)


def judge_missing_face(label, s, raw, body):
    """Declared expectation: a never-existing target -> 404.
    200 = Type1_IllegalSuccess (zombie); 5xx (healthz-gated) = Type3;
    400/422 = strict-validation NOTE (acceptable); 404 = promise kept."""
    if s == -1:
        return transport_dead(label)
    if 500 <= s <= 599:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        if hs == 200:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: server "
                  f"error {s} with service alive (healthz 200): {raw[:300]}")
        else:
            print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down (healthz {hs})")
        return False
    if s == 200:
        rid = record_id_of(body)
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: 200 with "
              f"Record id={rid!r} for a target the assertion promises as 404 "
              f"(zombie record): {raw[:300]}")
        return False
    if s in (400, 422):
        low = raw.lower()
        names = [w for w in ("id", "point", "parse", "collection") if w in low]
        print(f"{label}: strict 4xx ({s}) validation answer (mentions: "
              f"{names or 'no anchor word'} — NOTE only, R29)")
        return True
    if s == 404:
        print(f"{label}: 404 — promise kept")
        return True
    print(f"NOTE: {label} returned unexpected status {s}; recorded for the judge: {raw[:200]}")
    return True


def judge_out_of_domain_face(label, s, raw, body):
    """Declared expectation for ids outside the PointId uint64 domain
    (-1, 2^64): 400 clean / 404 tolerant NOTE / 200 Type1 / 5xx Type3."""
    if s == -1:
        return transport_dead(label)
    if 500 <= s <= 599:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        if hs == 200:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: server "
                  f"error {s} with service alive: {raw[:300]}")
        else:
            print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down (healthz {hs})")
        return False
    if 200 <= s <= 299:
        rid = record_id_of(body)
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: 2xx with "
              f"Record id={rid!r} for an id outside the uint64 PointId domain "
              f"(no such PointId can exist): {raw[:300]}")
        return False
    if s == 404:
        print(f"{label}: 404 tolerant-parse posture (out-of-domain id treated as "
              f"absent — truthful, acceptable)")
        return True
    if s in (400, 422):
        print(f"{label}: {s} clean domain rejection (error-naming NOTE only, R29)")
        return True
    print(f"NOTE: {label} returned unexpected status {s}; recorded for the judge: {raw[:200]}")
    return True


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpg1" + tag
    ghost_coll = "bpg1missing" + tag
    umax = 18446744073709551615  # uint64 max (2^64 - 1)

    # Arrange: data-bearing collection (own data, own cleanup)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    pts = [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"n": 1}},
           {"id": 0, "vector": [0.2, 0.3, 0.4, 0.5], "payload": {"n": 0}},
           {"id": umax, "vector": [0.3, 0.4, 0.5, 0.6], "payload": {"n": "max"}}]
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": pts}, params={"wait": "true"}, timeout=60)
    created_zero = created_max = True
    if s not in (200, 201):
        # id=0 / id=umax might be rejected by upsert; retry with the safe core id
        s2, _, raw2 = safe_request("PUT", f"/collections/{coll}/points",
                                   json={"points": [pts[0]]}, params={"wait": "true"}, timeout=60)
        if s2 not in (200, 201):
            print(f"setup upsert failed status={s2}/{s}: {raw2[:200]} / {raw[:200]}")
            try:
                safe_request("DELETE", f"/collections/{coll}", timeout=30)
            except Exception:
                pass
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        created_zero = created_max = False
        print(f"NOTE: full-domain upsert rejected ({s}); min/max closure faces "
              f"degrade to missing-point posture")
    try:
        # ---- Face A: positive core (point 1 exists -> 200 with its Record) ----
        s, body, raw = safe_request("GET", f"/collections/{coll}/points/1", timeout=30)
        print(f"\nface A existing point 1 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            if not transport_dead("face A"):
                return
        elif 500 <= s <= 599:
            hs, _, _ = safe_request("GET", "/healthz", timeout=10)
            if hs == 200:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — face A: 5xx {s} with service alive")
                return
            print("VERDICT: SCRIPT_ERROR — face A 5xx and healthz down")
            return
        elif s == 200:
            rid = record_id_of(body)
            if not ids_equal(rid, 1):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — face A: 200 "
                      f"but Record id={rid!r} != 1 (promise: 200 WITH the Record): {raw[:300]}")
                return
            print("face A OK: 200 with Record result.id == 1")
        else:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — face A: existing "
                  f"point read returned {s} (promise: 200 with Record): {raw[:300]}")
            return

        # ---- Faces B/C: min / max uint64 closure ----
        for label, pid in (("face B min id=0", 0), ("face C max id=2^64-1", umax)):
            created = created_zero if pid == 0 else created_max
            s, body, raw = safe_request("GET", f"/collections/{coll}/points/{pid}", timeout=30)
            print(f"\n{label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                if not transport_dead(label):
                    return
                continue
            if 500 <= s <= 599:
                hs, _, _ = safe_request("GET", "/healthz", timeout=10)
                if hs == 200:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: 5xx {s} with service alive")
                    return
                print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
                return
            if created:
                if s != 200 or not ids_equal(record_id_of(body), pid):
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"created boundary point read returned {s} "
                          f"(id={record_id_of(body)!r}); promise: 200 with its Record: {raw[:300]}")
                    return
                print(f"{label} OK: 200 with Record result.id == {pid} (closure accepted)")
            else:
                if not judge_missing_face(label + " (not created)", s, raw, body):
                    return

        # ---- Face D: missing point (never inserted id) -> 404 promised ----
        s, body, raw = safe_request("GET", f"/collections/{coll}/points/424242", timeout=30)
        print(f"\nface D missing point 424242 -> status={s}")
        print(f"raw: {raw[:400]}")
        if not judge_missing_face("face D missing point", s, raw, body):
            return

        # ---- Faces E/F: out-of-domain ids (-1 and 2^64) ----
        for label, pid in (("face E below-domain id=-1", "-1"),
                           ("face F above-domain id=2^64", "18446744073709551616")):
            s, body, raw = safe_request("GET", f"/collections/{coll}/points/{pid}", timeout=30)
            print(f"\n{label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if not judge_out_of_domain_face(label, s, raw, body):
                return

        # ---- Face G: missing collection control -> 404 promised ----
        s, body, raw = safe_request("GET", f"/collections/{ghost_coll}/points/1", timeout=30)
        print(f"\nface G missing collection -> status={s}")
        print(f"raw: {raw[:400]}")
        if not judge_missing_face("face G missing collection", s, raw, body):
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
