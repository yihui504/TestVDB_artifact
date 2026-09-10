#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_delete_invisibility_006
# strategy: state-consistency attack enacting the behavioral contract's own
#           scenario verbatim (upsert -> delete by ids AND by filter with
#           wait=true -> five read faces), zombie-hunt across faces
# endpoint: points+delete
# constraint_ids: qdrant_bc_delete_points_invisibility_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-03 (Concurrency State Blindness — wait=true deletes are
#            promised durable/invisible everywhere; a zombie point surviving
#            on ANY read face after a 200 delete is the state-consistency
#            failure this contract forbids)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state-consistency x qdrant_bc_delete_points_invisibility_001 — the
  contract's scenario is enacted verbatim: "upsert points -> delete by ids
  and by filter (wait=true) -> batch-get / single get / scroll / query".
  Seed 8 points (ids 1..4 tag=alpha, ids 5..8 tag=beta), then:
    D1 delete by IDS [1,2] (wait=true) -> 200; every read face must agree:
       count == 6 (arithmetic: 8-2); batch-get [1,2,3] -> result ids ==
       {3} exactly (1,2 zombies forbidden); single GET deleted id 1 -> 404
       while live id 3 -> 200 (pins the 404 to the delete); scroll
       tag=alpha -> EXACTLY {3,4}; search tag=alpha -> no deleted id and
       all returned ids within {3,4}; query tag=alpha -> same (search/query
       carry only absence + membership assertions — HNSW approximation
       non-determinism is by-design per threat model, and no score oracle
       is used per R27)
    D2 delete by FILTER must[tag=beta] (wait=true) -> 200; faces: count == 2
       (8-2-4); batch-get [5,6] -> result []; single GET id 5 -> 404;
       scroll tag=beta -> result.points == []; search tag=beta -> result
       ids == [] (filter scope has 0 live candidates); query tag=beta ->
       result.points == []
  Persistence judged via count+scroll cross-face plus the id-scoped faces
  (R34 lessons; R33 arithmetic: fresh uuid-tagged collection, prefix-unique
  ids 1..8, no pre-existing collision).
  [chunk_points+delete coverage: state-consistency cross-face invisibility x
  qdrant_bc_delete_points_invisibility_001 (this script; idempotence faces
  in boundary_points_delete_idempotent_001, filter-wipe faces in
  boundary_points_delete_filter_wipe_002, 404 leg in
  boundary_points_delete_404_003, invalid-filter 400 leg in
  boundary_points_delete_invalid_filter_004, selector-boundary faces in
  boundary_points_delete_selector_005)]
Oracle: D1/D2 delete -> 200 (non-200 = Type1_IllegalSuccess: promised delete
  rejected); after D1: count == 6, batch-get ids == {3}, single GET id1 404
  AND id3 200, scroll == {3,4}, search/query return no id from {1,2} and no
  id outside {3,4}; after D2: count == 2, batch-get == [], GET id5 404,
  scroll == [], search ids == [], query == []; ANY zombie (deleted id
  present on any face) or wrong count = Type4_StateLogicViolation; 5xx with
  /healthz alive = Type3_RuntimeFailure; transport failure -> /healthz
  liveness re-check then SCRIPT_ERROR
  (constraint qdrant_bc_delete_points_invisibility_001).
Constraint: qdrant_bc_delete_points_invisibility_001 (bare id) — "points
  deleted by id or filter (wait=true) are no longer returned by reads ...
  after a 200 delete the deleted ids are absent from batch-get results,
  single get of a deleted id returns 404, and filtered scroll/search no
  longer return the deleted points"

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+delete         -> POST /collections/{collection_name}/points/delete
  points+get (batch)    -> POST /collections/{collection_name}/points
  point+get (single)    -> GET  /collections/{collection_name}/points/{id}
  points+scroll         -> POST /collections/{collection_name}/points/scroll
  points+search         -> POST /collections/{collection_name}/points/search
  points+query          -> POST /collections/{collection_name}/points/query
  points+count          -> POST /collections/{collection_name}/points/count
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
  points+upsert         -> PUT  /collections/{collection_name}/points
  healthz               -> GET  /healthz
  (wait is a query parameter on the delete/upsert faces — passed via params=)
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

DIM = 4
V = [0.1, 0.2, 0.3, 0.4]
ALPHA_IDS = [1, 2, 3, 4]
BETA_IDS = [5, 6, 7, 8]
N_SEED = len(ALPHA_IDS) + len(BETA_IDS)  # 8


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/ordering/timeout) via params= — never stuffed into the body.
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


def healthz_alive():
    """Inline liveness probe on the lightweight healthz face."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def transport_dead(where):
    """Transport-branch liveness re-check (lightweight healthz face only)."""
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return False


def fail_5xx(where, status, raw):
    """5xx branch with healthz liveness re-check (G8)."""
    alive, _, _ = healthz_alive()
    if alive:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {where}: read/write "
              f"face returned {status}: {raw[:300]}")
    else:
        print(f"VERDICT: SCRIPT_ERROR — {where} 5xx and healthz down")
    return True


def tag_cond(tag):
    """FieldCondition from the contract Condition type: {key, match:{value}}."""
    return {"key": "tag", "match": {"value": tag}}


def exact_count(coll):
    """Exact count via the points+count face (result.count integer per shape)."""
    s, body, raw = safe_request("POST", f"/collections/{coll}/points/count",
                                json={"exact": True}, timeout=60)
    if s == -1 or not (200 <= s <= 299):
        return None, s, raw
    result = body.get("result") if isinstance(body, dict) else None
    got = result.get("count") if isinstance(result, dict) else None
    return got, s, raw


def batch_get_ids(coll, ids):
    """points+get face: result array of points; returns set of returned ids."""
    s, body, raw = safe_request("POST", f"/collections/{coll}/points",
                                json={"ids": ids, "with_payload": False,
                                      "with_vector": False}, timeout=60)
    if s == -1 or not (200 <= s <= 299):
        return None, s, raw
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, list):
        return None, s, raw
    return {p.get("id") for p in result if isinstance(p, dict)}, s, raw


def single_get(coll, pid):
    """point+get face: status only (200 live / 404 deleted)."""
    s, _, raw = safe_request("GET", f"/collections/{coll}/points/{pid}", timeout=60)
    return s, raw


def scroll_ids(coll, filt):
    """points+scroll face: result.points[].id set."""
    s, body, raw = safe_request("POST", f"/collections/{coll}/points/scroll",
                                json={"filter": filt, "limit": 20,
                                      "with_payload": False,
                                      "with_vector": False}, timeout=60)
    if s == -1 or not (200 <= s <= 299):
        return None, s, raw
    result = body.get("result") if isinstance(body, dict) else None
    pts = result.get("points") if isinstance(result, dict) else None
    if not isinstance(pts, list):
        return None, s, raw
    return {p.get("id") for p in pts if isinstance(p, dict)}, s, raw


def search_ids(coll, filt):
    """points+search face: result[].id set (absence/membership oracle only)."""
    s, body, raw = safe_request("POST", f"/collections/{coll}/points/search",
                                json={"vector": V, "filter": filt, "limit": 8},
                                timeout=60)
    if s == -1 or not (200 <= s <= 299):
        return None, s, raw
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, list):
        return None, s, raw
    return {p.get("id") for p in result if isinstance(p, dict)}, s, raw


def query_ids(coll, filt):
    """points+query face: result.points[].id set (absence/membership oracle only)."""
    s, body, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                json={"query": {"nearest": V}, "filter": filt,
                                      "limit": 8, "with_payload": False,
                                      "with_vector": False}, timeout=60)
    if s == -1 or not (200 <= s <= 299):
        return None, s, raw
    result = body.get("result") if isinstance(body, dict) else None
    pts = result.get("points") if isinstance(result, dict) else None
    if not isinstance(pts, list):
        return None, s, raw
    return {p.get("id") for p in pts if isinstance(p, dict)}, s, raw


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpd6i" + tag

    # Arrange: own collection + seed 8 (alpha 1..4, beta 5..8)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        points = []
        for i in ALPHA_IDS:
            points.append({"id": i, "vector": V, "payload": {"tag": "alpha"}})
        for i in BETA_IDS:
            points.append({"id": i, "vector": V, "payload": {"tag": "beta"}})
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": points}, params={"wait": "true"}, timeout=120)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        cnt, cs, craw = exact_count(coll)
        if cnt != N_SEED:
            print(f"seed count = {cnt} (status={cs}), expected {N_SEED}: {str(craw)[:200]}")
            print("VERDICT: SCRIPT_ERROR — setup baseline mismatch")
            return
        print(f"seed baseline: exact count == {N_SEED} (4 alpha + 4 beta)")

        # ================= D1: delete by ids [1,2], wait=true =================
        s1, _, raw1 = safe_request("POST", f"/collections/{coll}/points/delete",
                                   json={"points": [1, 2]}, timeout=60,
                                   params={"wait": "true"})
        print(f"\nD1 delete by ids [1,2] wait=true -> status={s1}")
        print(f"raw: {raw1[:400]}")
        if s1 == -1:
            transport_dead("D1 delete")
            return
        if 500 <= s1 <= 599:
            if fail_5xx("D1 delete", s1, raw1):
                return
        if not (200 <= s1 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — D1: promised "
                  f"delete by ids rejected with {s1}: {raw1[:300]}")
            return

        # D1 face 1: count == 6
        cnt, cs, craw = exact_count(coll)
        if cs == -1:
            transport_dead("D1 count")
            return
        if 500 <= cs <= 599:
            if fail_5xx("D1 count", cs, str(craw)):
                return
        if cnt != N_SEED - 2:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — D1 count: "
                  f"expected {N_SEED - 2} (8 - 2 deleted), got {cnt}: {str(craw)[:300]}")
            return
        print(f"D1 count == {cnt} == {N_SEED - 2}")

        # D1 face 2: batch-get [1,2,3] -> exactly {3}
        got, s, craw = batch_get_ids(coll, [1, 2, 3])
        print(f"D1 batch-get [1,2,3] -> status={s}, ids={sorted(got) if got is not None else None}")
        if s == -1:
            transport_dead("D1 batch-get")
            return
        if 500 <= s <= 599:
            if fail_5xx("D1 batch-get", s, str(craw)):
                return
        if got != {3}:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — D1 "
                  f"batch-get: deleted ids must be absent and live id 3 present; "
                  f"got {sorted(got) if got is not None else 'non-array result'}: {str(craw)[:300]}")
            return
        print("D1 batch-get: ids == {3} exactly (no zombies)")

        # D1 face 3: single get — deleted id 1 -> 404, live id 3 -> 200
        for pid, expect, why in ((1, 404, "deleted"), (3, 200, "live")):
            sp, praw = single_get(coll, pid)
            print(f"D1 single GET id {pid} ({why}) -> status={sp}")
            if sp == -1:
                transport_dead(f"D1 single GET {pid}")
                return
            if 500 <= sp <= 599:
                if fail_5xx(f"D1 single GET {pid}", sp, praw):
                    return
            if sp != expect:
                kind = ("zombie point returned 200 after delete"
                        if expect == 404 else
                        "live point unreadable after an unrelated delete")
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — D1 "
                      f"single GET id {pid}: expected {expect}, got {sp} "
                      f"({kind}): {praw[:300]}")
                return

        # D1 face 4: scroll tag=alpha -> exactly {3,4}
        got, s, craw = scroll_ids(coll, {"must": [tag_cond("alpha")]})
        print(f"D1 scroll tag=alpha -> status={s}, ids={sorted(got) if got is not None else None}")
        if s == -1:
            transport_dead("D1 scroll")
            return
        if 500 <= s <= 599:
            if fail_5xx("D1 scroll", s, str(craw)):
                return
        if got != {3, 4}:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — D1 "
                  f"scroll tag=alpha: expected exactly {{3, 4}}, got "
                  f"{sorted(got) if got is not None else 'non-array result'}: {str(craw)[:300]}")
            return
        print("D1 scroll: ids == {3, 4} exactly")

        # D1 faces 5+6: search/query tag=alpha — absence + membership only
        for label, fn in (("search", search_ids), ("query", query_ids)):
            got, s, craw = fn(coll, {"must": [tag_cond("alpha")]})
            print(f"D1 {label} tag=alpha -> status={s}, ids={sorted(got) if got is not None else None}")
            if s == -1:
                transport_dead(f"D1 {label}")
                return
            if 500 <= s <= 599:
                if fail_5xx(f"D1 {label}", s, str(craw)):
                    return
            if got is None:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — D1 {label}: "
                      f"result not the declared array shape: {str(craw)[:300]}")
                return
            zombies = got & {1, 2}
            foreign = got - {3, 4}
            if zombies or foreign:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — D1 "
                      f"{label} tag=alpha: zombie ids {sorted(zombies)} survived "
                      f"the delete" + (f"; foreign ids {sorted(foreign)} outside "
                      f"the filter scope" if foreign else "") + f": {str(craw)[:300]}")
                return
        print("D1 search/query: no zombie ids, all results within {3, 4}")

        # ================= D2: delete by filter tag=beta, wait=true =================
        s2, _, raw2 = safe_request("POST", f"/collections/{coll}/points/delete",
                                   json={"filter": {"must": [tag_cond("beta")]}},
                                   timeout=60, params={"wait": "true"})
        print(f"\nD2 delete by filter must[tag=beta] wait=true -> status={s2}")
        print(f"raw: {raw2[:400]}")
        if s2 == -1:
            transport_dead("D2 delete")
            return
        if 500 <= s2 <= 599:
            if fail_5xx("D2 delete", s2, raw2):
                return
        if not (200 <= s2 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — D2: promised "
                  f"delete by filter rejected with {s2}: {raw2[:300]}")
            return

        # D2 face 1: count == 2
        cnt, cs, craw = exact_count(coll)
        if cs == -1:
            transport_dead("D2 count")
            return
        if 500 <= cs <= 599:
            if fail_5xx("D2 count", cs, str(craw)):
                return
        if cnt != N_SEED - 2 - 4:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — D2 count: "
                  f"expected {N_SEED - 2 - 4} (8 - 2 by-ids - 4 beta), got {cnt}: {str(craw)[:300]}")
            return
        print(f"D2 count == {cnt} == {N_SEED - 2 - 4}")

        # D2 face 2: batch-get [5,6] -> []
        got, s, craw = batch_get_ids(coll, [5, 6])
        print(f"D2 batch-get [5,6] -> status={s}, ids={sorted(got) if got is not None else None}")
        if s == -1:
            transport_dead("D2 batch-get")
            return
        if 500 <= s <= 599:
            if fail_5xx("D2 batch-get", s, str(craw)):
                return
        if got != set():
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — D2 "
                  f"batch-get: beta ids wiped by filter delete must be absent, "
                  f"got {sorted(got) if got is not None else 'non-array result'}: {str(craw)[:300]}")
            return
        print("D2 batch-get: ids == [] (no zombies)")

        # D2 face 3: single get id 5 -> 404, live id 3 -> 200
        for pid, expect, why in ((5, 404, "filter-deleted"), (3, 200, "live alpha")):
            sp, praw = single_get(coll, pid)
            print(f"D2 single GET id {pid} ({why}) -> status={sp}")
            if sp == -1:
                transport_dead(f"D2 single GET {pid}")
                return
            if 500 <= sp <= 599:
                if fail_5xx(f"D2 single GET {pid}", sp, praw):
                    return
            if sp != expect:
                kind = ("zombie point returned 200 after filter delete"
                        if expect == 404 else
                        "unrelated live point lost after filter delete")
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — D2 "
                      f"single GET id {pid}: expected {expect}, got {sp} "
                      f"({kind}): {praw[:300]}")
                return

        # D2 face 4: scroll tag=beta -> []
        got, s, craw = scroll_ids(coll, {"must": [tag_cond("beta")]})
        print(f"D2 scroll tag=beta -> status={s}, ids={sorted(got) if got is not None else None}")
        if s == -1:
            transport_dead("D2 scroll")
            return
        if 500 <= s <= 599:
            if fail_5xx("D2 scroll", s, str(craw)):
                return
        if got != set():
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — D2 "
                  f"scroll tag=beta: expected empty, got "
                  f"{sorted(got) if got is not None else 'non-array result'}: {str(craw)[:300]}")
            return
        print("D2 scroll: ids == [] (wipe complete)")

        # D2 faces 5+6: search/query tag=beta -> empty (0 live candidates in scope)
        for label, fn in (("search", search_ids), ("query", query_ids)):
            got, s, craw = fn(coll, {"must": [tag_cond("beta")]})
            print(f"D2 {label} tag=beta -> status={s}, ids={sorted(got) if got is not None else None}")
            if s == -1:
                transport_dead(f"D2 {label}")
                return
            if 500 <= s <= 599:
                if fail_5xx(f"D2 {label}", s, str(craw)):
                    return
            if got is None:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — D2 {label}: "
                      f"result not the declared array shape: {str(craw)[:300]}")
                return
            if got:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — D2 "
                      f"{label} tag=beta: filter scope has 0 live candidates but "
                      f"returned {sorted(got)}: {str(craw)[:300]}")
                return
        print("D2 search/query: empty results (no beta zombies)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
