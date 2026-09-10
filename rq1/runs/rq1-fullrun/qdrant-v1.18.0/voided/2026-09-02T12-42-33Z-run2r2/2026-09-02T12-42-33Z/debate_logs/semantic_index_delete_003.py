#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_index_delete_003
# strategy: filter_semantics
# endpoint: index+delete
# constraint_ids: qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - "index deletion leaves point data
#   untouched" implies the payload values stay FILTERABLE: an index removal
#   that silently degrades filter evaluation on the de-indexed field (full
#   table, empty set, wrong subset) violates the data-untouched promise even
#   though no row was physically dropped)
"""
Attack: filter_semantics (S7, G4/G5) x
  constraints::qdrant_state_index_delete_001 on index+delete
  (chunk_index+delete unit constraints::qdrant_state_index_delete_001,
  evidence_tier=explicit, system level - the data-untouched promise read
  through the filter face: payload that survived index deletion must still
  filter EXACTLY).
  R22 chunk_index+delete semantic coverage map: see _001 (this script =
  slot 3 of 6: filter_semantics x state_index_delete_001).
Oracle: with seeded data (5 points: cat A/B at ids {1,3,5}/{2,4}, score
  10/40/20/50/30) and both indexes (cat keyword, score integer) verified
  echoed then DELETED with 200 + describe result.payload_schema entries
  gone (removal premise; 200-without-removal = Type4 silent no-op), the
  three filters evaluated on the de-indexed fields return EXACTLY the
  pre-declared sets - must match cat=A -> ids {1,3,5} (count exact 3);
  must range score>25 -> ids {2,4,5} (count exact 3); combined must
  [cat=A, score>15] -> ids {3,5} (count exact 2); no-filter control
  count exact == 5. whole-table hits (filter silently dropped), 0-hit
  (filter silently failing) or any wrong subset = Type4_
  StateLogicViolation; a non-200 on any filter leg = Type4/Type1 per
  branch; the SAME filters measured BEFORE deletion must already match
  the declared sets (premise calibration - a pre-delete mismatch is
  SCRIPT_ERROR, a setup fault never a defect, G8); 5xx with healthy
  /healthz = Type3_RuntimeFailure; transport/setup failures never
  produce defect conclusions (G8).

Constraint anchor qdrant_state_index_delete_001 (explicit, system level):
  assertion: "delete of a non-existent payload index is an idempotent
  success; index deletion leaves point data untouched"
  (source_url https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index,
  doc_version 1.18.x (versioned v-1-18-x api-reference)). The filter face
  here is the observability instrument for 'data untouched': untouched
  payload values keep their exact filter semantics (qdrant Filter syntax
  per contract data_types: must / match.value / range.gt).

Legs:
  leg 0 premise - collection + 5 seeded points + keyword index cat +
      integer index score (both echoed in describe); calibration: all
      three filters already return the declared sets BEFORE deletion;
  leg 1 removal - DELETE both indexes -> 200 each + describe entries
      gone (the state under test is genuinely de-indexed);
  leg 2 equality - must match cat=A on the de-indexed field -> exactly
      ids {1,3,5}, count exact 3;
  leg 3 range - must range score>25 on the de-indexed field -> exactly
      ids {2,4,5}, count exact 3;
  leg 4 combined - must [cat=A, score>15] -> exactly ids {3,5},
      count exact 2;
  leg 5 control - no-filter count exact == 5 (whole table intact).

URL derivation: runtime PATHS keys only (delete_index/create_index/
  describe_collection/upsert_points/scroll/count/healthz); scroll ->
  result.points, count -> result.count per the points+scroll /
  points+count response_shape grids. Scroll/count chosen over search on
  purpose: deterministic cardinality oracles, no HNSW by-design
  non-determinism (threat model G3 avoidance). R15-R21 lessons honored:
  bare constraint IDs; unique prefix; wait string-form query param;
  cleanup drops only script-owned collections.
"""
import os
import sys
import json
import time
import uuid
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ----
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
if os.environ.get("TESTVDB_TARGET", "").lower() != "qdrant":
    print(f"VERDICT: SCRIPT_ERROR - contract target mismatch (expected qdrant, got {os.environ.get('TESTVDB_TARGET')!r})")
    sys.exit(2)
try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)
if not os.environ.get("TESTVDB_DB_URL"):
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

PFX = "sidl03" + uuid.uuid4().hex[:6]
DIM = 4
COL = PFX + "_live"
# seeded truth table (the oracle is derived from THIS table, not from a readback)
SEED = [
    {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"cat": "A", "score": 10}},
    {"id": 2, "vector": [0.4, 0.3, 0.2, 0.1], "payload": {"cat": "B", "score": 40}},
    {"id": 3, "vector": [0.1, 0.1, 0.1, 0.1], "payload": {"cat": "A", "score": 20}},
    {"id": 4, "vector": [0.5, 0.5, 0.5, 0.5], "payload": {"cat": "B", "score": 50}},
    {"id": 5, "vector": [0.2, 0.2, 0.2, 0.2], "payload": {"cat": "A", "score": 30}},
]
N_PTS = len(SEED)
FIELDS = {"cat": "keyword", "score": "integer"}
FILTER_MATCH_A = {"must": [{"key": "cat", "match": {"value": "A"}}]}
FILTER_RANGE_GT25 = {"must": [{"key": "score", "range": {"gt": 25}}]}
FILTER_COMBINED = {"must": [{"key": "cat", "match": {"value": "A"}},
                            {"key": "score", "range": {"gt": 15}}]}
ALL_IDS = {p["id"] for p in SEED}
EXPECTED = {
    "match_cat_A": ({1, 3, 5}, FILTER_MATCH_A),
    "range_score_gt25": ({2, 4, 5}, FILTER_RANGE_GT25),
    "combined_catA_score_gt15": ({3, 5}, FILTER_COMBINED),
}


def safe_request(method, path_key, body=None, path_params=None, query_params=None,
                 timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def jload(raw):
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz", timeout=15)
    print(f"[{tag}] /healthz probe status={hs} raw={str(hraw)[:120]}")
    return hs


def transport_guard(label, st, raw):
    if st <= 0 or 500 <= st <= 599:
        hs = liveness(label)
        if hs != 200:
            defect("Type3_RuntimeFailure",
                   f"service down - '{label}' got status={st} and /healthz={hs}")
        if st <= 0:
            script_error(f"transport failure '{label}' with healthy /healthz: {str(raw)[:150]}")
        defect("Type3_RuntimeFailure",
               f"'{label}' got {st} with /healthz alive; raw={str(raw)[:250]}")
    return st


def delete_index(name, field, tag=""):
    st, raw = safe_request("DELETE", "delete_index",
                           path_params={"name": name, "field_name": field},
                           query_params={"wait": "true"}, timeout=30)
    print(f"[DELETE index{(' ' + tag) if tag else ''} {name}/{field}] -> status={st} raw={str(raw)[:200]}")
    return st, raw


def field_in_index_container(name, field):
    st, raw = safe_request("GET", "describe_collection", path_params={"name": name},
                           timeout=30)
    if st != 200:
        script_error(f"describe {name} failed: {st} {str(raw)[:200]}")
    res = jload(raw).get("result") if isinstance(jload(raw), dict) else None
    if not isinstance(res, dict):
        script_error(f"describe {name}: result not an object: {str(raw)[:200]}")
    for container in ("payload_schema", "payload_indexes"):
        v = res.get(container)
        if isinstance(v, dict) and field in v:
            return True
    return False


def scroll_filter_ids(name, flt, tag):
    """scroll with filter -> set of point ids (deterministic full scan)."""
    body = {"limit": 100, "with_payload": False, "with_vector": False}
    if flt is not None:
        body["filter"] = flt
    st, raw = safe_request("POST", "scroll", body=body,
                           path_params={"name": name}, timeout=30)
    transport_guard(f"scroll filter {tag}", st, raw)
    if st != 200:
        defect("Type4_StateLogicViolation" if 500 <= st < 600 else "Type1_IllegalRejection",
               f"filtered scroll ({tag}) answered HTTP {st} on the de-indexed fields: "
               f"{str(raw)[:300]!r}")
    res = jload(raw).get("result") if isinstance(jload(raw), dict) else None
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        defect("Type4_StateLogicViolation",
               f"scroll {tag}: result.points not an array (points+scroll response_shape "
               f"declares result.points:array): {str(raw)[:300]!r}")
    ids = sorted(p.get("id") for p in pts if isinstance(p, dict))
    print(f"[scroll {tag}] ids={ids}")
    return set(ids)


def count_filter(name, flt, tag):
    body = {"exact": True}
    if flt is not None:
        body["filter"] = flt
    st, raw = safe_request("POST", "count", body=body,
                           path_params={"name": name}, timeout=30)
    transport_guard(f"count {tag}", st, raw)
    if st != 200:
        defect("Type4_StateLogicViolation" if 500 <= st < 600 else "Type1_IllegalRejection",
               f"count ({tag}) answered HTTP {st}: {str(raw)[:300]!r}")
    res = jload(raw).get("result") if isinstance(jload(raw), dict) else None
    cnt = res.get("count") if isinstance(res, dict) else None
    if not isinstance(cnt, int):
        defect("Type4_StateLogicViolation",
               f"count {tag}: result.count not an integer (points+count response_shape "
               f"declares result.count:integer): {str(raw)[:300]!r}")
    print(f"[count {tag}] exact={cnt}")
    return cnt


def run_filter_legs(tag_prefix):
    """All three declared filters + the no-filter control; assert exact sets."""
    for leg, (expected_ids, flt) in EXPECTED.items():
        got = scroll_filter_ids(COL, flt, f"{tag_prefix}:{leg}")
        if got != expected_ids:
            if got == ALL_IDS:
                form = "whole-table hit (filter silently dropped)"
            elif not got:
                form = "empty set (filter silently failing)"
            else:
                form = "wrong subset (semantics corrupted)"
            defect("Type4_StateLogicViolation",
                   f"filter {leg!r} after index deletion returned ids {sorted(got)}; the "
                   f"seeded truth table requires exactly {sorted(expected_ids)} - "
                   f"{form} on the de-indexed field violates 'index deletion leaves "
                   f"point data untouched'")
        exp_cnt = len(expected_ids)
        got_cnt = count_filter(COL, flt, f"{tag_prefix}:{leg}")
        if got_cnt != exp_cnt:
            defect("Type4_StateLogicViolation",
                   f"count exact for {leg!r} after index deletion is {got_cnt}; expected "
                   f"{exp_cnt} per the seeded truth table (scroll ids already matched - "
                   f"count/filter disagree = semantics corrupted on the de-indexed field)")
    ctrl = count_filter(COL, None, f"{tag_prefix}:no-filter-control")
    if ctrl != N_PTS:
        defect("Type4_StateLogicViolation",
               f"no-filter control count is {ctrl}; expected {N_PTS} - the whole table "
               f"must be intact after index deletion")


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception as e:
        print(f"cleanup warning (drop {COL}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[constraint quote] assertion: 'delete of a non-existent payload index "
          "is an idempotent success; index deletion leaves point data untouched'")
    try:
        # ---- leg 0: premise + calibration BEFORE deletion ----
        ok, err = rt.setup_default(COL, dim=DIM, metric="Cosine")
        if not ok:
            script_error(f"premise create {COL} failed: {err}")
        st, raw = safe_request("PUT", "upsert_points", body={"points": SEED},
                               path_params={"name": COL},
                               query_params={"wait": "true"}, timeout=30)
        transport_guard("setup upsert", st, raw)
        if st not in (200, 201):
            script_error(f"setup upsert failed: {st} {str(raw)[:200]}")
        for field, schema in FIELDS.items():
            st, raw = safe_request("PUT", "create_index",
                                   body={"field_name": field, "field_schema": schema},
                                   path_params={"name": COL},
                                   query_params={"wait": "true"}, timeout=30)
            transport_guard(f"setup index {field}", st, raw)
            if st != 200 or not field_in_index_container(COL, field):
                script_error(f"premise: index on {field!r} not echoed (status={st})")
        # calibration: filters must match the truth table while indexes exist;
        # a mismatch here is a SETUP fault (never a defect on index+delete, G8)
        for leg, (expected_ids, flt) in EXPECTED.items():
            got = scroll_filter_ids(COL, flt, f"calibration:{leg}")
            if got != expected_ids:
                script_error(f"calibration: filter {leg!r} returned {sorted(got)} BEFORE "
                             f"deletion (expected {sorted(expected_ids)}) - setup fault, "
                             f"not an index+delete defect")

        # ---- leg 1: removal - both indexes gone with 200s ----
        for field in sorted(FIELDS):
            st, raw = delete_index(COL, field, "removal")
            transport_guard(f"delete {field}", st, raw)
            if st != 200:
                defect("Type1_IllegalRejection" if 400 <= st < 500 else "Type4_StateLogicViolation",
                       f"DELETE of EXISTING index {field!r} answered HTTP {st}: "
                       f"{str(raw)[:300]!r}")
            if field_in_index_container(COL, field):
                defect("Type4_StateLogicViolation",
                       f"DELETE of index {field!r} answered 200 but the entry is STILL in "
                       f"the describe payload index container - 200-without-removal silent "
                       f"no-op; the de-indexed state under test was never reached")

        # ---- legs 2-5: exact-hit filters on the de-indexed fields ----
        run_filter_legs("post-delete")

        print("OK: after 200-removal of cat/score indexes, equality/range/combined "
              "filters on the de-indexed fields return exactly the seeded truth sets "
              "[1,3,5] / [2,4,5] / [3,5] with matching exact counts, and the no-filter "
              "control still counts 5 - payload filter semantics untouched")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
