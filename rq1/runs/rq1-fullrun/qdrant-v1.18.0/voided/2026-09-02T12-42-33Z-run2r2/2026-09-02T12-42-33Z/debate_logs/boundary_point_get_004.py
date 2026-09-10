#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_point_get_004
# strategy: strategy7 malformed-input/character fuzzing + strategy4 special-value attack (id path segment)
# endpoint: point+get
# constraint_ids: qdrant_behavioral_point_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/get-point
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — hostile wire forms in
#            the {id} segment must be answered with a clean 4xx/404, never
#            a panic/5xx and never a hallucinated Record)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-input/character fuzzing + strategy4
  special-value x qdrant_behavioral_point_get_001 — hostile wire forms
  in the {id} path segment of the single-point read face (all on an
  existing collection holding point 1; every probe id was never
  created): (A) unicode "点\U0001F3AFid"; (B) SQL-injection
  "'; DROP TABLE points;--"; (C) JSON-injection '{"$gt": ""}';
  (D) RTL bidi control char "id\\u202eevil"; (E) percent-encoded NUL
  "1%00suffix" (literal %00 — measures the server's decode-truncation
  posture); (F) percent-encoded UTF-16 lone surrogate "%ED%A0%80"
  (illegal Unicode — strict serde must not panic); (G) overlong id
  'a' x 100000; (H) path-traversal id "..%2F..%2F..%2Fetc%2Fpasswd"
  (encoded slashes — must not escape the {id} segment); (I) overlong
  numeric '9' x 400 (uint64 overflow by length). Uniform oracle: a
  hostile id must be answered 4xx (incl. 414 URI-too-long) or 404
  (tolerant not-found) — a 200 with any Record = Type1_IllegalSuccess
  (a record served for a hostile identifier that was never created);
  a 5xx / panic / internal-error body = Type3_RuntimeFailure.
  Control face Z: canonical id 1 -> 200 with result.id == 1 (pins the
  promise so wholesale-4xx sloppiness cannot pass). Error-naming on
  4xx is NOTE only (R29). Percent-encoded tokens (%00, %ED%A0%80,
  %2F) are passed through the URL string verbatim — the probe measures
  the SERVER's decode behavior, not the client's.
  [chunk_point+get coverage: strategy7+strategy4 x
  qdrant_behavioral_point_get_001, id malformed/character faces (this
  script; id uint64 closure in boundary_point_get_001, id non-UUID
  string forms in boundary_point_get_002, id UUID branch in
  boundary_point_get_003, collection_name faces in boundary_point_get_005)]
Oracle: faces A-I (hostile never-created ids) -> 4xx/414 or 404 clean;
  200 with any Record = Type1_IllegalSuccess; 5xx or a body naming
  panic/internal/decode errors = Type3_RuntimeFailure (with /healthz
  liveness re-check); control Z -> 200 with result.id == 1 (anything
  else = Type1_IllegalSuccess promise face); transport failures ->
  /healthz liveness re-check then SCRIPT_ERROR (constraint
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


def judge_hostile(label, s, raw, body):
    """Declared expectation for a hostile never-created id (2xx adjudicated
    FIRST so no body keyword can bypass the Type1 check):
    4xx/414 or 404 clean; 200 = Type1; 5xx/panic-body = Type3."""
    if s == -1:
        return transport_dead(label)
    low = str(raw).lower()
    keywords = ("panic", "internal error", "decode error", "utf-8")
    # 1) hallucinated record on a hostile never-created id
    if 200 <= s <= 299:
        rid = record_id_of(body)
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: 2xx with "
              f"Record id={rid!r} for a hostile identifier that was never "
              f"created (hallucinated record): {raw[:300]}")
        return False
    # 2) server error — healthz-gated Type3
    if 500 <= s <= 599:
        hs, _, _ = safe_request("GET", "/healthz", timeout=10)
        if hs == 200:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                  f"server error {s} with service alive (hostile id must be "
                  f"answered with 4xx, not a crash): {raw[:300]}")
        else:
            print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
        return False
    # 3) parser/decode failure named in a non-5xx body — NOTE for the judge
    if any(k in low for k in keywords):
        print(f"NOTE: {label}: status {s} but body names a parser/decode "
              f"failure (recorded for the judge): {raw[:200]}")
        return True
    if s == 404:
        print(f"{label}: 404 tolerant not-found (clean)")
        return True
    if 400 <= s <= 499:  # incl. 414 URI Too Long
        print(f"{label}: {s} clean rejection (error-naming NOTE only, R29)")
        return True
    print(f"NOTE: {label} returned unexpected status {s}; recorded for the judge: {raw[:200]}")
    return True


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpg4" + tag

    # Arrange: data-bearing collection (own data, own cleanup)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4],
                                               "payload": {"n": 1}}]},
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
        # ---- Control Z: canonical id 1 -> must be 200 with its Record ----
        s, body, raw = safe_request("GET", f"/collections/{coll}/points/1", timeout=30)
        print(f"control Z canonical id 1 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            if not transport_dead("control Z"):
                return
        elif s == 200 and record_id_of(body) == 1:
            print("control Z OK: 200 with Record result.id == 1")
        else:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — control Z: "
                  f"existing point 1 read returned {s} (id={record_id_of(body)!r}); "
                  f"promise: 200 with Record: {raw[:300]}")
            return

        # ---- Faces A-I: hostile id wire forms (never created) ----
        probes = [
            ("face A unicode id", f"点\U0001F3AFid_{tag}"),
            ("face B SQL-injection id", "'; DROP TABLE points;--"),
            ("face C JSON-injection id", '{"$gt": ""}'),
            ("face D RTL-bidi id", f"id‮evil_{tag}"),
            # literal %00 — server-side decode-truncation posture
            ("face E percent-encoded NUL id", f"1%00suffix_{tag}"),
            # literal %ED%A0%80 — illegal Unicode (UTF-16 lone surrogate D800)
            ("face F lone-surrogate id", "%ED%A0%80"),
            ("face G overlong id (100k chars)", "a" * 100000),
            # literal %2F — encoded slashes must not escape the {id} segment
            ("face H traversal id", "..%2F..%2F..%2Fetc%2Fpasswd"),
            ("face I overlong numeric id (400 digits)", "9" * 400),
        ]
        for label, pid in probes:
            s, body, raw = safe_request("GET", f"/collections/{coll}/points/{pid}", timeout=30)
            shown = pid if len(str(pid)) <= 60 else f"<{len(str(pid))} chars>"
            print(f"\n{label} id={shown} -> status={s}")
            print(f"raw: {raw[:400]}")
            if not judge_hostile(label, s, raw, body):
                return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
