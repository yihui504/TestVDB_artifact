#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_index_create_005
# strategy: metamorphic
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - PayloadSchemaParams is documented
#   as one wire encoding family with two legal spellings; the live runtime
#   must disposition both spellings of the SAME semantic value identically)
"""
Attack: metamorphic (S6) x constraints::qdrant_type_index_create_001 on
  index+create (chunk_index+create unit
  constraints::qdrant_type_index_create_001 - assertion: "field_schema IN
  {keyword, integer, float, geo, text, bool, datetime, uuid}; text
  tokenizer IN {prefix, whitespace, word, multilingual}"; the parameter is
  typed PayloadSchemaParams, whose two branches (bare enum string vs
  {"type": <enum>} object) are documented spellings of the same semantic
  value).
  R21 chunk_index+create semantic coverage map (G10 reconciliation):
    _001 behavioral_contract x behavioral_index_create_001;
    _002 type_coercion x type_index_create_001 (BS-01 hostile shapes);
    _003 illegal_rejection x type_index_create_001 (legal enum closure);
    _004 diagnosis_quality x type_index_create_001 (Type-2 rubric, BS-02);
    _005 metamorphic x type_index_create_001 (this script - string vs
        object encoding equivalence + idempotent duplicate re-create, G9).
    search_correctness / filter_semantics: NO applicable surface on
    index+create - honestly reported (G10).
Oracle: on two identically-constructed self-created collections, the same
  keyword field_schema in its two legal encodings - string "keyword" (COL_S)
  vs object {"type":"keyword"} (COL_O) on the same field name - BOTH answer
  HTTP 200 and BOTH echo data_type "keyword" in describe
  result.payload_schema.<field> (asymmetric disposition across the two
  spellings of one parameter family = Type4_StateLogicViolation, G9
  consistent disposition; a divergent echoed data_type = Type4;
  200-without-echo = Type4 silent-ignore family, R16/R20 describe-readback
  lesson; payload_indexes only as measured conflict-zone fallback, spec
  wins); re-PUT of the byte-identical object-form body on COL_O answers
  200 again with the echo unchanged and exactly ONE entry for the field -
  the behavioral assertion qdrant_behavioral_index_create_001 promises 200
  for a valid schema PUT with no duplicate carve-out (a non-200 on the
  identical duplicate, a mutated data_type, or a duplicated/changed entry
  count = Type4 duplication-instability); 5xx with healthy /healthz =
  Type3_RuntimeFailure; transport/setup failures = SCRIPT_ERROR (G8).

Rationale (G6 mutation-justified): the two mutations chosen are the ones
  most likely to break a oneOf deserializer - (a) re-encoding the same
  semantic value through the OTHER branch of the oneOf exposes any
  branch-asymmetric validation (validators frequently check only the
  string branch), and (b) byte-identical duplication probes the
  create-or-update decision path where an upsert-vs-conflict fork commonly
  returns 409 or silently re-registers a second index entry.
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

PFX = "sic05" + uuid.uuid4().hex[:6]
DIM = 4
COL_S = PFX + "_enc_str"   # string-encoding twin
COL_O = PFX + "_enc_obj"   # object-encoding twin
FIELD = "meta_field"       # SAME field name on both twins
SCHEMA_STR = "keyword"
SCHEMA_OBJ = {"type": "keyword"}


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


def put_index(name, field, schema, tag):
    body = {"field_name": field, "field_schema": schema}
    st, raw = safe_request("PUT", "create_index", body=body,
                           path_params={"name": name},
                           query_params={"wait": "true"}, timeout=30)
    print(f"[{tag}] PUT index {name}/{field} schema={json.dumps(schema)} -> "
          f"status={st} raw={str(raw)[:400]}")
    return st, raw


def describe_index_entry(name, field):
    """GET describe -> result.payload_schema[field] (collections+get
    response_shape grid key; payload_indexes only as a measured
    conflict-zone fallback). Returns (used_key, entry_or_None, err)."""
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
        if isinstance(v, dict) and field in v:
            return key, v[field], None
    return None, None, f"field {field!r} not echoed in any describe payload index container"


def describe_field_count(name, field):
    """count of dict keys under the payload index container (spec key first,
    measured fallback) - used by the duplication-mutation stability check."""
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
            return key, len(v), None
    return None, None, f"no payload index container in describe result keys={sorted(res.keys())[:24]}"


def entry_data_type(entry):
    if isinstance(entry, dict):
        if "data_type" in entry:
            return entry.get("data_type")
        if "type" in entry:
            return entry.get("type")
    return None


def cleanup():
    for col in (COL_S, COL_O):
        try:
            rt.drop_collection(col)
        except Exception as e:
            print(f"cleanup warning (drop {col}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[constraint quote] 'field_schema IN {keyword, integer, float, geo, "
          "text, bool, datetime, uuid}' - PayloadSchemaParams oneOf(string, "
          "object-with-type); same semantic value, two documented spellings")
    try:
        # ---- identical twins ----
        for col in (COL_S, COL_O):
            ok, err = rt.setup_default(col, dim=DIM, metric="Cosine")
            if not ok:
                script_error(f"premise create {col} failed: {err}")
        print(f"[setup] created twins {COL_S} + {COL_O} (dim={DIM})")

        # ---- mutation 1: same value, the OTHER oneOf branch ----
        st_s, raw_s = put_index(COL_S, FIELD, SCHEMA_STR, "enc-string")
        transport_guard("string-encoding create", st_s, raw_s)
        st_o, raw_o = put_index(COL_O, FIELD, SCHEMA_OBJ, "enc-object")
        transport_guard("object-encoding create", st_o, raw_o)
        if st_s != 200 and st_o != 200:
            script_error(f"both encodings refused (string={st_s}, object={st_o}) "
                         f"- the face rejects the whole domain; nothing to "
                         f"compare (see _003 closure sweep)")
        if (st_s == 200) != (st_o == 200):
            defect("Type4_StateLogicViolation",
                   f"asymmetric disposition of the two legal spellings of the "
                   f"same keyword field_schema: string form -> {st_s}, object "
                   f"form -> {st_o}; G9 requires one parameter family to be "
                   f"dispositioned consistently across its interface faces "
                   f"(string={str(raw_s)[:200]!r} object={str(raw_o)[:200]!r})")
        if st_s != 200:
            defect("Type1_IllegalRejection",
                   f"string spelling field_schema='keyword' answered {st_s}; "
                   f"constraint documents it in the accepted domain: "
                   f"{str(raw_s)[:300]!r}")
        if st_o != 200:
            defect("Type1_IllegalRejection",
                   f"object spelling field_schema={{'type':'keyword'}} answered "
                   f"{st_o}; constraint documents keyword in the accepted "
                   f"domain: {str(raw_o)[:300]!r}")

        # ---- echo equivalence: identical persisted schema ----
        key_s, entry_s, err_s = describe_index_entry(COL_S, FIELD)
        key_o, entry_o, err_o = describe_index_entry(COL_O, FIELD)
        if err_s:
            script_error(f"string-twin echo readback failed: {err_s}")
        if err_o:
            script_error(f"object-twin echo readback failed: {err_o}")
        dt_s = entry_data_type(entry_s)
        dt_o = entry_data_type(entry_o)
        print(f"[echo] string twin {key_s} data_type={dt_s!r} entry={json.dumps(entry_s)[:200]}")
        print(f"[echo] object twin {key_o} data_type={dt_o!r} entry={json.dumps(entry_o)[:200]}")
        if dt_s != "keyword" or dt_o != "keyword":
            defect("Type4_StateLogicViolation",
                   f"200-without-echo/wrong-echo: string twin data_type={dt_s!r}, "
                   f"object twin data_type={dt_o!r} (both sent keyword; R16/R20 "
                   f"describe-readback lesson)")
        if dt_s != dt_o:
            defect("Type4_StateLogicViolation",
                   f"the two spellings of one semantic value persisted "
                   f"differently: data_type {dt_s!r} (string form) vs {dt_o!r} "
                   f"(object form) - encoding must not change persisted schema "
                   f"semantics")

        # ---- mutation 2: byte-identical duplicate re-create (idempotence) ----
        st_d, raw_d = put_index(COL_O, FIELD, SCHEMA_OBJ, "dup-recreate")
        transport_guard("duplicate re-create", st_d, raw_d)
        if st_d != 200:
            defect("Type4_StateLogicViolation",
                   f"byte-identical re-PUT of the accepted object-form schema "
                   f"answered {st_d}; assertion "
                   f"qdrant_behavioral_index_create_001 promises 200 for a "
                   f"valid schema PUT with no duplicate carve-out - the same "
                   f"body was 200 one call earlier (inconsistent disposition, "
                   f"G9): {str(raw_d)[:300]!r}")
        key_d, entry_d, err_d = describe_index_entry(COL_O, FIELD)
        if err_d:
            script_error(f"duplicate-leg echo readback failed: {err_d}")
        dt_d = entry_data_type(entry_d)
        print(f"[dup echo] {key_d} data_type={dt_d!r} entry={json.dumps(entry_d)[:200]}")
        if dt_d != "keyword":
            defect("Type4_StateLogicViolation",
                   f"duplicate re-create mutated the persisted schema: "
                   f"data_type={dt_d!r} (was 'keyword') - duplication must be a "
                   f"semantic no-op (G6)")
        key_c, count_c, err_c = describe_field_count(COL_O, FIELD)
        if err_c:
            script_error(f"duplicate-leg count readback failed: {err_c}")
        print(f"[dup count] {key_c} field count={count_c} (expected 1)")
        if count_c != 1:
            defect("Type4_StateLogicViolation",
                   f"after the duplicate re-create the {key_c} container holds "
                   f"{count_c} fields (expected exactly 1) - duplicated or "
                   f"spilled index registration")

        print(f"OK: string and object spellings of keyword both 200 with "
              f"identical data_type echo ({dt_s!r}/{dt_o!r}); byte-identical "
              f"re-PUT 200 with stable echo and a single field entry")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
