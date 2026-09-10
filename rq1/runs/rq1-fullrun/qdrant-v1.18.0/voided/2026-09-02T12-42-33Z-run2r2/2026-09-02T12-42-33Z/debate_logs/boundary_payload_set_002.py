#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_set_002
# strategy: strategy2 type-boundary attack (malformed geo/datetime literals — ingestion + lazy typed-validation)
# endpoint: payload+set
# constraint_ids: qdrant_type_payload_set_001
# source_url: https://qdrant.tech/documentation/manage-data/payload/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde assumed to reject
#            literal-format violations at ingestion; an accepted malformed
#            literal is sub-judged by readback AND by the lazy typed channel:
#            the native filter + the typed payload index)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_type_payload_set_001 — the NEGATIVE
  faces of the literal-syntax promise for geo and datetime. Seven malformed
  literals, each set via payload+set on its own point (wait=true query):
  geo faces — g1 {lon:"4.9", lat:52.37} (string lon, promise says doubles),
  g2 {lon:4.9} (missing lat), g3 {lon:4.9, lat:null} (null lat), g4
  [4.9, 52.37] (array-as-geo); datetime faces — d1 "2026-13-45T99:99:99Z"
  (RFC 3339 shape, calendar-impossible values), d2 "2026-09-02 12:00:00Z"
  (space separator — not RFC 3339), d3 "not-a-datetime" (garbage). Expected:
  4xx rejecting the malformed literal. If a malformed literal is instead
  200-accepted it is sub-judged on two channels and the script then STOPS on
  that face: (a) readback — byte-equal persistence = Type1_IllegalSuccess
  (the literal-format promise is violated at ingestion; judge may weigh the
  payload-is-free-JSON mitigation), any distortion = Type4; (b) lazy
  typed-validation aggravator on the same field — the native geo_radius /
  datetime range filter, then a typed payload index (index+create
  field_schema geo / datetime): 5xx = Type3 (lazy validation crash,
  strictly stronger finding, verdict escalates), silently WRONG match set =
  Type4; a clean 4xx or no-match = lazy validation defensible (recorded as
  NOTE aggravation context under the Type1 verdict). If ALL faces are
  rejected, the geo filtering channel runs once on the well-formed control
  point 8 (channel attributability) and a final sweep confirms every
  payload deep-equals baseline. Error-naming quality on 4xx faces is
  recorded as NOTE only (R29 lesson: Type2 error-naming has NO anchor —
  three NOT precedents).
  [chunk_payload+set coverage: strategy2 type-boundary x
  qdrant_type_payload_set_001, malformed geo/datetime faces (this script;
  positive round-trip in _001, malformed uuid/array faces in _003)]
Oracle: each of the seven malformed-literal set-payload calls returns 4xx
  (clean rejection; unnamed 4xx = NOTE only) and with all seven rejected the
  geo channel control matches exactly [8] and the final readback is
  deep-equal baseline; any 200 is sub-judged then stops the script —
  readback byte-equal persist = Type1_IllegalSuccess (escalated to
  Type3_RuntimeFailure with /healthz re-check if the follow-on native
  filter or typed index create on the same field returns 5xx; to
  Type4_StateLogicViolation if the follow-on filter silently returns a
  wrong match set); distorted readback = Type4; transport failure =
  SCRIPT_ERROR with /healthz re-check (constraint qdrant_type_payload_set_001).
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


def lazy_typed_probe(coll, field, flt, ischema, control_ids, face_label):
    """Lazy typed-validation aggravator on an ACCEPTED malformed literal.
    (1) native filter channel; (2) typed payload index creation.
    Returns None (verdict already printed) — escalates the Type1 finding to
    Type3 (5xx) or Type4 (silently wrong match) when warranted."""
    # (1) native filter channel
    ids, ferr = scroll_ids_by_filter(coll, flt)
    if ids is None:
        fs, fraw = ferr
        if 500 <= fs <= 599:
            hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
            print(f"5xx in lazy filter channel (healthz status={hs}: {hraw[:200]})")
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — accepted malformed "
                  f"literal (face {face_label}) then crashed the native filter "
                  f"channel with {fs}: {str(fraw)[:300]}")
            return
        # clean 4xx in the filter channel = defensible lazy validation (NOTE)
        print(f"NOTE: lazy filter channel on field '{field}' rejected with {fs} "
              f"(defensible lazy validation): {str(fraw)[:200]}")
    else:
        print(f"lazy filter channel on field '{field}' matched ids={ids} "
              f"(well-formed control ids={control_ids})")
        if ids != control_ids and ids:
            # e.g. an impossible-calendar datetime matching a 2026 range, or a
            # string-lon geo matching the radius: silently WRONG interpretation
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — accepted "
                  f"malformed literal (face {face_label}) is silently interpreted "
                  f"by its native filter channel: matched {ids} where the "
                  f"well-formed control matches {control_ids}")
            return
        print("NOTE: no-match or control-consistent result — lazy validation "
              "defensible (recorded as aggravation context, not a second defect)")
    # (2) typed payload index creation on the same field
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
    # base verdict when no escalation fired
    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — malformed literal "
          f"accepted with 200 and persisted byte-equal (promise: "
          f"geo={{lon,lat}} doubles / datetime RFC 3339; judge weighs "
          f"payload-is-free-JSON mitigation)")


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpset2" + tag
    vecs = {1: [0.1, 0.2, 0.3, 0.4], 2: [0.2, 0.3, 0.4, 0.5],
            3: [0.3, 0.4, 0.5, 0.6], 4: [0.4, 0.5, 0.6, 0.7],
            5: [0.5, 0.6, 0.7, 0.8], 6: [0.6, 0.7, 0.8, 0.9],
            7: [0.7, 0.8, 0.9, 1.0], 8: [0.8, 0.9, 1.0, 0.1]}
    baseline = {i: {"n": i} for i in vecs}
    # Seven malformed-literal faces: (label, payload-literal, field, native filter, typed index schema)
    geo_flt = {"must": [{"key": "loc", "geo_radius": {
        "center": {"lon": 4.9, "lat": 52.37}, "radius": 1000.0}}]}
    dt_flt = {"must": [{"key": "ts", "range": {"gte": "2026-01-01T00:00:00Z"}}]}
    faces = [
        ("g1 geo string-lon", {"loc": {"lon": "4.9", "lat": 52.37}}, "loc", geo_flt, "geo"),
        ("g2 geo missing-lat", {"loc": {"lon": 4.9}}, "loc", geo_flt, "geo"),
        ("g3 geo null-lat", {"loc": {"lon": 4.9, "lat": None}}, "loc", geo_flt, "geo"),
        ("g4 array-as-geo", {"loc": [4.9, 52.37]}, "loc", geo_flt, "geo"),
        ("d1 impossible-calendar", {"ts": "2026-13-45T99:99:99Z"}, "ts", dt_flt, "datetime"),
        ("d2 space-separator", {"ts": "2026-09-02 12:00:00Z"}, "ts", dt_flt, "datetime"),
        ("d3 garbage", {"ts": "not-a-datetime"}, "ts", dt_flt, "datetime"),
    ]
    # face point ids 1..7; point 8 carries WELL-FORMED literals as the
    # channel control (the lazy channels must work on a well-formed field
    # value so channel failures on malformed faces are attributable)
    well_formed = {"loc": {"lon": 4.9, "lat": 52.37}, "ts": "2026-09-02T12:00:00Z"}

    # Arrange: data-bearing collection (own data, own cleanup)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    pts = [{"id": i, "vector": vecs[i], "payload": dict(baseline[i])} for i in vecs]
    pts[-1]["payload"] = dict(well_formed)  # point 8 = well-formed control
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
        want0 = dict(baseline)
        want0[8] = dict(well_formed)
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
        print("baseline: 8 payloads visible via scroll")

        any_accepted = False
        for idx, (label, lit, field, flt, ischema) in enumerate(faces, start=1):
            body_json = {"points": [idx], "payload": dict(lit)}
            s, _, raw = safe_request(
                "POST", f"/collections/{coll}/points/payload",
                json=body_json, params={"wait": "true"}, timeout=60)
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
                any_accepted = True
                # sub-judge (a): readback must be byte-equal merged baseline+literal
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
                # sub-judge (b): native filter + typed index on the same field,
                # control = the well-formed point 8 ids for that channel
                control_ids = [8]
                lazy_typed_probe(coll, field, flt, ischema, control_ids, label)
                return
            if s in (400, 422):
                low = raw.lower()
                names = [w for w in ("lon", "lat", "loc", "ts", "datetime", "geo", "payload")
                         if w in low]
                print(f"face {label} cleanly rejected with {s} (mentions: "
                      f"{names or 'no literal/field name'} — NOTE only, R29)")
            else:
                print(f"NOTE: face {label} returned unexpected status {s}; recorded for the judge")

        # all-rejected path: channel control (attributability) + final sweep
        ids, ferr = scroll_ids_by_filter(coll, geo_flt)
        if ids is None:
            fs, fraw = ferr
            if 500 <= fs <= 599:
                hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
                print(f"5xx in geo channel control (healthz status={hs}: {hraw[:200]})")
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — geo_radius "
                      f"channel control returned {fs}: {str(fraw)[:300]}")
                return
            print(f"VERDICT: SCRIPT_ERROR — geo channel control unusable: "
                  f"status={fs} {str(fraw)[:300]}")
            return
        print(f"geo channel control (point 8 well-formed): matched ids={ids}")
        if ids != [8]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — geo_radius "
                  f"channel control returned {ids}, want exactly [8] (channel "
                  f"itself broken — earlier rejections unattributable)")
            return

        pls_f, cerr_f = scroll_payloads(coll)
        if pls_f is None:
            print(f"VERDICT: SCRIPT_ERROR — final readback failure: {str(cerr_f)[:300]}")
            return
        drift = [i for i in want0 if pls_f.get(i) != want0[i]]
        if drift:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — after all "
                  f"faces, payloads drifted from baseline on points {drift}")
            return
        print("final sweep: all payloads deep-equal baseline (all 7 malformed faces rejected)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
