#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_index_create_003
# strategy: illegal_rejection
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the published enum domain is
#   verified positively: every documented member must actually be accepted
#   on the live runtime, not merely listed in the reference)
"""
Attack: illegal_rejection (S3, legal-closure sweep) x
  constraints::qdrant_type_index_create_001 on index+create
  (chunk_index+create unit constraints::qdrant_type_index_create_001 -
  assertion: "field_schema IN {keyword, integer, float, geo, text, bool,
  datetime, uuid}; text tokenizer IN {prefix, whitespace, word,
  multilingual}", evidence_tier=explicit, endpoint level).
  Not testing whether illegal input is accepted (that is _002) but whether
  EVERY documented-legal enum member is wrongly rejected - a drift between
  the published enum domain and the server's accepted set (BS-05).
  R21 chunk_index+create semantic coverage map (G10 reconciliation):
    _001 behavioral_contract x behavioral_index_create_001;
    _002 type_coercion x type_index_create_001 (BS-01 hostile shapes);
    _003 illegal_rejection x type_index_create_001 (this script - full
        legal closure of both enums);
    _004 diagnosis_quality x type_index_create_001 (Type-2 rubric, BS-02);
    _005 metamorphic x type_index_create_001 (encoding equivalence, G9).
    search_correctness / filter_semantics: NO applicable surface on
    index+create - honestly reported (G10).
Oracle: every legal PayloadSchemaType member (keyword, integer, float, geo,
  text, bool, datetime, uuid) sent as the string encoding, and every legal
  text tokenizer (prefix, whitespace, word, multilingual) sent inside
  {"type":"text","tokenizer":X}, is accepted with HTTP 200 on a
  self-created collection and ECHOES in the describe readback
  result.payload_schema with the matching data_type (a non-200 on any legal
  member = Type1_IllegalRejection - the documented domain is refused; a 200
  with wrong/missing data_type echo = Type4_StateLogicViolation
  200-without-echo family, R16/R20 describe-readback lesson; the tokenizer
  value is compared when the describe entry exposes a tokenizer field and
  otherwise reported as not-observable - collections+get response_shape
  only grids result.payload_schema:object, deeper keys are measured-only);
  final describe holds exactly 12 index fields (8 types + 4 tokenizers);
  5xx with healthy /healthz = Type3_RuntimeFailure; transport/setup
  failures = SCRIPT_ERROR (G8).

Rationale (G4 boundary closure): a type constraint is only falsifiable
  against its positive closure - if even one documented enum member is
  rejected, the constraint's domain claim is already violated without any
  hostile input; datetime/uuid are the newest members (most likely to be
  missing from a stale server validator) and multilingual the rarest
  tokenizer, so the sweep covers the drift-prone tail, not just keyword.
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

PFX = "sic03" + uuid.uuid4().hex[:6]
DIM = 4
COL = PFX + "_live"
# full legal closure of both documented enums (constraint verbatim members)
TYPE_MEMBERS = ["keyword", "integer", "float", "geo", "text", "bool",
                "datetime", "uuid"]
TOKENIZER_MEMBERS = ["prefix", "whitespace", "word", "multilingual"]
EXPECTED_COUNT = len(TYPE_MEMBERS) + len(TOKENIZER_MEMBERS)


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


def describe_index_entry(name, field):
    """GET describe -> result.payload_schema[field] (spec grid key;
    payload_indexes only as measured conflict-zone fallback). Returns
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
    return st, None, None, f"field {field!r} not echoed in any describe payload index container"


def entry_data_type(entry):
    if isinstance(entry, dict):
        if "data_type" in entry:
            return entry.get("data_type")
        if "type" in entry:
            return entry.get("type")
    return None


def entry_echoed_tokenizer(entry):
    """Measured-only: if the describe entry exposes a tokenizer anywhere,
    return its value; else None (not-observable is not a defect - the
    response_shape grid stops at result.payload_schema:object)."""
    if not isinstance(entry, dict):
        return None
    if "tokenizer" in entry:
        return entry.get("tokenizer")
    params = entry.get("params")
    if isinstance(params, dict) and "tokenizer" in params:
        return params.get("tokenizer")
    return None


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

        # ---- closure sweep 1: all 8 PayloadSchemaType members (string form) ----
        for t in TYPE_MEMBERS:
            field = f"t_{t}"
            st, raw = put_index(COL, field, t)
            transport_guard(f"closure type {t}", st, raw)
            if st != 200:
                defect("Type1_IllegalRejection",
                       f"legal enum member field_schema={t!r} answered HTTP {st}; "
                       f"constraint qdrant_type_index_create_001 documents {t} "
                       f"inside the accepted domain - the documented domain is "
                       f"refused (BS-05 drift): {str(raw)[:300]!r}")
            _, used_key, entry, derr = describe_index_entry(COL, field)
            if derr:
                script_error(f"closure readback failed for {field}: {derr}")
            dt = entry_data_type(entry)
            print(f"[closure type {t}] echo under {used_key}: "
                  f"data_type={dt!r} entry={json.dumps(entry)[:200]}")
            if dt != t:
                defect("Type4_StateLogicViolation",
                       f"field_schema={t!r} answered 200 but the describe readback "
                       f"echoes data_type={dt!r} under {used_key} - "
                       f"200-without-echo/wrong-echo family (R16/R20 lesson)")

        # ---- closure sweep 2: all 4 text tokenizers (object form) ----
        for tok in TOKENIZER_MEMBERS:
            field = f"g_{tok}"
            schema = {"type": "text", "tokenizer": tok}
            st, raw = put_index(COL, field, schema)
            transport_guard(f"closure tokenizer {tok}", st, raw)
            if st != 200:
                defect("Type1_IllegalRejection",
                       f"legal text tokenizer {tok!r} inside "
                       f"{{'type':'text'}} answered HTTP {st}; constraint "
                       f"documents tokenizer IN {{prefix, whitespace, word, "
                       f"multilingual}}: {str(raw)[:300]!r}")
            _, used_key, entry, derr = describe_index_entry(COL, field)
            if derr:
                script_error(f"closure readback failed for {field}: {derr}")
            dt = entry_data_type(entry)
            etok = entry_echoed_tokenizer(entry)
            print(f"[closure tokenizer {tok}] echo under {used_key}: "
                  f"data_type={dt!r} echoed_tokenizer={etok!r} "
                  f"entry={json.dumps(entry)[:200]}")
            if dt != "text":
                defect("Type4_StateLogicViolation",
                       f"tokenizer leg {tok!r} answered 200 but the readback echoes "
                       f"data_type={dt!r} (expected 'text') under {used_key}")
            if etok is not None and etok != tok:
                defect("Type4_StateLogicViolation",
                       f"tokenizer leg sent {tok!r} but the readback echoes "
                       f"tokenizer={etok!r} - persisted schema disagrees with the "
                       f"accepted request")
            if etok is None:
                print(f"[closure tokenizer {tok}] note: tokenizer value not "
                      f"observable in the describe entry (grid stops at "
                      f"result.payload_schema:object) - measured-only, no oracle")

        # ---- final count control: exactly 12 index fields on a fresh collection ----
        st, raw = safe_request("GET", "describe_collection",
                               path_params={"name": COL}, timeout=30)
        transport_guard("final describe", st, raw)
        body = jload(raw)
        res = body.get("result") if isinstance(body, dict) else None
        cont = None
        used_key = None
        if isinstance(res, dict):
            for key in ("payload_schema", "payload_indexes"):
                v = res.get(key)
                if isinstance(v, dict):
                    cont, used_key = v, key
                    break
        if cont is None:
            script_error(f"final describe carries no payload index container: "
                         f"{str(raw)[:200]}")
        n = len(cont)
        print(f"[final describe] {used_key} field count={n} "
              f"fields={sorted(cont.keys())}")
        if n != EXPECTED_COUNT:
            defect("Type4_StateLogicViolation",
                   f"after {EXPECTED_COUNT} accepted (200) index creates the "
                   f"describe {used_key} holds {n} fields - accepted-but-vanished "
                   f"or duplicated state")

        print(f"OK: all {len(TYPE_MEMBERS)} PayloadSchemaType members and all "
              f"{len(TOKENIZER_MEMBERS)} text tokenizers accepted with 200 and "
              f"correct data_type echo; final {used_key} count = {EXPECTED_COUNT}")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
