#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_delete_002
# strategy: delete_consistency
# endpoint: points+delete
# constraint_ids: qdrant_behavioral_points_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: positive-negative face matrix (G4/G5/G9) x
  qdrant_behavioral_points_delete_001 "valid delete returns HTTP 200;
  missing collection returns 404; malformed filter returns 400".
  Positive faces: (B1) ids-branch delete of an existing id -> exactly 200;
  (B2) filter-branch delete of a valid Filter -> exactly 200. Negative
  faces with typed oracles: (B3) delete of valid ids against a VERIFIED
  non-existent collection -> exactly 404 (200 = phantom mutation accepted
  on a missing collection; 400/422 = disposition mismatch vs documented
  404; 5xx with service alive = crash-face). (B4) four malformed Filter
  shapes from the contract Filter form {should?,min_should?,must?,must_not?}
  (each clause an array of conditions): m1 must="not-a-list" (clause type
  confusion, BS-01), m2 should=null (explicit null clause, BS-01
  manifestation "filter.should=null"), m3 must=[{key:"grp"}] (condition
  with key but no match/range), m4 must=[{match:{value:"b"}}] (match
  without key) -> each must return 400; a 200 = Type1_IllegalSuccess and
  additionally triggers a state-reconciliation check (exact count must be
  unchanged — a silently-applied null/invalid clause wiping points is the
  BS-01 undefined-behavior manifestation). (B5) empty selector {} (neither
  points nor filter — the selector oneOf has no matching branch; BS-04
  "delete with empty selector") -> 400; 200 = Type1 validation gap,
  re-checked against the count. The positive faces share the same
  collection and seed as the negative ones so disposition asymmetry
  (same parameter family treated inconsistently, G9) is visible.
  [chunk_points+delete coverage: delete_consistency x
  qdrant_behavioral_points_delete_001 (200/404/400 disposition matrix +
  BS-01 malformed-filter x4 + BS-04 empty selector + state reconciliation)]
Oracle: B1 -> ids-delete 200; B2 -> filter-delete 200 (non-200 on a valid
  selector face = Type4_StateLogicViolation); B3 -> exactly 404 (200 =
  phantom Type4; 400/422 = documented-disposition mismatch Type4; 5xx with
  /healthz alive = Type3_RuntimeFailure); B4 m1-m4 -> each exactly 400
  (200 = Type1_IllegalSuccess and exact count must stay 3 — count drop =
  Type4 undefined-behavior corruption; 5xx alive = Type3); B5 -> {} body
  exactly 400 (200 = Type1 validation gap, count must stay 3); transport
  failure -> liveness re-check before any verdict.
"""

import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p / "scripts")
            break
if not _sd or not Path(_sd, "runtime", "__init__.py").exists():
    print("VERDICT: SCRIPT_ERROR - runtime scripts dir not found (TESTVDB_SCRIPTS_DIR unset)")
    sys.exit(2)
sys.path.insert(0, _sd)

if not os.environ.get("TESTVDB_TARGET"):
    for _p in Path(__file__).resolve().parents:
        _c = _p / "structured_contract.json"
        if _c.exists():
            try:
                _t = json.loads(_c.read_text(encoding="utf-8")).get("target", "")
                if _t:
                    os.environ["TESTVDB_TARGET"] = str(_t).lower()
            except Exception:
                pass
            break

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

# URLs used VERBATIM from raw_knowledge api_endpoints[]:
#   {"endpoint_name": "Delete Points", "method": "POST",
#    "url": "/collections/{collection_name}/points/delete"}   -> runtime delete_points
#   {"endpoint_name": "Check Collection Exists", "method": "GET",
#    "url": "/collections/{collection_name}/exists"}          -> collection_exists
rt.PATHS["collection_exists"] = "/collections/{collection_name}/exists"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('collection_exists', 'delete_points')]}")

DEFECTS = []
ABORT = [False]


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def result_of(raw):
    try:
        return json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return None


def raw_snip(raw):
    return str(raw)[:150].replace("\n", " ")


def classify_transport(tag, s, raw, ctx):
    """0/5xx handling with mandatory liveness re-check."""
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        return True
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {s} with service alive — "
                           f"Type3_RuntimeFailure — raw={raw_snip(raw)}")
            return True
        ABORT[0] = True
        return True
    return False


def delete_body(tag, coll, body):
    s, raw = safe_request("POST", "delete_points",
                          path_params={"name": coll},
                          body=body,
                          query_params={"wait": "true"})
    print(f"[{tag}] status={s} body={json.dumps(body)[:130]} "
          f"raw={str(raw)[:200]}")
    if classify_transport(tag, s, raw, tag):
        return s
    return s


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if classify_transport(tag, s, raw, tag):
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} count returned {s}")
        return None
    res = result_of(raw)
    cnt = res.get("count") if isinstance(res, dict) else None
    if isinstance(cnt, bool) or not isinstance(cnt, int):
        print(f"SETUP_ERROR: {tag} count result.count missing")
        return None
    return cnt


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spdel2_" + TS + "_"
    C = PFX + "col"
    MISSING = PFX + "missing"
    DIM = 4

    def vec(i):
        return [0.1 + 0.01 * (i % 6), 0.5, 0.75, 1.0]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C},
                              body={"points": [
                                  {"id": 100 + i, "vector": vec(i),
                                   "payload": {"grp": "a" if i < 3 else "b",
                                               "n": i}}
                                  for i in range(6)]},
                              query_params={"wait": "true"})
        print(f"[seed upsert 6 pts] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if exact_count("seed", C) != 6:
            print("SETUP_ERROR: seed count != 6")
            return "SCRIPT_ERROR"

        # ---- B3 first: verify MISSING truly absent, then delete against it ----
        s, raw = safe_request("GET", "collection_exists",
                              path_params={"collection_name": MISSING})
        print(f"[B3 exists {MISSING}] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print("SETUP_ERROR: exists probe not 200")
            return "SCRIPT_ERROR"
        res = result_of(raw)
        exists = res.get("exists") if isinstance(res, dict) else None
        if exists is not True:
            print(f"[B3] exists probe returned exists={exists!r} — "
                  f"collection name collision; retiring name")
            MISSING = MISSING + "x9"
        s = delete_body("B3-missing-collection", MISSING, {"points": [1]})
        if s == 200:
            DEFECTS.append(f"(B3) delete against missing collection returned "
                           f"200 — phantom mutation accepted — "
                           f"Type4_StateLogicViolation")
        elif s != 404:
            DEFECTS.append(f"(B3) delete against missing collection returned "
                           f"{s} (documented disposition is 404) — "
                           f"Type4_StateLogicViolation")

        # ---- B1: positive ids-branch face ----
        s = delete_body("B1-ids-branch", C, {"points": [100]})
        if s != 200:
            DEFECTS.append(f"(B1) valid ids-delete returned {s} "
                           f"(expected 200) — Type4_StateLogicViolation")
        else:
            print("[B1] OK: valid ids-delete 200")

        # ---- B2: positive filter-branch face ----
        s = delete_body("B2-filter-branch", C,
                        {"filter": {"must": [{"key": "grp",
                                              "match": {"value": "a"}}]}})
        if s != 200:
            DEFECTS.append(f"(B2) valid filter-delete returned {s} "
                           f"(expected 200) — Type4_StateLogicViolation")
        else:
            print("[B2] OK: valid filter-delete 200")
        # arithmetic: 6 seeded - 1 (B1) - 2 (grp=a: ids 101,102) = 3
        base = exact_count("baseline", C)
        if base != 3:
            DEFECTS.append(f"(baseline) exact count {base} != 6-1-2=3 after "
                           f"the two positive deletes — "
                           f"Type4_StateLogicViolation")

        # ---- B4: malformed filters must be 400-rejected ----
        malformed = [
            ("m1-must-not-a-list", {"filter": {"must": "not-a-list"}}),
            ("m2-should-null", {"filter": {"should": None}}),
            ("m3-cond-without-match", {"filter": {"must": [{"key": "grp"}]}}),
            ("m4-match-without-key",
             {"filter": {"must": [{"match": {"value": "b"}}]}}),
        ]
        for tag, body in malformed:
            s = delete_body(tag, C, body)
            if s == 200:
                DEFECTS.append(f"({tag}) malformed filter accepted with 200 "
                               f"— Type1_IllegalSuccess (behavioral "
                               f"assertion promises 400 on invalid filter)")
                cnt = exact_count(tag, C)
                if cnt is not None and cnt != 3:
                    DEFECTS.append(f"({tag}) exact count {cnt} != 3 after a "
                                   f"200-accepted malformed filter — invalid "
                                   f"clause silently applied — "
                                   f"Type4_StateLogicViolation")
            elif s not in (400,):
                DEFECTS.append(f"({tag}) malformed filter returned {s} "
                               f"(expected 400) — "
                               f"Type4_StateLogicViolation")

        # ---- B5: empty selector (oneOf: neither points nor filter) ----
        s = delete_body("B5-empty-selector", C, {})
        if s == 200:
            DEFECTS.append("(B5) empty selector accepted with 200 — "
                           "Type1_IllegalSuccess (selector oneOf has no "
                           "matching branch; 400 expected)")
            cnt = exact_count("B5", C)
            if cnt is not None and cnt != 3:
                DEFECTS.append(f"(B5) exact count {cnt} != 3 after "
                               f"200-accepted empty selector — silent "
                               f"mutation — Type4_StateLogicViolation")
        elif s != 400:
            DEFECTS.append(f"(B5) empty selector returned {s} "
                           f"(expected 400) — Type4_StateLogicViolation")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        if ABORT[0]:
            print("ABORT: environment/transport unavailable mid-run")
            return "SCRIPT_ERROR"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass
        try:
            rt.drop_collection(MISSING)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
