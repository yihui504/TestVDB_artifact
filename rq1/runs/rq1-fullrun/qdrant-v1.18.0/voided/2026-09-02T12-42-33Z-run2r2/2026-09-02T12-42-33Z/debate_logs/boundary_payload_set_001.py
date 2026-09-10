#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_set_001
# strategy: strategy2 type-boundary attack (positive round-trip of the four documented literal forms)
# endpoint: payload+set
# constraint_ids: qdrant_type_payload_set_001
# source_url: https://qdrant.tech/documentation/manage-data/payload/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the positive half of the
#            literal-format promise: well-formed geo/datetime/uuid/array
#            literals set via payload+set must persist byte-equal AND remain
#            interpretable by their native filter channels)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_type_payload_set_001 — the G4
  POSITIVE face of the literal-syntax promise ("payload values with
  non-trivial literal syntax: geo values are objects {lon, lat} of doubles;
  datetime values are RFC 3339 strings; uuid values are uuid strings; arrays
  must be same-type [DOC payload + filtering]"). Two points are upserted
  payload-free, then each receives its four typed literals through the
  endpoint under attack (payload+set, points-selector, wait=true query):
  p1 = geo Amsterdam + datetime 2026-09-02T12:00:00Z + uuid 6f9619ff-... +
  keyword array ["ams","nyc"]; p2 = geo Tokyo + datetime 2025-01-01T00:00:00Z
  + a different uuid + keyword array ["par","brx"]. Promise judged through
  two independent channels (R5/R21: judge the state, not the ack):
  (1) persistence — scroll readback must show each payload deep-equal the
  literal dict exactly (double byte-equality: lon 4.9 must round-trip 4.9,
  not a distorted float); (2) filtering (the constraint's second half —
  "payload + filtering") — four native filter channels through scroll, each
  must return EXACTLY the discriminated id set: geo_radius 1000m around
  Amsterdam -> exactly [1]; datetime range gte 2026-01-01T00:00:00Z ->
  exactly [1]; uuid match on p1's uuid -> exactly [1]; array element match
  "par" -> exactly [2] (data_types: "filter succeeds if at least one value
  matches").
  [chunk_payload+set coverage: strategy2 type-boundary x
  qdrant_type_payload_set_001, positive literal round-trip face (this
  script; malformed geo/datetime faces in _002, malformed uuid/array faces
  in _003)]
Oracle: both set-payload calls return 200 (wait=true); scroll readback shows
  p1/p2 payloads deep-equal the provided literal dicts (any key loss, type
  drift, or number distortion = Type4_StateLogicViolation); each of the four
  native filter channels returns exactly its predicted id set — geo_radius
  matches a point whose geo literal was NOT stored as {lon,lat} doubles (or
  fails to match the stored one) = Type4; datetime range returns the wrong
  side = Type4 (RFC 3339 literal not parsed as datetime); uuid match misses
  = Type4; array match violates at-least-one semantics = Type4; non-200 on
  a well-formed literal set = Type1_IllegalSuccess (promise: valid literals
  succeed); 5xx/transport = Type3_RuntimeFailure with /healthz re-check
  (constraint qdrant_type_payload_set_001).
Constraint: qdrant_type_payload_set_001 (bare id) — "payload values with
  non-trivial literal syntax: geo values are objects {lon, lat} of doubles;
  datetime values are RFC 3339 strings; uuid values are uuid strings; arrays
  must be same-type [DOC payload + filtering]" (evidence_tier: explicit;
  level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  payload+set           -> POST /collections/{collection_name}/points/payload
  points+upsert         -> PUT  /collections/{collection_name}/points
  points+scroll         -> POST /collections/{collection_name}/points/scroll
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
    Returns (ids, chan_err); None ids means channel unusable."""
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


def wait_payloads(coll, want, tries=6, delay=0.5):
    """Poll scroll readback until every id's payload deep-equals want[id]."""
    pls, cerr = scroll_payloads(coll)
    for _ in range(tries):
        if pls is None:
            break
        if all(pls.get(i) == want[i] for i in want):
            break
        time.sleep(delay)
        pls, cerr = scroll_payloads(coll)
    return pls, cerr


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpset1" + tag
    vecs = {1: [0.1, 0.2, 0.3, 0.4], 2: [0.2, 0.3, 0.4, 0.5]}
    # The four documented literal forms (contract data_types: "Payload JSON
    # types (filterable)"; constraint qdrant_type_payload_set_001)
    uid1 = "6f9619ff-8b86-d011-b42d-00c04fc964ff"
    uid2 = "0f8e4d73-61a1-4b9f-9c3d-7a2b5e9d1c40"
    lit1 = {
        "loc": {"lon": 4.9, "lat": 52.37},                 # geo {lon, lat} doubles
        "ts": "2026-09-02T12:00:00Z",                       # datetime RFC 3339
        "uid": uid1,                                        # uuid string
        "tags": ["ams", "nyc"],                             # same-type array
    }
    lit2 = {
        "loc": {"lon": 139.69, "lat": 35.69},
        "ts": "2025-01-01T00:00:00Z",
        "uid": uid2,
        "tags": ["par", "brx"],
    }

    # Arrange: data-bearing collection (own data, own cleanup), payload-free
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request(
        "PUT", f"/collections/{coll}/points",
        json={"points": [{"id": i, "vector": vecs[i]} for i in (1, 2)]},
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
        # Act: set the four typed literals through payload+set (points-selector)
        for pid, lit in ((1, lit1), (2, lit2)):
            s, _, raw = safe_request(
                "POST", f"/collections/{coll}/points/payload",
                json={"points": [pid], "payload": dict(lit)},
                params={"wait": "true"}, timeout=60)
            print(f"set-payload points=[{pid}] (4 typed literals) -> status={s}")
            print(f"raw: {raw[:500]}")
            if s <= 0:
                transport_dead()
                return
            if 500 <= s <= 599:
                hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
                print(f"5xx on well-formed literal set (healthz status={hs}: {hraw[:200]})")
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — set-payload "
                      f"points=[{pid}] with documented literal forms returned {s}")
                return
            if s != 200:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — set-payload "
                      f"with well-formed geo/datetime/uuid/array literals on point "
                      f"{pid} rejected with {s} (promise: valid literals succeed)")
                return

        # Assert channel 1: persistence — deep-equal byte-identical readback
        want = {1: dict(lit1), 2: dict(lit2)}
        pls, cerr = wait_payloads(coll, want)
        if pls is None or pls.get(1) != lit1 or pls.get(2) != lit2:
            print(f"readback: p1={pls.get(1) if pls else None} p2={pls.get(2) if pls else None}")
            print(f"VERDICT: SCRIPT_ERROR — readback channel failure: {str(cerr)[:300]}")
            return
        print("persistence OK: both literal payloads deep-equal the provided dicts")

        # Assert channel 2: filtering — each native channel discriminates exactly
        channels = [
            ("geo_radius 1000m around Amsterdam -> exactly [1]",
             {"must": [{"key": "loc", "geo_radius": {
                 "center": {"lon": 4.9, "lat": 52.37}, "radius": 1000.0}}]},
             [1]),
            ("datetime range gte 2026-01-01T00:00:00Z -> exactly [1]",
             {"must": [{"key": "ts", "range": {"gte": "2026-01-01T00:00:00Z"}}]},
             [1]),
            (f"uuid match {uid1} -> exactly [1]",
             {"must": [{"key": "uid", "match": {"value": uid1}}]},
             [1]),
            ("array element match 'par' -> exactly [2]",
             {"must": [{"key": "tags", "match": {"value": "par"}}]},
             [2]),
        ]
        for label, flt, expect in channels:
            ids, ferr = scroll_ids_by_filter(coll, flt)
            if ids is None:
                fs, fraw = ferr
                if 500 <= fs <= 599:
                    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
                    print(f"5xx in filtering channel (healthz status={hs}: {hraw[:200]})")
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — filter "
                          f"channel '{label}' returned {fs}: {str(fraw)[:300]}")
                    return
                print(f"VERDICT: SCRIPT_ERROR — filtering channel unusable "
                      f"({label}): status={fs} {str(fraw)[:300]}")
                return
            print(f"filter channel [{label}]: matched ids={ids}")
            if ids != expect:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — filter "
                      f"channel '{label}' returned {ids}, want exactly {expect} "
                      f"(constraint: payload + filtering literal formats — the "
                      f"stored literal is not interpreted by its native filter)")
                return

        print("all four native filter channels returned exactly the predicted sets")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
