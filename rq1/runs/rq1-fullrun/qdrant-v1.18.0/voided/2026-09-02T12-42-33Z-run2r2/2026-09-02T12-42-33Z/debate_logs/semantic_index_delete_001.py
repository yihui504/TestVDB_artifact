#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_index_delete_001
# strategy: behavioral_contract
# endpoint: index+delete
# constraint_ids: qdrant_behavioral_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the published promise "index deletion
#   (existing or not) returns HTTP 200; missing collection returns 404" is
#   verified branch-by-branch against the live v1.18.0 runtime, including the
#   result:object envelope and the describe-readback disappearance that a
#   "200 ok" answer implicitly promises)
"""
Attack: behavioral_contract (S1, G4 positive/negative pairing, G7 oracle-first)
  x assertions::qdrant_behavioral_index_delete_001 on index+delete
  (chunk_index+delete unit assertions::qdrant_behavioral_index_delete_001 -
  expected_behavior: "index deletion (existing or not) returns HTTP 200;
  missing collection returns 404", evidence_tier=explicit, endpoint level).
  R22 chunk_index+delete semantic coverage map (G10 reconciliation):
    _001 behavioral_contract x behavioral_index_delete_001 (this script -
        three-branch status contract 200/200/404 + envelope + removal echo);
    _002 behavioral_contract x state_index_delete_001 (idempotent-success
        positive + the data-untouched negative construction, Type4);
    _003 filter_semantics x state_index_delete_001 (exact-hit filters on
        de-indexed fields, Type4);
    _004 metamorphic x state_index_delete_001 (result-set invariance across
        the index create/delete lifecycle + re-create reversibility, G9);
    _005 diagnosis_quality x behavioral_index_delete_001 (Type-2 rubric on
        the 404 body, BS-02);
    _006 illegal_rejection x behavioral_index_delete_001 (legal closure:
        existing / never-indexed / already-deleted / dotted-path field names
        + wait/timeout query params).
    type_coercion / search_correctness: NO applicable surface on index+delete
    (path-param-only face - field_name is a URL path segment with no JSON
    body to confuse; no vector query parameter exists) - honestly reported,
    not fabricated (G10). Filter semantics IS applicable indirectly via the
    state constraint's data-untouched promise (see _003). HNSW score-order
    oracles are deliberately avoided (by-design non-determinism, threat
    model G3) - all row-set oracles here use deterministic scroll/count.
Oracle: DELETE of an EXISTING index on a self-created collection returns
  HTTP 200 with envelope result an object (index+delete response_shape
  declares result:object, result.status:string, result.operation_id:
  integer|null) AND the field DISAPPEARS from the describe readback
  result.payload_schema.<field> (200-without-removal = Type4_
  StateLogicViolation silent no-op - the 200 promises the index was deleted;
  R16/R21 standing lesson: persistence judged via describe readback,
  payload_schema is the collections+get response_shape grid key,
  payload_indexes honored only as measured conflict-zone fallback, spec
  wins); DELETE of a NON-EXISTENT index (both a never-known field name and
  a payload-present-but-never-indexed field) on the EXISTING collection
  returns HTTP 200 each time, twice without flapping (idempotent success is
  the assertion's own promise, threat-model by-design list agrees - any 4xx
  there = Type1_IllegalRejection, any 5xx-with-live-/healthz = Type3);
  DELETE of any index on a never-created unique-prefix collection name
  returns HTTP 404 exactly, twice (200 = Type1_IllegalSuccess phantom
  success; non-404 non-200 = Type4); a control create+delete after all
  rejection legs is 200 again (404s are name-scoped, not face wreckage);
  5xx with healthy /healthz = Type3_RuntimeFailure; transport/setup
  failures never produce defect conclusions (G8).

Constraint anchor qdrant_behavioral_index_delete_001 (explicit, endpoint
level):
  description: "returns 200 ok; a missing collection returns 404"
  (source_url https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index,
  doc_version 1.18.x (versioned v-1-18-x api-reference), expected_responses
  {200: ok, 404: not found}).

Legs:
  leg 1 positive-existing - PUT keyword index on field cat (wait=true,
      verified echoed), then DELETE it -> HTTP 200 + result object + field
      gone from describe payload_schema (the "200 ok" answer promises the
      index actually left);
  leg 2 negative-nonexistent-index - DELETE ghost_field (never existed
      anywhere) and DELETE note (payload key present on points, never
      indexed) on the EXISTING collection -> HTTP 200 each, repeated twice
      (idempotent success branch; G9: both non-existent flavors must be
      dispositioned identically by the assertion's "(existing or not)"
      wording);
  leg 3 negative-missing-collection - DELETE cat on a never-created
      unique-prefix name -> HTTP 404 exactly, twice (stability, no
      flapping);
  leg 4 control - create+delete a second field index after all legs ->
      200 again, and the leg-1 field stays absent (state stable).

URL derivation: raw_knowledge api_endpoints[index+delete].url is
  /collections/{collection_name}/index/{field_name}; all calls go through
  runtime PATHS keys (delete_index DELETE /collections/{name}/index/
  {field_name}, create_index PUT /collections/{name}/index,
  describe_collection GET /collections/{name}, healthz GET /healthz) -
  literal path strings forbidden. R15-R21 lessons honored: constraint_id
  bare IDs; envelope result.<field> extraction; unique per-script
  prefixes; inline /healthz probes; safe_request forwards
  body/path_params/query_params/timeout exactly; wait is a query
  parameter in string form ("true", not boolean True - v34 R1 S1 lesson);
  cleanup drops only collections this script created.
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

PFX = "sidl01" + uuid.uuid4().hex[:6]
DIM = 4
COL = PFX + "_live"
NEVER = PFX + "_never_" + uuid.uuid4().hex[:6]
assert NEVER != COL
FIELD_1 = "cat"         # leg-1 existing-index field
FIELD_2 = "score_tag"   # leg-4 control field
GHOST = "ghost_field"   # never existed anywhere (leg 2a)
PAYLOAD_ONLY = "note"   # payload key on points, never indexed (leg 2b)


def safe_request(method, path_key, body=None, path_params=None, query_params=None,
                 timeout=30):
    """All HTTP through the runtime (DB-neutral path_key); forwards body/
    path_params/query_params/timeout exactly - standing lesson."""
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
    """G8 three-outcome isolation: transport failures and 5xx never produce
    defect conclusions without a liveness re-check."""
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


def put_index(name, field, schema):
    """PUT index+create {field_name, field_schema} with wait=true (query
    parameter, string form) so the describe readback is deterministic."""
    body = {"field_name": field, "field_schema": schema}
    st, raw = safe_request("PUT", "create_index", body=body,
                           path_params={"name": name},
                           query_params={"wait": "true"}, timeout=30)
    print(f"[PUT index {name}/{field}] schema={json.dumps(schema)} -> status={st} raw={str(raw)[:300]}")
    return st, raw


def delete_index(name, field, tag=""):
    """DELETE index+delete /collections/{name}/index/{field} with wait=true."""
    st, raw = safe_request("DELETE", "delete_index", path_params={"name": name, "field_name": field},
                           query_params={"wait": "true"}, timeout=30)
    print(f"[DELETE index{(' ' + tag) if tag else ''} {name}/{field}] -> status={st} raw={str(raw)[:300]}")
    return st, raw


def describe_index_container(name):
    """GET describe -> (status, payload_schema_dict_or_None, fallback_dict_or_None).
    payload_schema is the collections+get response_shape grid key;
    payload_indexes honored only as measured conflict-zone fallback."""
    st, raw = safe_request("GET", "describe_collection", path_params={"name": name},
                           timeout=30)
    if st != 200:
        return st, None, None
    body = jload(raw)
    res = body.get("result") if isinstance(body, dict) else None
    if not isinstance(res, dict):
        return st, None, None
    ps = res.get("payload_schema") if isinstance(res.get("payload_schema"), dict) else None
    pi = res.get("payload_indexes") if isinstance(res.get("payload_indexes"), dict) else None
    return st, ps, pi


def field_in_index_container(name, field):
    """True if field is echoed in the describe payload index container."""
    st, ps, pi = describe_index_container(name)
    if st != 200:
        script_error(f"describe {name} failed: status={st}")
    for container in (ps, pi):
        if isinstance(container, dict) and field in container:
            return True
    return False


def upsert_points(name, points):
    st, raw = safe_request("PUT", "upsert_points", body={"points": points},
                           path_params={"name": name},
                           query_params={"wait": "true"}, timeout=30)
    print(f"[upsert {len(points)} pts -> {name}] status={st} raw={str(raw)[:200]}")
    return st, raw


def check_200_envelope(st, raw, label):
    """200 branch: envelope result must be an object per index+delete
    response_shape (result:object, result.status:string,
    result.operation_id:integer|null)."""
    if st != 200:
        return False
    body = jload(raw)
    res = body.get("result") if isinstance(body, dict) else None
    if not isinstance(res, dict):
        defect("Type4_StateLogicViolation",
               f"{label}: 200 body envelope result is not an object: {str(raw)[:300]!r} "
               f"(index+delete response_shape declares result:object, "
               f"result.status:string, result.operation_id:integer|null)")
    print(f"[{label} envelope] result.status={res.get('status')!r} "
          f"result.operation_id={res.get('operation_id')!r} (measured)")
    return True


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception as e:
        print(f"cleanup warning (drop {COL}): {e}")
    try:
        rt.drop_collection(NEVER)
    except Exception as e:
        print(f"cleanup warning (drop {NEVER}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[assertion quote] expected_behavior: 'index deletion (existing or "
          "not) returns HTTP 200; missing collection returns 404'")
    try:
        # ---- setup premise: one prefix-owned collection with data + a real index ----
        ok, err = rt.setup_default(COL, dim=DIM, metric="Cosine")
        if not ok:
            script_error(f"premise create {COL} failed: {err}")
        pts = [{"id": i, "vector": [0.1 * i, 0.2, 0.3, 0.4],
                "payload": {"cat": "A" if i % 2 else "B", "score": 10 * i, "note": f"n{i}"}}
               for i in range(1, 4)]
        st, raw = upsert_points(COL, pts)
        transport_guard("setup upsert", st, raw)
        if st not in (200, 201):
            script_error(f"setup upsert into {COL} failed: {st} {str(raw)[:200]}")
        st, raw = put_index(COL, FIELD_1, "keyword")
        transport_guard("setup index create", st, raw)
        if st != 200 or not field_in_index_container(COL, FIELD_1):
            script_error(f"premise: index on {FIELD_1} not echoed in describe (status={st})")
        print(f"[setup] {COL} ready with keyword index on {FIELD_1!r}")

        # ---- leg 1: positive-existing - 200 + result object + field really removed ----
        st, raw = delete_index(COL, FIELD_1, "leg1 existing")
        transport_guard("leg1 delete existing index", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"DELETE of the EXISTING index {FIELD_1!r} on {COL} answered HTTP {st}; "
                   f"assertion positive branch promises 200 ('index deletion ... returns "
                   f"HTTP 200'): {str(raw)[:300]!r}")
        check_200_envelope(st, raw, "leg1")
        if field_in_index_container(COL, FIELD_1):
            defect("Type4_StateLogicViolation",
                   f"DELETE of index {FIELD_1!r} answered 200 result:object but the field is "
                   f"STILL echoed in the describe payload index container - 200-without-"
                   f"removal silent no-op family (the '200 ok' promise of a deleted index "
                   f"is not kept; R16/R21 describe-readback lesson)")
        print("[leg1] existing index deleted: 200 + envelope + describe echo gone")

        # ---- leg 2: negative-nonexistent-index - 200 both flavors, twice ----
        for field, flavor in ((GHOST, "never-known field"),
                              (PAYLOAD_ONLY, "payload-present-but-never-indexed field")):
            for rep in (1, 2):
                st, raw = delete_index(COL, field, f"leg2 {flavor} rep{rep}")
                transport_guard(f"leg2 {field} rep {rep}", st, raw)
                if st != 200:
                    defect("Type1_IllegalRejection" if 400 <= st < 500 else "Type4_StateLogicViolation",
                           f"DELETE of NON-EXISTENT index {field!r} ({flavor}) on EXISTING "
                           f"collection {COL} answered HTTP {st}; assertion promises idempotent "
                           f"200 for 'index deletion (existing or not)': {str(raw)[:300]!r}")
                check_200_envelope(st, raw, f"leg2 {field} rep{rep}")
        print("[leg2] non-existent index deletes (ghost + payload-only flavors): 200 x4")

        # ---- leg 3: negative-missing-collection - 404 exactly, twice ----
        for rep in (1, 2):
            st, raw = delete_index(NEVER, FIELD_1, f"leg3 missing-collection rep{rep}")
            transport_guard(f"leg3 attempt {rep}", st, raw)
            if st == 200:
                defect("Type1_IllegalSuccess",
                       f"DELETE index on never-created collection name {NEVER} answered "
                       f"HTTP 200; assertion negative branch promises 404 for a missing "
                       f"collection (phantom success): {str(raw)[:300]!r}")
            if st != 404:
                defect("Type4_StateLogicViolation",
                       f"DELETE index on never-created collection name {NEVER} answered "
                       f"HTTP {st}; assertion negative branch promises exactly 404: "
                       f"{str(raw)[:300]!r}")
        print(f"[leg3] missing collection {NEVER}: 404 twice without flapping")

        # ---- leg 4: control - create+delete still 200 after rejection legs ----
        st, raw = put_index(COL, FIELD_2, "keyword")
        transport_guard("leg4 control index create", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"control: legal PUT index on existing {COL} answered {st} after the "
                   f"rejection legs; rejections must be name-scoped: {str(raw)[:300]!r}")
        st, raw = delete_index(COL, FIELD_2, "leg4 control")
        transport_guard("leg4 control delete", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"control: DELETE of existing index {FIELD_2!r} answered {st} after the "
                   f"rejection legs; rejections must be name-scoped: {str(raw)[:300]!r}")
        check_200_envelope(st, raw, "leg4")
        if field_in_index_container(COL, FIELD_2):
            defect("Type4_StateLogicViolation",
                   f"control leg: index {FIELD_2!r} still echoed after a 200 delete - "
                   f"removal must stay effective after the 404 legs")
        if field_in_index_container(COL, FIELD_1):
            defect("Type4_StateLogicViolation",
                   f"leg-1 field {FIELD_1!r} re-appeared in the index container after the "
                   f"later legs - index removal state must be stable")
        # points must have survived every delete leg (full data-untouched probe
        # is _002's slot; here a one-count sanity so this script's legs cannot
        # pass on a wiped collection)
        st, raw = safe_request("POST", "count", body={"exact": True},
                               path_params={"name": COL}, timeout=30)
        transport_guard("leg4 count sanity", st, raw)
        cnt = jload(raw).get("result", {}).get("count") if isinstance(jload(raw), dict) else None
        print(f"[leg4 sanity] count={cnt} (setup upserted 3)")
        if cnt != 3:
            defect("Type4_StateLogicViolation",
                   f"points_count={cnt!r} after index-delete legs (expected 3) - deletes "
                   f"touched point data, see the data-untouched constraint probe _002")

        print(f"OK: existing-index delete -> 200 + envelope + removal echo; non-existent "
              f"index deletes (both flavors) -> 200 x4 idempotent; never-created "
              f"{NEVER} -> 404 twice; control create+delete -> 200 with clean state")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
