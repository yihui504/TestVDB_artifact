#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_index_create_002
# strategy: type_coercion
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust - field_schema is a
#   PayloadSchemaParams oneOf(string-enum | object); a lenient deserializer
#   could coerce int/bool/array shapes into the enum branch or silently
#   default an empty object, exactly like the vectors={} family)
"""
Attack: type_coercion (S4) x constraints::qdrant_type_index_create_001 on
  index+create (chunk_index+create unit
  constraints::qdrant_type_index_create_001 - assertion: "field_schema IN
  {keyword, integer, float, geo, text, bool, datetime, uuid}; text tokenizer
  IN {prefix, whitespace, word, multilingual}", evidence_tier=explicit,
  endpoint level; request_required_paths = [field_name, field_schema.type]
  so the object branch must carry field_schema.type).
  R21 chunk_index+create semantic coverage map (G10 reconciliation):
    _001 behavioral_contract x behavioral_index_create_001;
    _002 type_coercion x type_index_create_001 (this script - field_schema
        wire shapes + tokenizer enum violations, BS-01);
    _003 illegal_rejection x type_index_create_001 (legal enum closure);
    _004 diagnosis_quality x type_index_create_001 (Type-2 rubric, BS-02);
    _005 metamorphic x type_index_create_001 (encoding equivalence, G9).
    search_correctness / filter_semantics: NO applicable surface on
    index+create - honestly reported (G10).
Oracle: with the control legal keyword create answered 200 (face healthy,
  G4 ground), each hostile field_schema wire shape - integer 123, boolean
  true, array ["keyword"], empty object {} (violates the required path
  field_schema.type), {"type":"varchar"} unknown enum member, {"type":123}
  int-shaped type, JSON null, and {"type":"text","tokenizer":"ngram"}
  (tokenizer outside [prefix, whitespace, word, multilingual]) - is refused
  with a 4xx client error (any 2xx = Type1_IllegalSuccess, a wrongly-typed
  or out-of-enum schema silently coerced/accepted, BS-01); after all legs
  the describe readback result.payload_schema contains ONLY the control
  field - a hostile field name appearing there = Type4_StateLogicViolation
  phantom index state (200-worthiness judged via describe readback, R16/R20
  lesson; payload_indexes only as measured conflict-zone fallback, spec
  wins); 5xx with healthy /healthz = Type3_RuntimeFailure; transport/setup
  failures = SCRIPT_ERROR (G8).

Rationale (G6 mutation-justified): field_schema is the one parameter whose
  wire type the constraint pins (enum-string or object with type), so
  shape-crossing values are the maximal breakers: {} is the classic
  empty-object hole (serde untagged oneOf can default an empty object into
  the object branch and null-fill the type), 123/true/["keyword"] cross the
  JSON-type boundary into the enum branch, {"type":"varchar"} stays
  well-typed JSON but leaves the value domain, and the ngram leg isolates
  the NESTED enum (tokenizer) from the outer one - a server that validates
  only the outer enum would 200 it.
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

PFX = "sic02" + uuid.uuid4().hex[:6]
DIM = 4
COL = PFX + "_live"
CTRL_FIELD = "ctrl_ok"
# (leg tag, field name, hostile field_schema value, violation class)
HOSTILE_LEGS = [
    ("int-shaped field_schema",        "h_int",   123,                       "JSON-type crossing into the enum branch"),
    ("bool-shaped field_schema",       "h_bool",  True,                      "JSON-type crossing into the enum branch"),
    ("array-shaped field_schema",      "h_arr",   ["keyword"],               "JSON-type crossing into the enum branch"),
    ("empty-object field_schema",      "h_empty", {},                        "missing required path field_schema.type (request_required_paths)"),
    ("object unknown enum member",     "h_varchar", {"type": "varchar"},     "value outside PayloadSchemaType enum"),
    ("object int-shaped type",         "h_intype", {"type": 123},            "JSON-type crossing inside the object branch"),
    ("null field_schema",              "h_null",  None,                      "required parameter nulled"),
    ("tokenizer outside enum",         "h_ngram", {"type": "text", "tokenizer": "ngram"}, "nested tokenizer enum violation (legit outer type)"),
]


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
    body = {"field_name": field, "field_schema": schema}
    st, raw = safe_request("PUT", "create_index", body=body,
                           path_params={"name": name},
                           query_params={"wait": "true"}, timeout=30)
    print(f"[PUT index {name}/{field}] schema={json.dumps(schema)} -> status={st} raw={str(raw)[:400]}")
    return st, raw


def describe_container(name):
    """GET describe -> (result.payload_schema dict, used_key, err). Spec grid
    key first; payload_indexes only as measured conflict-zone fallback."""
    st, raw = safe_request("GET", "describe_collection", path_params={"name": name},
                           timeout=30)
    if st != 200:
        return None, None, f"describe failed: st={st} raw={str(raw)[:200]}"
    body = jload(raw)
    res = body.get("result") if isinstance(body, dict) else None
    if not isinstance(res, dict):
        return None, None, f"describe result not an object: {str(raw)[:200]}"
    for key in ("payload_schema", "payload_indexes"):
        v = res.get(key)
        if isinstance(v, dict):
            return v, key, None
    return None, None, f"no payload index container in describe result keys={sorted(res.keys())[:24]}"


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception as e:
        print(f"cleanup warning (drop {COL}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[constraint quote] 'field_schema IN {keyword, integer, float, geo, "
          "text, bool, datetime, uuid}; text tokenizer IN {prefix, whitespace, "
          "word, multilingual}'")
    try:
        ok, err = rt.setup_default(COL, dim=DIM, metric="Cosine")
        if not ok:
            script_error(f"premise create {COL} failed: {err}")
        print(f"[setup] created {COL} (dim={DIM})")

        # ---- control gate: the face accepts a legal schema (G4 ground) ----
        st, raw = put_index(COL, CTRL_FIELD, "keyword")
        transport_guard("control legal create", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"control: legal field_schema 'keyword' answered HTTP {st} on "
                   f"{COL}; without a healthy positive face the hostile legs "
                   f"below would be meaningless: {str(raw)[:300]!r}")

        # ---- hostile legs: each must be refused 4xx ----
        accepted_fields = []
        for tag, field, schema, vclass in HOSTILE_LEGS:
            st, raw = put_index(COL, field, schema)
            transport_guard(f"hostile {tag}", st, raw)
            if 200 <= st < 300:
                defect("Type1_IllegalSuccess",
                       f"{tag} ({vclass}) answered HTTP {st}; constraint "
                       f"qdrant_type_index_create_001 pins field_schema to the "
                       f"PayloadSchemaType enum (+tokenizer enum) and "
                       f"request_required_paths requires field_schema.type - a "
                       f"2xx means the wrongly-typed schema was silently coerced/"
                       f"accepted (BS-01): {str(raw)[:300]!r}")
            if not (400 <= st < 500):
                defect("Type4_StateLogicViolation",
                       f"{tag} ({vclass}) answered HTTP {st}; a 4xx client error "
                       f"is required for a schema outside the declared type "
                       f"domain: {str(raw)[:300]!r}")
            # measured: did the refused leg nevertheless leak state?
            cont, used_key, cerr = describe_container(COL)
            if cerr:
                script_error(f"readback after leg '{tag}' failed: {cerr}")
            if field in cont:
                accepted_fields.append(field)
                print(f"[hostile {tag}] NOTE: field {field!r} present in {used_key} "
                      f"despite the {st} refusal - phantom state evidence")

        # ---- phantom-state check: only the control field may exist ----
        cont, used_key, cerr = describe_container(COL)
        if cerr:
            script_error(f"final readback failed: {cerr}")
        hostile_names = [f for _, f, _, _ in HOSTILE_LEGS]
        leaked = [f for f in cont if f in hostile_names]
        print(f"[final readback] {used_key} fields={sorted(cont.keys())}")
        if leaked:
            defect("Type4_StateLogicViolation",
                   f"refused hostile schemas left phantom index state: fields "
                   f"{leaked} present in describe {used_key} although every "
                   f"hostile leg was answered 4xx - state and response disagree")
        if CTRL_FIELD not in cont:
            defect("Type4_StateLogicViolation",
                   f"control field {CTRL_FIELD!r} missing from describe {used_key} "
                   f"after the hostile legs - the control index must persist")

        print(f"OK: control legal create 200; all {len(HOSTILE_LEGS)} hostile "
              f"field_schema shapes refused 4xx; describe {used_key} holds only "
              f"the control field (no phantom state)")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
