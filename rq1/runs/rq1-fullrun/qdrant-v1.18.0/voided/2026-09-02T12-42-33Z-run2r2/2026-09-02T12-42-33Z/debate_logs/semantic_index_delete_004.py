#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_index_delete_004
# strategy: metamorphic
# endpoint: index+delete
# constraint_ids: qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the state promise 'index deletion
#   leaves point data untouched' implies a metamorphic invariant: identical
#   filtered queries are INVARIANT under index create/delete toggling; an
#   implementation that couples filter evaluation to index presence drifts
#   the moment the index leaves)
"""
Attack: metamorphic (S6, G6 mutation justified, G9 cross-face) x
  constraints::qdrant_state_index_delete_001 on index+delete
  (chunk_index+delete unit constraints::qdrant_state_index_delete_001,
  evidence_tier=explicit, system level).
  R22 chunk_index+delete semantic coverage map: see _001 (this script =
  slot 4 of 6: metamorphic x state_index_delete_001).
  G6 mutation justification: toggling payload-index PRESENCE (create ->
  delete -> re-create -> delete) is the mutation most likely to break the
  invariant 'query semantics are independent of index presence' - filter
  implementations that route through the index (vs a full-scan fallback)
  are exactly the ones that drift when the index is removed, and the
  delete face is the only way to reach the de-indexed states.
Oracle: with 5 seeded points (cat A at {1,3,5}, B at {2,4}; score
  10/40/20/50/30), the two tracked queries - must match cat=A (expected
  exactly ids {1,3,5}) and must range score>25 (expected exactly ids
  {2,4,5}) - return the IDENTICAL id set at all FIVE index lifecycle
  states: S0 no index, S1 both indexes created (wait=true, verified
  echoed in describe result.payload_schema), S2 both deleted (200 +
  entries gone), S3 both re-created (entries echoed AGAIN - the create
  face must still work after the delete face was used, cross-face G9),
  S4 deleted again (200 + entries gone). ANY drift between any two
  states = Type4_StateLogicViolation (filter semantics coupled to index
  presence - 'index deletion leaves point data untouched' violated
  through the query face); a 200 delete whose entry survives describe =
  Type4 silent no-op; a failed re-create echo at S3 = Type4 create-face
  regression after delete; non-200 on any create/delete leg per branch
  (4xx = Type1_IllegalRejection on a documented-legal operation);
  5xx with healthy /healthz = Type3_RuntimeFailure; transport/setup
  failures never produce defect conclusions (G8).

Constraint anchor qdrant_state_index_delete_001 (explicit, system level):
  assertion: "delete of a non-existent payload index is an idempotent
  success; index deletion leaves point data untouched"
  (source_url https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index,
  doc_version 1.18.x (versioned v-1-18-x api-reference)).

URL derivation: runtime PATHS keys only (delete_index/create_index/
  describe_collection/upsert_points/scroll/healthz); scroll ->
  result.points per the points+scroll response_shape grid. Deterministic
  scroll chosen over search (no HNSW by-design non-determinism, threat
  model G3). R15-R21 lessons honored: bare constraint IDs; unique prefix;
  wait string-form query param; cleanup drops only script-owned
  collections.
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

PFX = "sidl04" + uuid.uuid4().hex[:6]
DIM = 4
COL = PFX + "_live"
SEED = [
    {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"cat": "A", "score": 10}},
    {"id": 2, "vector": [0.4, 0.3, 0.2, 0.1], "payload": {"cat": "B", "score": 40}},
    {"id": 3, "vector": [0.1, 0.1, 0.1, 0.1], "payload": {"cat": "A", "score": 20}},
    {"id": 4, "vector": [0.5, 0.5, 0.5, 0.5], "payload": {"cat": "B", "score": 50}},
    {"id": 5, "vector": [0.2, 0.2, 0.2, 0.2], "payload": {"cat": "A", "score": 30}},
]
FIELDS = {"cat": "keyword", "score": "integer"}
TRACKED = {
    "match_cat_A": ({"must": [{"key": "cat", "match": {"value": "A"}}]}, {1, 3, 5}),
    "range_score_gt25": ({"must": [{"key": "score", "range": {"gt": 25}}]}, {2, 4, 5}),
}
STATES = ["S0_no_index", "S1_indexed", "S2_deleted", "S3_recreated", "S4_deleted_again"]


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


def put_index(field, schema):
    st, raw = safe_request("PUT", "create_index",
                           body={"field_name": field, "field_schema": schema},
                           path_params={"name": COL},
                           query_params={"wait": "true"}, timeout=30)
    print(f"[PUT index {field}] schema={schema} -> status={st} raw={str(raw)[:200]}")
    return st, raw


def delete_index(field, tag=""):
    st, raw = safe_request("DELETE", "delete_index",
                           path_params={"name": COL, "field_name": field},
                           query_params={"wait": "true"}, timeout=30)
    print(f"[DELETE index{(' ' + tag) if tag else ''} {field}] -> status={st} raw={str(raw)[:200]}")
    return st, raw


def index_entry_present(field):
    st, raw = safe_request("GET", "describe_collection", path_params={"name": COL},
                           timeout=30)
    if st != 200:
        script_error(f"describe {COL} failed: {st} {str(raw)[:200]}")
    res = jload(raw).get("result") if isinstance(jload(raw), dict) else None
    if not isinstance(res, dict):
        script_error(f"describe {COL}: result not an object: {str(raw)[:200]}")
    for container in ("payload_schema", "payload_indexes"):
        v = res.get(container)
        if isinstance(v, dict) and field in v:
            return True
    return False


def measure(state_tag):
    """Run both tracked filtered queries; return dict leg -> id set."""
    out = {}
    for leg, (flt, _) in TRACKED.items():
        st, raw = safe_request("POST", "scroll",
                               body={"limit": 100, "with_payload": False,
                                     "with_vector": False, "filter": flt},
                               path_params={"name": COL}, timeout=30)
        transport_guard(f"scroll {state_tag}:{leg}", st, raw)
        if st != 200:
            defect("Type4_StateLogicViolation" if 500 <= st < 600 else "Type1_IllegalRejection",
                   f"tracked query {leg!r} at state {state_tag} answered HTTP {st}: "
                   f"{str(raw)[:300]!r}")
        res = jload(raw).get("result") if isinstance(jload(raw), dict) else None
        pts = res.get("points") if isinstance(res, dict) else None
        if not isinstance(pts, list):
            defect("Type4_StateLogicViolation",
                   f"scroll {state_tag}:{leg}: result.points not an array "
                   f"(points+scroll response_shape declares result.points:array): "
                   f"{str(raw)[:300]!r}")
        ids = sorted(p.get("id") for p in pts if isinstance(p, dict))
        out[leg] = set(ids)
    print(f"[measure {state_tag}] " + " ".join(f"{k}={sorted(v)}" for k, v in out.items()))
    return out


def assert_expected(state_tag, measured):
    for leg, (_, expected) in TRACKED.items():
        if measured[leg] != expected:
            defect("Type4_StateLogicViolation",
                   f"tracked query {leg!r} at state {state_tag} returned "
                   f"{sorted(measured[leg])}; seeded truth table requires "
                   f"{sorted(expected)} - premise broken before the metamorphic "
                   f"comparison can run")


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
        # ---- premise: collection + seeded points, NO index yet (S0) ----
        ok, err = rt.setup_default(COL, dim=DIM, metric="Cosine")
        if not ok:
            script_error(f"premise create {COL} failed: {err}")
        st, raw = safe_request("PUT", "upsert_points", body={"points": SEED},
                               path_params={"name": COL},
                               query_params={"wait": "true"}, timeout=30)
        transport_guard("setup upsert", st, raw)
        if st not in (200, 201):
            script_error(f"setup upsert failed: {st} {str(raw)[:200]}")
        for f in FIELDS:
            if index_entry_present(f):
                script_error(f"premise broken: {f!r} already indexed on a fresh collection")

        results = {}

        # ---- S0: no index (baseline) ----
        results["S0_no_index"] = measure("S0_no_index")
        assert_expected("S0_no_index", results["S0_no_index"])

        # ---- S1: both indexes created ----
        for f, s in FIELDS.items():
            st, raw = put_index(f, s)
            transport_guard(f"S1 create {f}", st, raw)
            if st != 200:
                defect("Type1_IllegalRejection" if 400 <= st < 500 else "Type4_StateLogicViolation",
                       f"S1: legal create of {f!r} index answered HTTP {st}: {str(raw)[:300]!r}")
            if not index_entry_present(f):
                defect("Type4_StateLogicViolation",
                       f"S1: index on {f!r} answered 200 but is not echoed in describe "
                       f"payload index container (200-without-echo, R21 lesson)")
        results["S1_indexed"] = measure("S1_indexed")

        # ---- S2: both deleted ----
        for f in sorted(FIELDS):
            st, raw = delete_index(f, "S2")
            transport_guard(f"S2 delete {f}", st, raw)
            if st != 200:
                defect("Type1_IllegalRejection" if 400 <= st < 500 else "Type4_StateLogicViolation",
                       f"S2: legal delete of {f!r} index answered HTTP {st}: {str(raw)[:300]!r}")
            if index_entry_present(f):
                defect("Type4_StateLogicViolation",
                       f"S2: delete of {f!r} answered 200 but the entry survives describe - "
                       f"200-without-removal silent no-op")
        results["S2_deleted"] = measure("S2_deleted")

        # ---- S3: re-created (create face usable AFTER the delete face, G9) ----
        for f, s in FIELDS.items():
            st, raw = put_index(f, s)
            transport_guard(f"S3 re-create {f}", st, raw)
            if st != 200:
                defect("Type1_IllegalRejection" if 400 <= st < 500 else "Type4_StateLogicViolation",
                       f"S3: re-create of {f!r} index after delete answered HTTP {st} - "
                       f"create face regressed after the delete face was used (G9 "
                       f"cross-face): {str(raw)[:300]!r}")
            if not index_entry_present(f):
                defect("Type4_StateLogicViolation",
                       f"S3: re-created index on {f!r} answered 200 but is not echoed - "
                       f"create face silent-ignore after delete (G9 cross-face)")
        results["S3_recreated"] = measure("S3_recreated")

        # ---- S4: deleted again ----
        for f in sorted(FIELDS):
            st, raw = delete_index(f, "S4")
            transport_guard(f"S4 delete {f}", st, raw)
            if st != 200:
                defect("Type1_IllegalRejection" if 400 <= st < 500 else "Type4_StateLogicViolation",
                       f"S4: second legal delete of {f!r} index answered HTTP {st}: "
                       f"{str(raw)[:300]!r}")
            if index_entry_present(f):
                defect("Type4_StateLogicViolation",
                       f"S4: delete of {f!r} answered 200 but the entry survives describe")
        results["S4_deleted_again"] = measure("S4_deleted_again")

        # ---- metamorphic comparison: all five states identical ----
        base_state = STATES[0]
        for state in STATES[1:]:
            for leg in TRACKED:
                if results[state][leg] != results[base_state][leg]:
                    defect("Type4_StateLogicViolation",
                           f"metamorphic invariant broken for tracked query {leg!r}: "
                           f"{base_state} -> {sorted(results[base_state][leg])} but "
                           f"{state} -> {sorted(results[state][leg])} - filtered query "
                           f"results depend on payload-index presence, i.e. index "
                           f"deletion/creation changed query semantics ('index deletion "
                           f"leaves point data untouched' violated through the query face)")

        print("OK: both tracked filtered queries returned identical id sets at all "
              "five index lifecycle states (no-index / indexed / deleted / recreated "
              "/ deleted-again); re-create echoed after delete; both deletes removed "
              "their describe entries")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
