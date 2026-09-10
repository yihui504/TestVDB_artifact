#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_index_delete_005
# strategy: diagnosis_quality
# endpoint: index+delete
# constraint_ids: qdrant_behavioral_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - a bare 404 with an empty or
#   context-free body names neither the missing collection nor what the
#   caller should check; the refusal is correct but undiagnosable, the
#   classic low-priority edge-case message this rubric scores)
"""
Attack: diagnosis_quality (S2, Type-2 focused) x
  assertions::qdrant_behavioral_index_delete_001 on index+delete
  (chunk_index+delete unit assertions::qdrant_behavioral_index_delete_001 -
  expected_behavior: "index deletion (existing or not) returns HTTP 200;
  missing collection returns 404", evidence_tier=explicit, endpoint level).
  The endpoint's ONLY documented error face is the 404 (expected_responses
  {200: ok, 404: not found}), so the quality of the 404 body is the
  user-facing diagnostic contract: it must at minimum NAME the missing
  resource (BS-02).
  R22 chunk_index+delete semantic coverage map: see _001 (this script =
  slot 5 of 6: diagnosis_quality x behavioral_index_delete_001).
Oracle: with the control leg proving the face healthy (create+delete of a
  real index on a self-created collection -> 200 with result:object
  envelope), DELETE of an index on EACH of two distinct never-created
  collection names answers exactly HTTP 404 (any 2xx = Type1_
  IllegalSuccess phantom success and outranks the rubric; any non-404
  4xx = Type4_StateLogicViolation branch violation; 5xx with healthy
  /healthz = Type3_RuntimeFailure), and EACH 404 body scores >= 1/3 on
  the Type-2 rubric: c1 resource named (the actual collection-name
  literal or the word 'collection'), c2 format/existence hint ('not
  found'/'exist'/'must be'/'valid' family), c3 actionable suggestion
  ('use'/'create'/'check'/'specify' family); a 404 body scoring 0/3 -
  names neither the missing collection nor any existence statement -
  = Type2_PoorDiagnostics (BS-02). Rubric mechanics per the S2 helper:
  the body may be a JSON dict (json.dumps it) or a non-JSON string -
  both are scanned by str().lower(); error-body FIELD NAMES are
  implementation detail per the threat-model by-design list, so the
  rubric scans the whole raw text and asserts no structural shape.
  A localization note is printed (does the body echo the offending
  name, and is leg 2's body distinct from leg 1's) - measured, not
  scored. Transport/setup failures never produce defect conclusions
  (G8).

Constraint anchor qdrant_behavioral_index_delete_001 (explicit, endpoint
level):
  description: "returns 200 ok; a missing collection returns 404"
  (source_url https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index,
  doc_version 1.18.x (versioned v-1-18-x api-reference)).

Legs:
  leg 0 control - create collection + keyword index, DELETE it -> 200
      (the delete face is healthy; premise for everything below);
  leg 1 missing-collection A - DELETE index on never-created name N1
      -> exactly 404, rubric-scored with leg-specific tokens;
  leg 2 missing-collection B - DELETE index on never-created name N2
      (distinct name AND distinct field) -> exactly 404, rubric-scored;
      localization measured (N2 echoed? body differs from leg 1?).

URL derivation: raw_knowledge api_endpoints[index+delete].url is
  /collections/{collection_name}/index/{field_name}; runtime PATHS keys
  only (delete_index/create_index/describe_collection/upsert_points/
  healthz). R15-R21 lessons honored: bare constraint IDs; unique prefix;
  wait string-form query param; cleanup drops only script-owned
  collections (both the live one and, defensively, the never-names).
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

PFX = "sidl05" + uuid.uuid4().hex[:6]
DIM = 4
COL = PFX + "_live"
NEVER_A = PFX + "_never_a_" + uuid.uuid4().hex[:6]
NEVER_B = PFX + "_never_b_" + uuid.uuid4().hex[:6]
assert NEVER_A != COL and NEVER_B != COL and NEVER_A != NEVER_B
CTRL_FIELD = "cat"
FIELD_A = "field_alpha"
FIELD_B = "field_beta"

FORMAT_HINTS = ["not found", "doesn't exist", "does not exist", "no collection",
                "not exist", "exist", "must be", "expected", "should be", "valid",
                "missing", "unknown"]
ACTION_HINTS = ["use", "create", "check", "verify", "specify", "provide", "try",
                "ensure", "correct", "change"]


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
    print(f"[DELETE index{(' ' + tag) if tag else ''} {name}/{field}] -> status={st} raw={str(raw)[:400]}")
    return st, raw


def check_error_quality(status, body, raw_text, name_tokens):
    """Type-2 diagnosis quality rubric (S2 helper contract):
    c1 parameter/resource named (1pt) - any of the leg-specific tokens
        (the actual never-created collection name literal, or the word
        'collection' / 'field' family for the path resource);
    c2 format/existence hint (1pt) - FORMAT_HINTS family;
    c3 actionable suggestion (1pt) - ACTION_HINTS family.
    Scans str(body-or-raw).lower(); body may be a dict (json.dumps) or a
    non-JSON string. Error-body field names are NOT asserted (threat-model
    by-design: they are implementation detail)."""
    text = json.dumps(body).lower() if isinstance(body, dict) else str(body if body is not None else raw_text).lower()
    if not text or text == "{}":
        text = str(raw_text).lower()
    score = []
    c1 = any(t.lower() in text for t in name_tokens)
    c2 = any(h in text for h in FORMAT_HINTS)
    c3 = any(h in text for h in ACTION_HINTS)
    score = (1 if c1 else 0) + (1 if c2 else 0) + (1 if c3 else 0)
    print(f"    rubric: c1 resource-named={c1} c2 format/existence-hint={c2} "
          f"c3 actionable={c3} -> score {score}/3 (text={text[:200]!r})")
    return score


def cleanup():
    for n in (COL, NEVER_A, NEVER_B):
        try:
            rt.drop_collection(n)
        except Exception as e:
            print(f"cleanup warning (drop {n}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[assertion quote] expected_behavior: 'index deletion (existing or not) "
          "returns HTTP 200; missing collection returns 404'")
    try:
        # ---- leg 0: control - the delete face is healthy on a real collection ----
        ok, err = rt.setup_default(COL, dim=DIM, metric="Cosine")
        if not ok:
            script_error(f"premise create {COL} failed: {err}")
        st, raw = safe_request("PUT", "create_index",
                               body={"field_name": CTRL_FIELD, "field_schema": "keyword"},
                               path_params={"name": COL},
                               query_params={"wait": "true"}, timeout=30)
        transport_guard("leg0 control create", st, raw)
        if st != 200:
            script_error(f"leg0 control create failed: {st} {str(raw)[:200]}")
        st, raw = delete_index(COL, CTRL_FIELD, "leg0 control")
        transport_guard("leg0 control delete", st, raw)
        if st != 200:
            script_error(f"leg0 control delete failed: {st} {str(raw)[:200]}")
        body = jload(raw)
        res = body.get("result") if isinstance(body, dict) else None
        if not isinstance(res, dict):
            defect("Type4_StateLogicViolation",
                   f"control delete: 200 envelope result is not an object: {str(raw)[:300]!r} "
                   f"(index+delete response_shape declares result:object)")
        print("[leg0] control create+delete -> 200 result:object (face healthy)")

        # ---- legs 1-2: the 404 face on two distinct never-created names ----
        bodies = {}
        for leg, (never, field) in enumerate(((NEVER_A, FIELD_A), (NEVER_B, FIELD_B)), start=1):
            st, raw = delete_index(never, field, f"leg{leg} missing-collection")
            transport_guard(f"leg{leg} missing collection", st, raw)
            if 200 <= st < 300:
                defect("Type1_IllegalSuccess",
                       f"DELETE index on never-created collection {never} answered HTTP "
                       f"{st}; assertion negative branch promises exactly 404 (phantom "
                       f"success outranks the rubric): {str(raw)[:300]!r}")
            if st != 404:
                defect("Type4_StateLogicViolation",
                       f"DELETE index on never-created collection {never} answered HTTP "
                       f"{st}; assertion negative branch promises exactly 404: "
                       f"{str(raw)[:300]!r}")
            body = jload(raw)
            text = json.dumps(body) if isinstance(body, dict) else str(raw)
            bodies[leg] = text
            print(f"[leg{leg}] 404 confirmed for {never}; scoring diagnostics")
            tokens = [never, "collection", "collection_name", field]
            score = check_error_quality(st, body, raw, tokens)
            if score == 0:
                defect("Type2_PoorDiagnostics",
                       f"404 body for never-created collection {never} names neither the "
                       f"missing resource nor any existence statement (rubric 0/3, BS-02): "
                       f"{str(raw)[:400]!r}")
            # localization measurements (not scored)
            print(f"    localization: body echoes the offending name={never in text} "
                  f"field mentioned={field in text}")

        same_body = bodies[1] == bodies[2]
        print(f"[localization] leg1 body == leg2 body: {same_body} (distinct names "
              f"should ideally produce distinct/localized bodies - measured, not "
              f"scored; both scored >= 1/3 above)")

        print(f"OK: control delete 200; both never-created collections ({NEVER_A}, "
              f"{NEVER_B}) -> exactly 404 with diagnosable bodies (rubric >= 1/3 each)")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
