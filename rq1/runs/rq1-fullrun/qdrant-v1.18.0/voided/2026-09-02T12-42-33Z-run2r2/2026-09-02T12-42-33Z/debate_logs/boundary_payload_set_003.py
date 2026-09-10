#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_set_003
# strategy: strategy2 type-boundary attack (malformed uuid + array literals — ingestion + lazy typed-validation)
# endpoint: payload+set
# constraint_ids: qdrant_type_payload_set_001
# source_url: https://qdrant.tech/documentation/manage-data/payload/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde assumed to reject
#            non-uuid uuid values and mixed-type arrays at ingestion; an
#            accepted malformed literal is sub-judged by readback AND by the
#            lazy typed channel: the match filter + the typed payload index)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_type_payload_set_001 — the NEGATIVE
  faces of the literal-syntax promise for uuid and arrays. Six faces, each
  set via payload+set on its own point (wait=true query): uuid faces —
  u1 uid="not-a-uuid" (string but not uuid syntax; promise: uuid values are
  uuid strings), u2 uid=42 (integer); array faces — a1 tags=[1,"ams"]
  (mixed-type array; promise: arrays must be same-type), a2 tags=[[1,2],[3]]
  (nested arrays — arrays of scalar same-type values are the documented
  form), a3 tags=[null] (null element), a4 tags=[] (empty array — R28
  posture face: trivially same-type degenerate, never a defect on status
  alone). Expected for u1/u2/a1/a2/a3: 4xx rejecting the malformed literal;
  a 200-accepted face is sub-judged then STOPS the script: readback
  byte-equal persist = Type1_IllegalSuccess (literal-format promise
  violated at ingestion; judge may weigh payload-is-free-JSON mitigation),
  distortion = Type4; lazy typed-validation aggravator on the same field —
  a uuid match filter (u1), keyword/uuid typed payload index build
  (index+create): 5xx = Type3 (stronger finding, verdict escalates),
  silently wrong match set = Type4, clean 4xx / no-match = defensible lazy
  validation (NOTE context under the Type1 verdict). The a4 empty-array
  posture face accepts either 4xx or 200-with-byte-equal-persist (both
  recorded as NOTE per the R28 no-empty-array-rejection-norm lesson); only
  5xx or readback distortion is a defect there. Error-naming quality on 4xx
  faces is NOTE only (R29 lesson: Type2 error-naming has NO anchor).
  [chunk_payload+set coverage: strategy2 type-boundary x
  qdrant_type_payload_set_001, malformed uuid/array + empty-array posture
  faces (this script; positive round-trip in _001, malformed geo/datetime
  faces in _002)]
Oracle: faces u1/u2/a1/a2/a3 each return 4xx (clean rejection; unnamed 4xx =
  NOTE only) and with all five rejected the uuid channel control matches
  exactly [7] and the final readback is deep-equal baseline; any 200 on
  u1/u2/a1/a2/a3 stops the script — byte-equal persist = Type1_IllegalSuccess
  (escalated to Type3_RuntimeFailure with /healthz re-check if the follow-on
  match filter or typed index build on the same field returns 5xx, or
  Type4_StateLogicViolation on a silently wrong match set); distorted
  readback = Type4; face a4 returns either 4xx or 200 with tags=[] persisted
  byte-equal (both NOTE) — only 5xx or distortion on a4 is a defect;
  transport failure = SCRIPT_ERROR with /healthz re-check (constraint
  qdrant_type_payload_set_001).
Constraint: qdrant_type_payload_set_001 (bare id) — "payload values with
  non-trivial literal syntax: geo values are objects {lon, lat} of doubles;
  datetime values are RFC 3339 strings; uuid values are uuid strings; arrays
  must be same-type [DOC payload + filtering]" (evidence_tier: explicit;
  level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  payload+set           -> POST /collections/{collection_name}/points/payload
  points+upsert         -> PUT  /collections/{collection_name}/points
  points+scroll         -> POST /collections/{collection_name}/points/scroll
  index+create          -> PUT  /collections/{collection_name}/index
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
  healthz               -> GET  /healthz
  (wait is a query parameter on the point-mutation faces — passed via params=)
"""

import json
import os
import sys
import time
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
    params= forwards query parameters exactly (wait/timeout live in the query
    string on qdrant point-mutation faces).
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


def transport_dead():
    """Liveness re-check on the lightweight healthz face (transport branch)."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    print(f"transport failure (healthz status={hs}: {str(hraw)[:200]})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return


def scroll_payloads(coll):
    """id -> payload dict from points+scroll (with_payload).
    Returns (payloads, chan_err); None payloads means channel unusable."""
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points/scroll",
        json={"limit": 100, "with_payload": True}, timeout=30)
    if s != 200 or not isinstance(body, dict):
        return None, (s, raw)
    res = body.get("result")
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        return None, (s, raw)
    return {p.get("id"): p.get("payload") for p in pts if isinstance(p, dict)}, (s, raw)


def scroll_ids_by_filter(coll, flt):
    """Sorted id list of points matching flt via scroll (filtering channel).
    Returns (ids, chan_err); None ids means channel unusable (chan_err carries status)."""
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points/scroll",
        json={"limit": 100, "with_payload": False, "filter": flt}, timeout=30)
    if s != 200 or not isinstance(body, dict):
        return None, (s, raw)
    res = body.get("result")
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        return None, (s, raw)
    return sorted(p.get("id") for p in pts if isinstance(p, dict)), (s, raw)


def lazy_typed_probe(coll, field, match_flt, ischema, control_ids, face_label, promise_txt):
    """Lazy typed-validation aggravator on an ACCEPTED malformed literal:
    (1) optional native match-filter channel; (2) typed payload index build.
    Prints the final verdict (escalating to Type3/Type4 when warranted)."""
    if match_flt is not None:
        ids, ferr = scroll_ids_by_filter(coll, match_flt)
        if ids is None:
            fs, fraw = ferr
            if 500 <= fs <= 599:
                hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
                print(f"5xx in lazy match channel (healthz status={hs}: {hraw[:200]})")
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — accepted malformed "
                      f"literal (face {face_label}) then crashed the match filter "
                      f"channel with {fs}: {str(fraw)[:300]}")
                return
            print(f"NOTE: lazy match channel on field '{field}' rejected with {fs} "
                  f"(defensible lazy validation): {str(fraw)[:200]}")
        else:
            print(f"lazy match channel on field '{field}' matched ids={ids} "
                  f"(well-formed control ids={control_ids})")
            if ids != control_ids and ids:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — accepted "
                      f"malformed literal (face {face_label}) is silently interpreted "
                      f"by the match channel: matched {ids} where the well-formed "
                      f"control matches {control_ids}")
                return
            print("NOTE: no-match or control-consistent result — lazy validation "
                  "defensible (recorded as aggravation context)")
    s, _, raw = safe_request(
        "PUT", f"/collections/{coll}/index",
        json={"field_name": field, "field_schema": {"type": ischema}},
        params={"wait": "true"}, timeout=60)
    print(f"typed index create ({field}: {ischema}) -> status={s}: {raw[:300]}")
    if 500 <= s <= 599:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
        print(f"5xx in typed index build (healthz status={hs}: {hraw[:200]})")
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — accepted malformed "
              f"literal (face {face_label}) then crashed the typed {ischema} "
              f"index build with {s}")
        return
    if s in (400, 422):
        print(f"NOTE: typed {ischema} index build rejected with {s} (defensible "
              f"lazy validation): {raw[:200]}")
    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — malformed literal "
          f"accepted with 200 and persisted byte-equal (promise: {promise_txt}; "
          f"judge weighs payload-is-free-JSON mitigation)")


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpset3" + tag
    vecs = {1: [0.1, 0.2, 0.3, 0.4], 2: [0.2, 0.3, 0.4, 0.5],
            3: [0.3, 0.4, 0.5, 0.6], 4: [0.4, 0.5, 0.6, 0.7],
            5: [0.5, 0.6, 0.7, 0.8], 6: [0.6, 0.7, 0.8, 0.9],
            7: [0.7, 0.8, 0.9, 1.0]}
    baseline = {i: {"n": i} for i in vecs}
    control_uid = "6f9619ff-8b86-d011-b42d-00c04fc964ff"
    # Hard faces: (label, literal, field, match filter, typed index schema, promise txt)
    faces = [
        ("u1 non-uuid string", {"uid": "not-a-uuid"}, "uid",
         {"must": [{"key": "uid", "match": {"value": "not-a-uuid"}}]}, "uuid",
         "uuid values are uuid strings"),
        ("u2 integer-as-uuid", {"uid": 42}, "uid", None, "uuid",
         "uuid values are uuid strings"),
        ("a1 mixed-type array", {"tags": [1, "ams"]}, "tags",
         {"must": [{"key": "tags", "match": {"value": "ams"}}]}, "keyword",
         "arrays must be same-type"),
        ("a2 nested-array", {"tags": [[1, 2], [3]]}, "tags", None, "keyword",
         "arrays of scalar same-type values"),
        ("a3 null-element array", {"tags": [None]}, "tags", None, "keyword",
         "arrays of scalar same-type values"),
    ]
    # Posture face (R28): empty array — either status family is acceptable
    posture_face = ("a4 empty array", {"tags": []})

    # Arrange: data-bearing collection (own data, own cleanup); point 7 =
    # well-formed control (uuid + keyword array)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    pts = [{"id": i, "vector": vecs[i], "payload": dict(baseline[i])} for i in vecs]
    pts[-1]["payload"] = {"n": 7, "uid": control_uid, "tags": ["ams", "nyc"]}
    s, _, raw = safe_request(
        "PUT", f"/collections/{coll}/points", json={"points": pts},
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
        want0 = {i: dict(baseline[i]) for i in vecs}
        want0[7] = {"n": 7, "uid": control_uid, "tags": ["ams", "nyc"]}
        pls, cerr = scroll_payloads(coll)
        for _ in range(6):
            if pls is not None and all(pls.get(i) == want0[i] for i in want0):
                break
            time.sleep(0.5)
            pls, cerr = scroll_payloads(coll)
        if pls is None or any(pls.get(i) != want0[i] for i in want0):
            print(f"baseline readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        print("baseline: 7 payloads visible via scroll")

        for idx, (label, lit, field, mflt, ischema, promise_txt) in enumerate(faces, start=1):
            s, _, raw = safe_request(
                "POST", f"/collections/{coll}/points/payload",
                json={"points": [idx], "payload": dict(lit)},
                params={"wait": "true"}, timeout=60)
            print(f"\nface {label} (point {idx}) -> status={s}")
            print(f"raw: {raw[:400]}")
            if s <= 0:
                transport_dead()
                return
            if 500 <= s <= 599:
                hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
                print(f"5xx on malformed literal (healthz status={hs}: {hraw[:200]})")
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — face {label} "
                      f"triggered server error {s}")
                return
            if 200 <= s <= 299:
                merged = dict(baseline[idx])
                merged.update(lit)
                pls_a, _ = scroll_payloads(coll)
                for _ in range(4):
                    if pls_a is not None and pls_a.get(idx) == merged:
                        break
                    time.sleep(0.5)
                    pls_a, _ = scroll_payloads(coll)
                if pls_a is None:
                    print(f"VERDICT: SCRIPT_ERROR — readback channel failure on face {label}")
                    return
                got = pls_a.get(idx)
                if got != merged:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — face "
                          f"{label} was 200-accepted but readback distorted the "
                          f"literal: {got}, want {merged}")
                    return
                print(f"face {label} 200-accepted, persisted byte-equal — running "
                      f"lazy typed-validation aggravators")
                lazy_typed_probe(coll, field, mflt, ischema, [7], label, promise_txt)
                return
            if s in (400, 422):
                low = raw.lower()
                names = [w for w in ("uid", "uuid", "tags", "array", "payload", "type")
                         if w in low]
                print(f"face {label} cleanly rejected with {s} (mentions: "
                      f"{names or 'no field/type name'} — NOTE only, R29)")
            else:
                print(f"NOTE: face {label} returned unexpected status {s}; recorded for the judge")

        # ---- posture face a4: empty array (R28 — never a defect on status) ----
        label, lit = posture_face
        s, _, raw = safe_request(
            "POST", f"/collections/{coll}/points/payload",
            json={"points": [6], "payload": dict(lit)},
            params={"wait": "true"}, timeout=60)
        print(f"\nposture face {label} (point 6) -> status={s}")
        print(f"raw: {raw[:400]}")
        if s <= 0:
            transport_dead()
            return
        if 500 <= s <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx on empty-array posture face (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — face {label} "
                  f"triggered server error {s}")
            return
        if 200 <= s <= 299:
            merged = dict(baseline[6])
            merged.update(lit)
            pls_b, _ = scroll_payloads(coll)
            for _ in range(4):
                if pls_b is not None and pls_b.get(6) == merged:
                    break
                time.sleep(0.5)
                pls_b, _ = scroll_payloads(coll)
            if pls_b is None:
                print("VERDICT: SCRIPT_ERROR — readback channel failure on posture face")
                return
            if pls_b.get(6) != merged:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — empty "
                      f"array 200-accepted but readback distorted it: "
                      f"{pls_b.get(6)}, want {merged}")
                return
            print(f"NOTE: {label} 200-accepted with tags=[] persisted byte-equal "
                  f"(trivially same-type degenerate — R28 family posture)")
        else:
            print(f"NOTE: {label} rejected with {s} (R28 no-empty-array-rejection "
                  f"norm divergence); recorded for the judge")

        # channel control (attributability of the uuid match channel)
        ids, ferr = scroll_ids_by_filter(
            coll, {"must": [{"key": "uid", "match": {"value": control_uid}}]})
        if ids is None:
            fs, fraw = ferr
            if 500 <= fs <= 599:
                hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
                print(f"5xx in uuid channel control (healthz status={hs}: {hraw[:200]})")
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — uuid match "
                      f"channel control returned {fs}: {str(fraw)[:300]}")
                return
            print(f"VERDICT: SCRIPT_ERROR — uuid channel control unusable: "
                  f"status={fs} {str(fraw)[:300]}")
            return
        print(f"uuid channel control (point 7 well-formed): matched ids={ids}")
        if ids != [7]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — uuid match "
                  f"channel control returned {ids}, want exactly [7]")
            return

        print("all hard faces rejected; posture face recorded; channels attributable")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
