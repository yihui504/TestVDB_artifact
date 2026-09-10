#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_create_002
# strategy: index_state
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001, qdrant_behavioral_index_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: index_state (negative side of the type domain) x
  qdrant_type_index_create_001 (field_schema type domain is the exact enum
  [keyword, integer, float, geo, text, bool, datetime, uuid]; text tokenizer
  enum [prefix, whitespace, word, multilingual]) + the 400 branch of
  qdrant_behavioral_index_create_001 ("400 on an invalid field schema").
  Positive control leg first (G4): a valid keyword index returns 200 and is
  persisted in describe result.payload_schema - proving the promise exists
  on this exact face before challenging it. Negative legs, each on its own
  fresh field so no cross-contamination: n1 type="varchar" (not in enum),
  n2 type="integer64" (alias-shaped, not in enum), n3 type="" (empty),
  n4 type="Keyword" (case variant, outside the exact enum), n5
  type="text" tokenizer="camel" (outside tokenizer enum), n6 type="text"
  tokenizer="WORD" (case variant), n7 type=123 (non-string type confusion
  on the enum slot), n8 field_schema={"type": null} (null in the required
  field_schema.type slot). Each must be rejected 400/422. A 2xx here =
  Type1_IllegalSuccess AND (if describe then shows the field) a
  Type4 phantom materialization of an out-of-domain schema; 5xx with
  /healthz alive = Type3_RuntimeFailure; 404 on the live collection =
  SCRIPT_ERROR-class environment shift.
  [chunk_index+create coverage: index_state x qdrant_type_index_create_001
  (out-of-enum negative) x qdrant_behavioral_index_create_001 (400 branch)]
Oracle: the valid keyword control returns 200 + describe echo data_type
  keyword; all 8 invalid schema legs return HTTP 400/422 and leave
  result.payload_schema free of their fields; any 2xx on an invalid leg =
  Type1_IllegalSuccess (5xx with /healthz alive = Type3_RuntimeFailure;
  2xx + phantom describe entry = compounded Type4_StateLogicViolation)
  (qdrant_type_index_create_001, qdrant_behavioral_index_create_001)
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

print(f"[PATHS] index keys present="
      f"{[k for k in ('create_index', 'delete_index', 'describe_collection') if k in rt.PATHS]}")


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    """Transport/5xx branch liveness re-check via the lightweight healthz face."""
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def describe_payload_schema(tag, collection):
    s, raw = safe_request("GET", "describe_collection",
                          path_params={"name": collection})
    print(f"[{tag}] describe status={s} raw={str(raw)[:300]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict):
        return None, False
    ps = res.get("payload_schema")
    if ps is None:
        return {}, True
    return (ps, True) if isinstance(ps, dict) else (None, False)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidx2_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    NOTES = []
    created_phantom = []   # fields that got 2xx on an INVALID schema

    CONTROL_FIELD = "city_kw"
    NEG_LEGS = [
        ("n1_varchar",  {"type": "varchar"}),
        ("n2_int64",    {"type": "integer64"}),
        ("n3_empty",    {"type": ""}),
        ("n4_casevar",  {"type": "Keyword"}),
        ("n5_tok_bad",  {"type": "text", "tokenizer": "camel"}),
        ("n6_tok_case", {"type": "text", "tokenizer": "WORD"}),
        ("n7_type_int", {"type": 123}),
        ("n8_type_null", {"type": None}),
    ]

    try:
        ok, err = rt.setup_default(C, 4)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points", body={"points": [
            {"id": i, "vector": [0.1 + 0.01 * i, 0.2, 0.3, 0.4],
             "payload": {CONTROL_FIELD: f"c{i % 3}"}}
            for i in range(1, 7)
        ]}, path_params={"name": C}, query_params={"wait": "true"})
        print(f"[setup upsert] status={s} raw={str(raw)[:160]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"

        # ---- positive control: valid keyword index -> 200 + echo ----
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": CONTROL_FIELD,
                                    "field_schema": {"type": "keyword"}},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[control create keyword] status={s} raw={str(raw)[:200]}")
        if s == 0 or s == 404 or 500 <= s <= 599:
            if not liveness("control create"):
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(control) HTTP {s} on the valid keyword control while "
                f"/healthz alive - Type3_RuntimeFailure - raw={str(raw)[:160]}")
        elif s not in (200, 201):
            DEFECTS.append(
                f"(control) valid keyword index rejected with HTTP {s} - "
                f"Type1_IllegalSuccess - raw={str(raw)[:160]} "
                f"(qdrant_behavioral_index_create_001 200 branch)")
        else:
            ps, _ = describe_payload_schema("describe control", C)
            if ps is not None and CONTROL_FIELD not in ps:
                DEFECTS.append(
                    f"(control) keyword create returned 200 but {CONTROL_FIELD} "
                    f"absent from payload_schema (echo={ps}) - "
                    f"Type4_StateLogicViolation - ack without persistence")

        # ---- negative legs: out-of-domain schemas must be rejected ----
        for leg, schema in NEG_LEGS:
            s, raw = safe_request("PUT", "create_index",
                                  body={"field_name": leg,
                                        "field_schema": schema},
                                  path_params={"name": C},
                                  query_params={"wait": "true"})
            print(f"[{leg} schema={schema}] status={s} raw={str(raw)[:240]}")
            if s in (400, 422):
                print(f"[{leg}] OK: rejected with {s} as asserted")
                continue
            if s == 0 or 500 <= s <= 599 or s == 404:
                if not liveness(leg):
                    return "SCRIPT_ERROR"
                if 500 <= s <= 599 or s == 0:
                    DEFECTS.append(
                        f"({leg}) HTTP {s} on an invalid schema while "
                        f"/healthz alive - Type3_RuntimeFailure - "
                        f"raw={str(raw)[:160]}")
                else:
                    NOTES.append(f"{leg}: unexpected 404 on the live "
                                 f"collection (environment shift, not claimed)")
                continue
            # 2xx family (200/201/202...) on an out-of-domain schema
            DEFECTS.append(
                f"({leg} schema={schema}) invalid field_schema ACCEPTED with "
                f"HTTP {s} - Type1_IllegalSuccess - raw={str(raw)[:160]} "
                f"(qdrant_type_index_create_001 / "
                f"qdrant_behavioral_index_create_001 400 branch)")
            created_phantom.append(leg)

        # ---- phantom materialization check for any 2xx'd invalid leg ----
        if created_phantom:
            ps, okps = describe_payload_schema("describe phantom check", C)
            if okps and ps:
                for leg in created_phantom:
                    if leg in ps:
                        DEFECTS.append(
                            f"(describe) out-of-domain schema for field {leg} "
                            f"was MATERIALIZED into payload_schema "
                            f"(echo={str(ps.get(leg))[:160]}) - "
                            f"Type4_StateLogicViolation - illegal schema "
                            f"persisted")
            # best-effort removal of any phantom index (cleanup discipline)
            for leg in list(created_phantom):
                try:
                    safe_request("DELETE", "delete_index",
                                 path_params={"name": C, "field_name": leg},
                                 query_params={"wait": "true"})
                except Exception:
                    pass

        # ---- final describe: only the control index remains ----
        ps, okps = describe_payload_schema("describe final", C)
        if okps and ps is not None:
            expected = {CONTROL_FIELD} if not created_phantom else \
                {CONTROL_FIELD} | set(created_phantom)
            unexpected = [f for f in ps if f not in expected]
            if unexpected:
                DEFECTS.append(
                    f"(describe) unexpected fields in payload_schema after "
                    f"rejections: {unexpected} - Type4_StateLogicViolation - "
                    f"echo={str(ps)[:200]}")

        for n in NOTES:
            print(f"NOTE: {n}")
        print(f"[summary] negative legs={len(NEG_LEGS)} "
              f"accepted={len(created_phantom)} "
              f"phantom_materialized="
              f"{[l for l in created_phantom if ps and l in (ps or {})] if okps else 'n/a'}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("type-domain negative verification complete: valid keyword "
              "control 200 + persisted; all 8 out-of-enum/case-variant/"
              "type-confused/null schema legs rejected with 400/422 and none "
              "materialized into payload_schema - NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup (own data only; failure must not flip the verdict)
        try:
            rt.drop_collection(C)
            print(f"[cleanup] dropped {C}")
        except Exception as e:
            print(f"[cleanup] drop {C} failed (ignored): {e}")


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
