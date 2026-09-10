#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_index_create_004
# strategy: diagnosis_quality
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - a bare 'internal error' or
#   enum-dump refusal for an invalid field_schema names neither the
#   offending parameter nor the accepted domain, the classic low-priority
#   edge-case message this rubric scores)
"""
Attack: diagnosis_quality (S2, Type-2 focused) x
  constraints::qdrant_type_index_create_001 on index+create
  (chunk_index+create unit constraints::qdrant_type_index_create_001 -
  assertion: "field_schema IN {keyword, integer, float, geo, text, bool,
  datetime, uuid}; text tokenizer IN {prefix, whitespace, word,
  multilingual}", evidence_tier=explicit, endpoint level). The endpoint is
  refused-oriented (index+create expected_responses document 400 'bad
  request / validation error'), so the quality of the refusal body is the
  user-facing contract: it must at minimum NAME the offending parameter
  (BS-02).
  R21 chunk_index+create semantic coverage map (G10 reconciliation):
    _001 behavioral_contract x behavioral_index_create_001;
    _002 type_coercion x type_index_create_001 (BS-01 hostile shapes);
    _003 illegal_rejection x type_index_create_001 (legal enum closure);
    _004 diagnosis_quality x type_index_create_001 (this script - Type-2
        rubric on four distinct violation classes, BS-02);
    _005 metamorphic x type_index_create_001 (encoding equivalence, G9).
    search_correctness / filter_semantics: NO applicable surface on
    index+create - honestly reported (G10).
Oracle: with the control legal keyword create answered 200 (face healthy),
  the four violation legs - field_schema "varchar" (unknown enum member,
  string branch), field_schema 123 (JSON-type violation), field_schema {}
  (missing the required field_schema.type path), and
  {"type":"text","tokenizer":"ngram"} (nested tokenizer enum violation) -
  are EACH first refused with a 4xx client error (any 2xx = Type1_
  IllegalSuccess and outranks the rubric), and each refusal body then
  scores >= 1/3 on the Type-2 rubric: c1 parameter named via leg-specific
  tokens (field_schema/type for the schema legs, tokenizer for the
  tokenizer leg), c2 format/range hint (enum members, 'must be'/'valid'/
  'expected' family), c3 actionable suggestion ('use'/'provide'/'specify'
  family); score 0/3 - names neither the offending parameter nor any
  format statement - = Type2_PoorDiagnostics (BS-02); 5xx with healthy
  /healthz = Type3_RuntimeFailure; transport/setup failures = SCRIPT_ERROR
  (G8). Rubric note: body may be a dict (json.dumps it) or a non-JSON
  string - both are checked by str().lower() per the S2 helper contract.

Rationale (G5/G7): each leg is a DIFFERENT violation class so the rubric
  result localizes the negligence - a server that names the parameter for
  the value-domain error but answers a bare 400 (empty body) for the
  empty-object leg is a different diagnostic gap than one that fails all
  four; the tokenizer leg isolates whether the NESTED parameter is named,
  which pure outer-enum validators routinely get wrong.
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

PFX = "sic04" + uuid.uuid4().hex[:6]
DIM = 4
COL = PFX + "_live"
CTRL_FIELD = "ctrl_ok"
# (leg tag, field, hostile schema, violation class, c1 parameter tokens)
VIOLATION_LEGS = [
    ("unknown enum member (string branch)", "d_varchar", "varchar",
     "value outside PayloadSchemaType enum", ["field_schema", "field schema", "schema"]),
    ("int-shaped field_schema", "d_int", 123,
     "JSON-type violation", ["field_schema", "field schema", "schema"]),
    ("empty object (missing field_schema.type)", "d_empty", {},
     "missing required path field_schema.type", ["field_schema", "field schema", "type", "schema"]),
    ("tokenizer outside enum", "d_ngram", {"type": "text", "tokenizer": "ngram"},
     "nested tokenizer enum violation", ["tokenizer"]),
]
FORMAT_HINTS = ["must be", "expected", "should be", "valid", "range", "type",
                "enum", "variant", "unknown", "one of", "keyword", "integer",
                "float", "geo", "text", "bool", "datetime", "uuid", "prefix",
                "whitespace", "word", "multilingual", "deserializ", "parse",
                "missing", "field"]
ACTION_HINTS = ["use", "provide", "specify", "set", "change", "correct",
                "try", "refer"]


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


def rubric_score(raw, param_tokens):
    """Type-2 diagnosis rubric (S2 helper contract): body may be dict (dump
    it) or non-JSON str; both go through str().lower()."""
    low = json.dumps(raw).lower() if isinstance(raw, dict) else str(raw).lower()
    c1 = any(t.lower() in low for t in param_tokens)
    c2 = any(h in low for h in FORMAT_HINTS)
    c3 = any(a in low for a in ACTION_HINTS)
    return (int(c1) + int(c2) + int(c3)), {"c1_param_named": c1,
                                           "c2_format_range": c2,
                                           "c3_actionable": c3}


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
                   f"{COL}; without a healthy positive face the refusal bodies "
                   f"below are uninterpretable: {str(raw)[:300]!r}")

        # ---- violation legs: refuse 4xx first, then score the refusal body ----
        worst = 0
        for tag, field, schema, vclass, tokens in VIOLATION_LEGS:
            st, raw = put_index(COL, field, schema)
            transport_guard(f"violation {tag}", st, raw)
            if 200 <= st < 300:
                defect("Type1_IllegalSuccess",
                       f"{tag} ({vclass}) answered HTTP {st}; constraint "
                       f"qdrant_type_index_create_001 pins the field_schema/"
                       f"tokenizer domains - a 2xx outranks the rubric: "
                       f"{str(raw)[:300]!r}")
            if not (400 <= st < 500):
                defect("Type4_StateLogicViolation",
                       f"{tag} ({vclass}) answered HTTP {st}; a 4xx client error "
                       f"is required (expected_responses document 400): "
                       f"{str(raw)[:300]!r}")
            score, details = rubric_score(raw, tokens)
            print(f"[violation {tag}] refused {st}; rubric={score}/3 "
                  f"{json.dumps(details)}")
            if score == 0:
                defect("Type2_PoorDiagnostics",
                       f"refusal body for field_schema={json.dumps(schema)} "
                       f"({vclass}) scores 0/3 on the Type-2 rubric - names "
                       f"neither the offending parameter (tokens {tokens}) nor "
                       f"any format/enum statement (BS-02 negligence): "
                       f"{str(raw)[:400]!r}")
            worst = max(worst, score)

        # ---- control: face still healthy after the legs ----
        st, raw = put_index(COL, "ctrl_after", "keyword")
        transport_guard("post-control create", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"post-control: legal keyword create answered {st} after the "
                   f"violation legs; rejections must be body-scoped: "
                   f"{str(raw)[:300]!r}")

        print(f"OK: all 4 violation legs refused 4xx; worst rubric score "
              f"{worst}/3 (claim threshold 0/3); control legs 200 before and "
              f"after")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
