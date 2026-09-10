#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_index_create_001
# strategy: behavioral_contract
# endpoint: index+create
# constraint_ids: qdrant_behavioral_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - API contract verification of the
#   index+create face: the published promise "returns 200 ok; 400 on an
#   invalid field schema; 404 when the collection is missing" is verified
#   against the live v1.18.0 runtime, including the result:object envelope
#   shape and the describe-readback persistence that a "200 ok" answer
#   implicitly promises)
"""
Attack: behavioral_contract (S1, G4 positive/negative pairing, G7 oracle-first)
  x assertions::qdrant_behavioral_index_create_001 on index+create
  (chunk_index+create unit assertions::qdrant_behavioral_index_create_001 -
  expected_behavior: "valid index creation returns HTTP 200; invalid schema
  (e.g. unknown type) returns 400; missing collection returns 404",
  evidence_tier=explicit, endpoint level).
  R21 chunk_index+create semantic coverage map (G10 reconciliation):
    _001 behavioral_contract x behavioral_index_create_001 (this script);
    _002 type_coercion x type_index_create_001 (field_schema wire shapes +
        tokenizer enum violations, BS-01);
    _003 illegal_rejection x type_index_create_001 (legal enum closure: all
        8 PayloadSchemaType members + all 4 text tokenizers);
    _004 diagnosis_quality x type_index_create_001 (Type-2 rubric on the
        rejection bodies, BS-02);
    _005 metamorphic x type_index_create_001 (string vs object encoding
        equivalence + idempotent re-create, G9).
    search_correctness / filter_semantics: NO applicable surface on
    index+create (no vector query and no filter parameter on this face) -
    honestly reported, not fabricated (G10). Illegal-rejection closure of the
    type enum lives in _003; this script's positive legs carry the G4 ground
    for its own negative branches.
Oracle: PUT of a legal keyword field_schema on a self-created collection
  returns HTTP 200 with envelope result an object (index+create
  response_shape declares result:object, result.status:string,
  result.operation_id:integer|null) and the index ECHOES in the describe
  readback result.payload_schema.<field> with data_type keyword
  (200-without-echo = Type4_StateLogicViolation silent-ignore; R16/R20
  standing lesson: probe persistence via describe readback - payload_schema
  is the collections+get response_shape grid key, payload_indexes honored
  only as a measured conflict-zone fallback, spec wins); PUT of the same
  legal body on a never-created unique-prefix name returns HTTP 404 twice
  without flapping (200 on a missing collection = Type1_IllegalSuccess
  phantom success; non-404 non-200 = Type4); an unknown field_schema type
  value is refused with a 4xx client error - the versioned v-1-18-x
  expected_responses document 400 for invalid schema, and any 2xx on the
  invalid schema = Type1_IllegalSuccess per the assertion's own promise
  (a measured 422 remains a client-error refusal and is printed, spec wins
  over the loose '400' wording, D3b-2/R16); the control create after the
  rejection legs is 200 + echo again (rejections are body-scoped, not
  face-level wreckage); 5xx with healthy /healthz = Type3_RuntimeFailure;
  transport/setup failures never produce defect conclusions (G8).

Constraint anchor qdrant_behavioral_index_create_001 (explicit, endpoint
  level):
  description: "returns 200 ok; 400 on an invalid field schema; 404 when the
  collection is missing"
  (source_url https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index,
  doc_version 1.18.x (versioned v-1-18-x api-reference)).

Legs:
  leg 1 positive-valid - PUT {field_name, field_schema:"keyword"} (wait=true)
      on a self-created collection -> HTTP 200 + result object + describe
      payload_schema[field].data_type == "keyword" (the "200 ok" answer
      promises the index landed; echo absence = the silent-ignore family);
  leg 2 negative-missing - the SAME legal body on a never-created
      unique-prefix name -> HTTP 404 exactly, twice (stability, no flapping);
  leg 3 invalid-schema - field_schema "not-a-type" (value outside the
      PayloadSchemaType enum) on the EXISTING collection -> refused 4xx
      (2xx = Type1_IllegalSuccess);
  leg 4 control - a second valid field index after the rejection legs ->
      200 again + echo, and the leg-1 field is still echoed (state stable).

URL derivation: raw_knowledge api_endpoints[index+create].url is
  /collections/{collection_name}/index; all calls go through runtime PATHS
  keys (create_index PUT /collections/{name}/index, describe_collection GET
  /collections/{name}, healthz GET /healthz) - literal path strings
  forbidden. R15-R20 lessons honored: constraint_id bare IDs; envelope
  result.<field> extraction (never fixed index chains); unique per-script
  prefixes; inline /healthz probes; safe_request forwards
  body/path_params/query_params/timeout exactly; wait is a query parameter
  ("true" string form - boolean True would serialize as "True" and be
  rejected by the query parser, v34 R1 S1 lesson); cleanup drops only
  collections this script created.
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

PFX = "sic01" + uuid.uuid4().hex[:6]
DIM = 4
COL = PFX + "_live"
NEVER = PFX + "_never_" + uuid.uuid4().hex[:6]
assert NEVER != COL
FIELD_1 = "cat"        # leg-1 / control-readback field
FIELD_2 = "score_tag"  # leg-4 control field


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
    print(f"[PUT index {name}/{field}] schema={json.dumps(schema)} -> status={st} raw={str(raw)[:400]}")
    return st, raw


def describe_index_entry(name, field):
    """GET describe -> result.payload_schema[field] entry (collections+get
    response_shape grid key). payload_indexes is honored only as a
    measured conflict-zone fallback (spec wins, R16/R20 lesson). Returns
    (status, used_key, entry_or_None, err_or_None)."""
    st, raw = safe_request("GET", "describe_collection", path_params={"name": name},
                           timeout=30)
    if st != 200:
        return st, None, None, f"describe failed: st={st} raw={str(raw)[:200]}"
    body = jload(raw)
    res = body.get("result") if isinstance(body, dict) else None
    if not isinstance(res, dict):
        return st, None, None, f"describe result not an object: {str(raw)[:200]}"
    for key in ("payload_schema", "payload_indexes"):
        v = res.get(key)
        if isinstance(v, dict) and field in v:
            return st, key, v[field], None
    present = sorted(res.keys())
    has_empty_ps = isinstance(res.get("payload_schema"), dict)
    return st, None, None, (f"field {field!r} not echoed in describe payload index "
                            f"container (result keys={present[:24]}, "
                            f"payload_schema-dict={has_empty_ps})")


def entry_data_type(entry):
    """data_type per the PayloadIndexInfo shape; 'type' honored as measured
    alias only."""
    if isinstance(entry, dict):
        if "data_type" in entry:
            return entry.get("data_type")
        if "type" in entry:
            return entry.get("type")
    return None


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception as e:
        print(f"cleanup warning (drop {COL}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[assertion quote] expected_behavior: 'valid index creation returns "
          "HTTP 200; invalid schema (e.g. unknown type) returns 400; missing "
          "collection returns 404'")
    try:
        # ---- setup premise: one prefix-owned collection ----
        ok, err = rt.setup_default(COL, dim=DIM, metric="Cosine")
        if not ok:
            script_error(f"premise create {COL} failed: {err}")
        print(f"[setup] created {COL} (dim={DIM})")

        # ---- leg 1: positive-valid - 200 + result object + echo persistence ----
        st, raw = put_index(COL, FIELD_1, "keyword")
        transport_guard("leg1 legal index create", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"legal PUT index {{field_name:{FIELD_1!r}, field_schema:'keyword'}} "
                   f"on existing collection {COL} answered HTTP {st}; assertion "
                   f"positive branch promises 200: {str(raw)[:300]!r}")
        body = jload(raw)
        res = body.get("result") if isinstance(body, dict) else None
        if not isinstance(res, dict):
            defect("Type4_StateLogicViolation",
                   f"200 body envelope result is not an object: {str(raw)[:300]!r} "
                   f"(index+create response_shape declares result:object, "
                   f"result.status:string)")
        rstatus = res.get("status")
        print(f"[leg1 envelope] result.status={rstatus!r} "
              f"result.operation_id={res.get('operation_id')!r} (measured)")
        st2, used_key, entry, derr = describe_index_entry(COL, FIELD_1)
        if derr:
            script_error(f"leg1 echo readback failed: {derr}")
        dt = entry_data_type(entry)
        print(f"[leg1 echo] describe {used_key}[{FIELD_1!r}] = {json.dumps(entry)} "
              f"(data_type={dt!r}, sent 'keyword')")
        if dt != "keyword":
            defect("Type4_StateLogicViolation",
                   f"valid index create answered 200 result:object but the describe "
                   f"readback shows data_type={dt!r} (sent 'keyword') under "
                   f"{used_key} - 200-without-echo silent-ignore family (R16/R20 "
                   f"lesson: persistence is judged via describe readback); the "
                   f"'200 ok' promise of a landed index is not kept")

        # ---- leg 2: negative-missing - 404 on never-created name, twice ----
        for rep in (1, 2):
            st, raw = put_index(NEVER, FIELD_1, "keyword")
            transport_guard(f"leg2 attempt {rep}", st, raw)
            if st == 200:
                defect("Type1_IllegalSuccess",
                       f"PUT index on never-created collection name {NEVER} answered "
                       f"HTTP 200; assertion negative branch promises 404 for a "
                       f"missing collection (phantom success): {str(raw)[:300]!r}")
            if st != 404:
                defect("Type4_StateLogicViolation",
                       f"PUT index on never-created collection name {NEVER} answered "
                       f"HTTP {st}; assertion negative branch promises exactly 404: "
                       f"{str(raw)[:300]!r}")

        # ---- leg 3: invalid schema - unknown enum value on EXISTING collection ----
        st, raw = put_index(COL, "bogus_field", "not-a-type")
        transport_guard("leg3 invalid schema", st, raw)
        if 200 <= st < 300:
            defect("Type1_IllegalSuccess",
                   f"invalid field_schema 'not-a-type' (outside PayloadSchemaType "
                   f"enum) answered HTTP {st}; assertion promises refusal - '400 on "
                   f"an invalid field schema': {str(raw)[:300]!r}")
        if not (400 <= st < 500):
            defect("Type4_StateLogicViolation",
                   f"invalid field_schema 'not-a-type' answered HTTP {st}; a 4xx "
                   f"client error is required (expected_responses document 400): "
                   f"{str(raw)[:300]!r}")
        print(f"[leg3 note] measured rejection status {st}; expected_responses "
              f"document 400 'bad request / validation error' - any 4xx refusal "
              f"satisfies the assertion's substance (spec wins, R16)")

        # ---- leg 4: control - valid create still 200 + both echoes after rejections ----
        st, raw = put_index(COL, FIELD_2, "keyword")
        transport_guard("leg4 control index create", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"control: legal PUT index on existing {COL} answered {st} after "
                   f"the rejection legs; rejections must be body-scoped: "
                   f"{str(raw)[:300]!r}")
        for f in (FIELD_1, FIELD_2):
            st2, used_key, entry, derr = describe_index_entry(COL, f)
            if derr:
                script_error(f"leg4 echo readback failed for {f}: {derr}")
            if entry_data_type(entry) != "keyword":
                defect("Type4_StateLogicViolation",
                       f"control leg echo lost/unstable for {f}: entry="
                       f"{json.dumps(entry)} - index echo must stay stable across "
                       f"rejection legs")

        print(f"OK: legal index create -> 200 result:object with keyword echo in "
              f"describe (stable across control); never-created {NEVER} -> 404 "
              f"twice without flapping; unknown schema value refused with 4xx as "
              f"documented")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
