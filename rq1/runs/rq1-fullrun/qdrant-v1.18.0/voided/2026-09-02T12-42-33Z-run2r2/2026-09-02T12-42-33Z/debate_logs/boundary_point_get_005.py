#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_point_get_005
# strategy: strategy1 boundary-value attack (collection_name: the assertion's 404-when-collection-missing leg) + lifecycle mutation + strategy7 malformed name faces
# endpoint: point+get
# constraint_ids: qdrant_behavioral_point_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/get-point
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the collection_name
#            parameter's degenerate corners: missing, empty, NUL-truncated
#            alias, hostile encodings, and the post-deletion lifecycle
#            corner; every one must resolve to a clean 404/4xx, never a
#            served Record and never a 5xx)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value x qdrant_behavioral_point_get_001 — the
  collection_name half of the single-point read promise ("404 when the
  point OR THE COLLECTION does not exist"). Faces: (A) never-created
  collection + well-formed id 1 -> 404 promised; (B) never-created
  collection + garbage id "abc" -> the collection leg must still yield
  404 (400 strict-validation NOTE acceptable; 200 = Type1; 5xx = Type3
  — validation-order must not become a crash); (C) EMPTY collection
  name -> /collections//points/1 -> 4xx clean (200 = Type1); (D)
  NUL-truncation aliasing: GET on "{base}%00suffix" where base is this
  script's OWN live collection holding point 1 — a 200 WITH the Record
  means the server truncated the decoded name at NUL and served a
  DIFFERENT collection's point = identifier confusion
  (Type1_IllegalSuccess); 4xx/404 = clean; (E) lone-surrogate name
  "%ED%A0%80..." (illegal Unicode) -> 4xx/404; 5xx = Type3; (F)
  traversal name "..%2F..%2F..." -> 4xx/404 (no path escape, no
  leakage); (G) overlong name 8000 chars -> 4xx (incl. 414) / 404; no
  OOM/5xx; (H) lifecycle mutation: control GET point 5 on the live
  collection -> 200 (pinned), then DELETE the collection wait=true,
  then GET the same point -> 404 promised. Mutation justification (G6):
  collection deletion is the lifecycle mutation most likely to leave a
  stale single-point read (segment tombstone / cache lag), and the
  assertion explicitly enumerates the missing-collection leg — a 200
  here is a zombie read served for a collection that no longer exists
  (typed per the assertion's defect_type_if_violated =
  Type1_IllegalSuccess, stale-read noted for the judge). Error-naming
  on 4xx is NOTE only (R29).
  [chunk_point+get coverage: strategy1 boundary-value + strategy7
  malformed-name x qdrant_behavioral_point_get_001, collection_name
  promise/lifecycle faces (this script; id uint64 closure in
  boundary_point_get_001, id non-UUID forms in boundary_point_get_002,
  id UUID branch in boundary_point_get_003, id hostile chars in
  boundary_point_get_004)]
Oracle: face A -> 404 (200 with any Record = Type1_IllegalSuccess;
  5xx with /healthz alive = Type3_RuntimeFailure; 400/422 = strict
  NOTE); face B -> 404 (400 = validation-order NOTE acceptable; 200 =
  Type1; 5xx = Type3); face C -> 4xx (200 = Type1; 5xx = Type3);
  face D -> 4xx/404 clean, 200 WITH the base point's Record =
  Type1_IllegalSuccess NUL-truncation identifier confusion; face E/F
  -> 4xx/404 clean (5xx = Type3; any 200 = Type1); face G -> 4xx/414
  or 404 clean, 5xx/OOM = Type3; face H control -> 200 with
  result.id == 5, post-delete GET -> 404 (200 = Type1_IllegalSuccess
  zombie read across collection deletion; 5xx = Type3; 400/422 =
  NOTE); transport failures -> /healthz liveness re-check then
  SCRIPT_ERROR (constraint qdrant_behavioral_point_get_001).
Constraint: qdrant_behavioral_point_get_001 (bare id) — "returns 200
  with the Record; 404 when the point or the collection does not exist"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  point+get            -> GET  /collections/{collection_name}/points/{id}
  points+upsert        -> PUT  /collections/{collection_name}/points
  collections+create   -> PUT  /collections/{collection_name}
  collections+delete   -> DELETE /collections/{collection_name}
  healthz              -> GET  /healthz
  (wait is a query parameter on the upsert/delete faces — passed via params=)
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


def judge_never_created(label, s, raw, body, note_400="strict-validation NOTE acceptable"):
    """Faces A/B/C/E/F: a target collection that does not exist -> 404
    promised. 200 = Type1; 5xx (healthz-gated) = Type3; 400/422 = NOTE."""
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
              f"Record id={rid!r} although the collection does not exist "
              f"(assertion leg: 404): {raw[:300]}")
        return False
    if s == 404:
        print(f"{label}: 404 — collection leg of the promise kept")
        return True
    if 400 <= s <= 499:  # incl. 414
        print(f"{label}: {s} ({note_400}; error-naming NOTE only, R29)")
        return True
    print(f"NOTE: {label} returned unexpected status {s}; recorded for the judge: {raw[:200]}")
    return True


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpg5" + tag
    ghost = "bpg5missing" + tag

    # Arrange: data-bearing collection (own data, own cleanup)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4],
                                               "payload": {"n": 1}},
                                              {"id": 5, "vector": [0.2, 0.3, 0.4, 0.5],
                                               "payload": {"n": 5}}]},
                             params={"wait": "true"}, timeout=60)
    if s not in (200, 201):
        print(f"setup upsert failed status={s}: {raw[:300]}")
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # ---- Face A: never-created collection + well-formed id -> 404 ----
        s, body, raw = safe_request("GET", f"/collections/{ghost}/points/1", timeout=30)
        print(f"face A ghost collection + id 1 -> status={s}")
        print(f"raw: {raw[:400]}")
        if not judge_never_created("face A ghost collection", s, raw, body):
            return

        # ---- Face B: never-created collection + garbage id ----
        s, body, raw = safe_request("GET", f"/collections/{ghost}/points/abc", timeout=30)
        print(f"\nface B ghost collection + id 'abc' -> status={s}")
        print(f"raw: {raw[:400]}")
        if not judge_never_created("face B ghost collection + garbage id", s, raw, body,
                                   note_400="id-validation-before-existence ordering"):
            return

        # ---- Face C: EMPTY collection name ----
        s, body, raw = safe_request("GET", f"/collections//points/1", timeout=30)
        print(f"\nface C empty collection name -> status={s}")
        print(f"raw: {raw[:400]}")
        if not judge_never_created("face C empty collection name", s, raw, body,
                                   note_400="route-not-matched rejection"):
            return

        # ---- Face D: NUL-truncation aliasing against the LIVE base collection ----
        s, body, raw = safe_request("GET", f"/collections/{coll}%00suffix/points/1", timeout=30)
        print(f"\nface D NUL-truncation name '{coll}%00suffix' + id 1 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            if not transport_dead("face D"):
                return
        elif 500 <= s <= 599:
            hs, _, _ = safe_request("GET", "/healthz", timeout=10)
            if hs == 200:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — face D: 5xx {s} with service alive")
                return
            print("VERDICT: SCRIPT_ERROR — face D 5xx and healthz down")
            return
        elif 200 <= s <= 299:
            rid = record_id_of(body)
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — face D: request "
                  f"naming collection '{coll}%00suffix' (a DIFFERENT name) was "
                  f"served point Record id={rid!r} — the server truncated the "
                  f"decoded name at NUL and aliased it to the base collection "
                  f"{coll} (identifier confusion): {raw[:300]}")
            return
        else:
            print(f"face D: {s} clean (no NUL-truncation aliasing)")

        # ---- Faces E/F/G: hostile collection names (never created) ----
        for label, name in (
            ("face E lone-surrogate name", "%ED%A0%80" + tag),
            ("face F traversal name", "..%2F..%2F" + tag),
            ("face G overlong name (8000 chars)", "z" * 8000),
        ):
            s, body, raw = safe_request("GET", f"/collections/{name}/points/1", timeout=30)
            shown = name if len(name) <= 60 else f"<{len(name)} chars>"
            print(f"\n{label} name={shown} -> status={s}")
            print(f"raw: {raw[:400]}")
            if not judge_never_created(label, s, raw, body,
                                       note_400="clean hostile-name rejection"):
                return

        # ---- Face H: lifecycle mutation (control 200 -> delete -> 404) ----
        s, body, raw = safe_request("GET", f"/collections/{coll}/points/5", timeout=30)
        print(f"\nface H control: live collection point 5 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            if not transport_dead("face H control"):
                return
        elif s == 200 and record_id_of(body) == 5:
            print("face H control OK: 200 with Record result.id == 5")
        else:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — face H control: "
                  f"existing point 5 read returned {s} (id={record_id_of(body)!r}); "
                  f"promise: 200 with Record: {raw[:300]}")
            return
        s, _, raw = safe_request("DELETE", f"/collections/{coll}",
                                 params={"wait": "true"}, timeout=60)
        print(f"face H delete collection -> status={s}")
        print(f"raw: {raw[:300]}")
        if s not in (200, 202):
            print(f"VERDICT: SCRIPT_ERROR — face H delete returned {s} (mutation step failed)")
            return
        s, body, raw = safe_request("GET", f"/collections/{coll}/points/5", timeout=30)
        print(f"face H post-delete GET point 5 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            if not transport_dead("face H post-delete"):
                return
        if 500 <= s <= 599:
            hs, _, _ = safe_request("GET", "/healthz", timeout=10)
            if hs == 200:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — face H: "
                      f"post-delete GET returned {s} with service alive")
            else:
                print("VERDICT: SCRIPT_ERROR — face H 5xx and healthz down")
            return
        if 200 <= s <= 299:
            rid = record_id_of(body)
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — face H: GET on a "
                  f"DELETED collection returned 2xx with Record id={rid!r} "
                  f"(zombie read across collection deletion — stale-read noted "
                  f"for the judge): {raw[:300]}")
            return
        if s == 404:
            print("face H OK: post-delete GET -> 404 (collection leg held after deletion)")
        else:
            print(f"NOTE: face H post-delete GET returned {s}; recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
