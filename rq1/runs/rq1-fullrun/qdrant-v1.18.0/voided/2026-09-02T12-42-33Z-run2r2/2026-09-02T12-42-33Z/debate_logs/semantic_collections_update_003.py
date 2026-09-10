#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_update_003
# strategy: diagnosis_quality
# endpoint: collections+update
# constraint_ids: qdrant_range_collections_update_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - the update-time
#   optimizers_config diff bounds live on one face but are rejected by two
#   diagnostic classes: value-validation below-min/out-of-range values answer
#   422 messages that name the full field path (e.g. "...deleted_threshold:
#   value 1.5 invalid, must be from 0.0 to 1.0"), while negative integers on
#   the same face answer anonymous serde 400 messages ("invalid value: integer
#   `-5`, expected usize at line 1 column N") that never name the offending
#   parameter. Both classes belong to the SAME OptimizersConfigDiff parameter
#   family of constraint qdrant_range_collections_update_002 - a developer
#   cannot locate which field a 400-class refusal is about without
#   byte-counting their own request. The gradient is the blindspot.)
"""
Attack: diagnosis_quality (S2, Type-2 rubric; G4 positive/negative pairing on
  one constraint; G9 within-family consistency) x
  qdrant_range_collections_update_002 on collections+update
  (chunk_collections+update unit constraints::qdrant_range_collections_update_002 -
  assertion: "optimizers_config (diff) bounds: deleted_threshold within [0, 1];
  vacuum_min_vector_number minimum 100; max_segment_size minimum 1 KB;
  memmap_threshold minimum 0; indexing_threshold minimum 0 KB",
  evidence_tier=explicit, endpoint level). All bounds cross-checked against
  the versioned v-1-18-x OpenAPI component schema BEFORE writing: each field's
  published minimum/maximum matches the constraint text (deleted_threshold
  min 0 max 1; vacuum_min_vector_number min 100; max_segment_size min 1;
  memmap_threshold min 0; indexing_threshold min 0) - spec wins, no conflict
  zone. Positive closure legs (the minima / the closed-interval endpoints
  themselves must be ACCEPTED) are the G4 ground; persistence echo is checked
  where the applied value is default-distinguishable in the describe readback
  (deleted_threshold 0.0/1.0 vs default 0.2; vacuum_min_vector_number 100 vs
  default 1000; max_segment_size 1 vs default null; indexing_threshold 0 vs
  default 10000 - readback key optimizer_config per the collections+get
  response_shape grid).
  R17 reconciliation: range_collections_update_002 is owned here; boundary
  lane sweeps the outer value space. Each violation PATCH is a separate
  request so a refusal is attributable to exactly one parameter.
Oracle: the documented in-family closure values are accepted by PATCH with
  HTTP 200 and envelope result===true (deleted_threshold=0.0 AND =1.0 - both
  endpoints of the closed [0,1] interval - plus vacuum_min_vector_number=100,
  max_segment_size=1, memmap_threshold=0, indexing_threshold=0; any 4xx on a
  closure-legal diff = Type1_IllegalRejection of documented-legal input);
  default-distinguishable closure values echo in the describe readback
  (deleted_threshold 0.0/1.0, vacuum 100, max_segment_size 1, indexing_
  threshold 0; echo mismatch = Type4_StateLogicViolation); each
  bound-violating value (deleted_threshold=1.5 and -0.1 outside [0,1],
  vacuum_min_vector_number=99, max_segment_size=0, memmap_threshold=-5,
  indexing_threshold=-1) is refused with a 4xx client error (any 2xx =
  Type1_IllegalSuccess - documented bounds accepted-away) and no refusal
  message scores 0/3 on the Type-2 rubric (c1 offending parameter path named
  / c2 format-or-range statement / c3 actionable hint; 0/3 = Type2_PoorDiag-
  nostics); per-leg rubric scores printed; the collection stays describable
  200 after all legs; transport/setup failure with healthy /healthz =
  SCRIPT_ERROR, 5xx with healthy /healthz = Type3_RuntimeFailure (G8).

Constraint anchor qdrant_range_collections_update_002 (explicit, endpoint):
  description: "optimizer config numeric bounds (update diff):
  deleted_threshold in [0, 1], vacuum_min_vector_number minimum 100,
  max_segment_size minimum 1 (KB), memmap_threshold minimum 0,
  indexing_threshold minimum 0 (KB)"
  assertion: "optimizers_config (diff) bounds: deleted_threshold within
  [0, 1]; vacuum_min_vector_number minimum 100; max_segment_size minimum 1
  KB; memmap_threshold minimum 0; indexing_threshold minimum 0 KB"
  (source_url https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection,
  doc_version 1.18.x (versioned v-1-18-x api-reference)).
"""
import os
import sys
import json
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

PFX = "scu03" + uuid.uuid4().hex[:6]
COL = PFX + "_opt"
DIM = 4

# closure legs: documented minima + both endpoints of the closed [0,1]
# interval. Each PATCH is a separate request (attribution).
CLOSURE_LEGS = [
    ("deleted_threshold=0.0 (interval lower endpoint)",
     {"optimizers_config": {"deleted_threshold": 0.0}}, "deleted_threshold", 0.0),
    ("deleted_threshold=1.0 (interval upper endpoint)",
     {"optimizers_config": {"deleted_threshold": 1.0}}, "deleted_threshold", 1.0),
    ("vacuum_min_vector_number=100 (minimum 100)",
     {"optimizers_config": {"vacuum_min_vector_number": 100}},
     "vacuum_min_vector_number", 100),
    ("max_segment_size=1 (minimum 1)",
     {"optimizers_config": {"max_segment_size": 1}}, "max_segment_size", 1),
    ("memmap_threshold=0 (minimum 0)",
     {"optimizers_config": {"memmap_threshold": 0}}, "memmap_threshold", 0),
    ("indexing_threshold=0 (minimum 0)",
     {"optimizers_config": {"indexing_threshold": 0}}, "indexing_threshold", 0),
]
# echo expectations: (readback_key, expected_value) for values distinguishable
# from the v1.18 defaults (deleted_threshold default 0.2, vacuum default 1000,
# max_segment_size default null, indexing_threshold default 10000;
# memmap_threshold default null and 0 is its documented legal minimum - echo
# recorded as a note only because null-vs-0 readback rendering is measured).
ECHO_EXPECT = {
    "deleted_threshold": (0.0, 1.0),   # two separate legs -> read back each time
    "vacuum_min_vector_number": 100,
    "max_segment_size": 1,
    "indexing_threshold": 0,
}
VIOLATION_LEGS = [
    ("deleted_threshold=1.5 (above max 1.0)", {"optimizers_config": {"deleted_threshold": 1.5}},
     "optimizers_config.deleted_threshold", "deleted_threshold"),
    ("deleted_threshold=-0.1 (below min 0.0)", {"optimizers_config": {"deleted_threshold": -0.1}},
     "optimizers_config.deleted_threshold", "deleted_threshold"),
    ("vacuum_min_vector_number=99 (below min 100)", {"optimizers_config": {"vacuum_min_vector_number": 99}},
     "optimizers_config.vacuum_min_vector_number", "vacuum_min_vector_number"),
    ("max_segment_size=0 (below min 1)", {"optimizers_config": {"max_segment_size": 0}},
     "optimizers_config.max_segment_size", "max_segment_size"),
    ("memmap_threshold=-5 (below min 0)", {"optimizers_config": {"memmap_threshold": -5}},
     "optimizers_config.memmap_threshold", "memmap_threshold"),
    ("indexing_threshold=-1 (below min 0)", {"optimizers_config": {"indexing_threshold": -1}},
     "optimizers_config.indexing_threshold", "indexing_threshold"),
]

FORMAT_HINTS = ["must be", "expected", "should be", "valid", "range", "minimum",
                "at least", "or larger", "from 0.0 to", "0.0 to 1.0", "usize",
                "u32", "u64", "integer", "invalid", "between"]
ACTION_HINTS = ["use", "provide", "specify", "set", "change", "correct", "try",
                "larger"]


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


def read_optimizer_field(name, key):
    """GET describe -> result.config.optimizer_config.<key> (readback key is
    optimizer_config, the collections+get response_shape grid key)."""
    st, raw = safe_request("GET", "describe_collection", path_params={"name": name},
                           timeout=30)
    if st != 200:
        return None, None, f"describe failed: st={st} raw={str(raw)[:200]}"
    body = jload(raw)
    res = body.get("result") if isinstance(body, dict) else None
    cfg = (res or {}).get("config") if isinstance(res, dict) else None
    opt = (cfg or {}).get("optimizer_config") if isinstance(cfg, dict) else None
    if not isinstance(opt, dict):
        return st, None, f"config.optimizer_config missing: {str(cfg)[:300]}"
    return st, opt.get(key), None


def rubric_score(raw, param_tokens):
    low = str(raw).lower()
    c1 = any(t.lower() in low for t in param_tokens)
    c2 = any(h in low for h in FORMAT_HINTS)
    c3 = any(a in low for a in ACTION_HINTS)
    return (int(c1) + int(c2) + int(c3)), {"c1_param_named": c1, "c2_format_range": c2,
                                           "c3_actionable": c3}


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception as e:
        print(f"cleanup warning (drop {COL}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[assertion quote] 'optimizers_config (diff) bounds: deleted_threshold "
          "within [0, 1]; vacuum_min_vector_number minimum 100; "
          "max_segment_size minimum 1 KB; memmap_threshold minimum 0; "
          "indexing_threshold minimum 0 KB'")
    try:
        ok, err = rt.setup_default(COL, dim=DIM, metric="Cosine")
        if not ok:
            script_error(f"premise create {COL} failed: {err}")
        print(f"[setup] created {COL} (dim={DIM})")

        # ---- closure legs: minima + closed-interval endpoints accepted ----
        for tag, body, param, value in CLOSURE_LEGS:
            st, raw = safe_request("PATCH", "update_collection", body=body,
                                   path_params={"name": COL}, timeout=30)
            print(f"[closure {tag}] body={json.dumps(body)} -> status={st} raw={str(raw)[:300]}")
            transport_guard(f"closure {tag}", st, raw)
            if st != 200:
                defect("Type1_IllegalRejection",
                       f"closure-legal diff {json.dumps(body)} answered HTTP {st}; "
                       f"constraint qdrant_range_collections_update_002 documents "
                       f"this value as inside the bound: {str(raw)[:300]!r}")
            b = jload(raw)
            if b.get("result") is not True:
                defect("Type4_StateLogicViolation",
                       f"200 envelope result not true on closure leg {tag}: {str(raw)[:300]!r}")
            # echo check for default-distinguishable values
            dst, echo, err = read_optimizer_field(COL, param)
            if err:
                script_error(f"closure {tag} echo readback failed: {err}")
            print(f"[closure {tag}] accepted 200; describe optimizer_config."
                  f"{param}={echo}")
            if param == "deleted_threshold":
                if echo != value:
                    defect("Type4_StateLogicViolation",
                           f"deleted_threshold sent {value} but describe echoes "
                           f"{echo} - update accepted 200 result:true yet the "
                           f"config did not land (silent-ignore family)")
            elif param == "vacuum_min_vector_number" and echo != 100:
                defect("Type4_StateLogicViolation",
                       f"vacuum_min_vector_number sent 100 (documented default "
                       f"1000, so distinguishable) but describe echoes {echo} - "
                       f"200-without-echo silent-ignore")
            elif param == "max_segment_size" and echo != 1:
                defect("Type4_StateLogicViolation",
                       f"max_segment_size sent 1 (default null, distinguishable) "
                       f"but describe echoes {echo} - 200-without-echo")
            elif param == "indexing_threshold" and echo != 0:
                defect("Type4_StateLogicViolation",
                       f"indexing_threshold sent 0 (default 10000, distinguishable) "
                       f"but describe echoes {echo} - 200-without-echo")

        # ---- violation legs: bound-crossing values refused 4xx + rubric ----
        worst = 0
        for tag, body, path_tok, name_tok in VIOLATION_LEGS:
            st, raw = safe_request("PATCH", "update_collection", body=body,
                                   path_params={"name": COL}, timeout=30)
            print(f"[violation {tag}] body={json.dumps(body)} -> status={st} raw={str(raw)[:400]}")
            transport_guard(f"violation {tag}", st, raw)
            if 200 <= st < 300:
                defect("Type1_IllegalSuccess",
                       f"bound-violating diff {json.dumps(body)} answered HTTP {st}; "
                       f"constraint documents the bound this value crosses: "
                       f"{str(raw)[:300]!r}")
            if st not in (400, 422):
                defect("Type4_StateLogicViolation",
                       f"bound-violating diff {json.dumps(body)} answered HTTP {st}; "
                       f"expected a 4xx client error (400/422): {str(raw)[:300]!r}")
            score, details = rubric_score(raw, [path_tok, name_tok])
            print(f"[violation {tag}] refused {st}; rubric={score}/3 {json.dumps(details)}")
            if score == 0:
                defect("Type2_PoorDiagnostics",
                       f"refusal body for {json.dumps(body)} scores 0/3 on the "
                       f"Type-2 rubric - names neither the offending parameter "
                       f"({path_tok}) nor a format/range statement: "
                       f"{str(raw)[:400]!r}")
            worst = max(worst, score)

        # ---- control: describe healthy after all legs ----
        st, raw = safe_request("GET", "describe_collection", path_params={"name": COL},
                               timeout=30)
        print(f"[control describe {COL}] status={st} raw={str(raw)[:300]}")
        transport_guard("control describe", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"control describe on {COL} answered {st} after the closure/"
                   f"violation legs: {str(raw)[:300]!r}")

        print(f"OK: closure values accepted 6/6 with echo where default-"
              f"distinguishable; all bound-violating values refused 4xx; worst "
              f"rubric score {worst}/3 (claim threshold 0/3)")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
