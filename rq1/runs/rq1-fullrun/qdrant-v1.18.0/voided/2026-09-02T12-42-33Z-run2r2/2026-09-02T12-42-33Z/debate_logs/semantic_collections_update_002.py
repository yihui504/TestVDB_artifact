#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_update_002
# strategy: diagnosis_quality
# endpoint: collections+update
# constraint_ids: qdrant_range_collections_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - the update-time HnswConfigDiff
#   minima are rejected by two different validation classes on the same face:
#   value-validation below-min rejections (which the v1.18.0 runtime answers
#   with param-naming 422 messages) versus type-format rejections (which the
#   same runtime answers with anonymous serde 400 messages that never name the
#   offending request field). A developer hitting the anonymous class cannot
#   locate which config field is wrong without byte-counting their own request;
#   that diagnostic gradient across ONE parameter family is exactly the
#   negligence this blindspot covers)
"""
Attack: diagnosis_quality (S2, Type-2 rubric; G4 positive-negative pairing on
  one constraint) x qdrant_range_collections_update_001 on collections+update
  (chunk_collections+update unit constraints::qdrant_range_collections_update_001 -
  assertion: "HnswConfigDiff (update): m minimum 0; ef_construct minimum 4;
  full_scan_threshold minimum 10 (KB); payload_m minimum 0", evidence_tier=
  explicit, endpoint level). One fresh prefix-owned collection carries the
  whole family; every PATCH is a separate request so a refusal is attributable
  to exactly one parameter (diagnostics attribution).
  R17 semantic coverage reconciliation (G10): range_collections_update_001 is
  owned here (diagnosis_quality + closure ground); the pure boundary matrix
  (large-value sweeps) lives in the boundary lane. Positive closure legs
  (each documented minimum itself must be ACCEPTED) are the G4 ground - with
  only negative legs the constraint itself could be false (minima may be
  fictional); per-parameter closure uses four separate PATCHes.
Oracle: each of the four documented minima (m=0, ef_construct=4,
  full_scan_threshold=10, payload_m=0) is accepted by PATCH with HTTP 200 and
  envelope result===true (any 4xx on a minimum-value legal diff =
  Type1_IllegalRejection, 5xx with healthy /healthz = Type3_RuntimeFailure);
  each below-minimum value (ef_construct=3, full_scan_threshold=9, m=-1,
  payload_m=-1) is refused with a 4xx client error (400 OR 422 both
  spec-compliant - any 2xx = Type1_IllegalSuccess, the documented minimum is
  accepted-away) and no refusal message scores 0/3 on the Type-2 rubric
  (c1 offending parameter path named / c2 format-or-range statement / c3
  actionable hint; 0/3 = Type2_PoorDiagnostics - a body that names NEITHER
  the field NOR the constraint leaves the developer unable to locate the
  problem); per-leg rubric scores are printed for falsifiability; control
  describe on the collection stays 200 after all legs (config updates are
  body-scoped, no face-level wreckage); transport/setup failure with healthy
  /healthz = SCRIPT_ERROR (G8).

Constraint anchor qdrant_range_collections_update_001 (explicit, endpoint):
  description: "update-time HnswConfigDiff schema minima: m >= 0,
  ef_construct >= 4, full_scan_threshold >= 10 (KB, diff-specific minimum),
  payload_m >= 0"
  assertion: "HnswConfigDiff (update): m minimum 0; ef_construct minimum 4;
  full_scan_threshold minimum 10 (KB); payload_m minimum 0"
  (source_url https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection,
  doc_version 1.18.x (versioned v-1-18-x api-reference)).

Rubric class notes (measured v1.18.0 shape, cross-checked with the R-chunk
  create-face logs of the same runtime): below-min VALUES inside a valid JSON
  type answer 422 "Validation error in JSON body: [<path>: value N invalid,
  must be X or larger]" (param path named); negative ints on usize-typed
  fields answer 400 "Format error in JSON body: invalid value: integer `-N`,
  expected usize at line L column C" (field NOT named - serde cannot attach
  the wire path). Both classes are graded with the same rubric; the gradient
  between them is printed as the per-leg score. c1 tokens shorter than 3
  chars (the single-letter field 'm') are matched word-bounded so the letter
  'm' cannot false-positive on prose like 'Format error in JSON body'.
"""
import os
import re
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

PFX = "scu02" + uuid.uuid4().hex[:6]
COL = PFX + "_hnsw"
DIM = 4

# closure legs: the four documented minima, one PATCH per parameter
CLOSURE_LEGS = [
    ("m=0 (minimum 0)", {"hnsw_config": {"m": 0}}, "m"),
    ("ef_construct=4 (minimum 4)", {"hnsw_config": {"ef_construct": 4}}, "ef_construct"),
    ("full_scan_threshold=10 (minimum 10)", {"hnsw_config": {"full_scan_threshold": 10}}, "full_scan_threshold"),
    ("payload_m=0 (minimum 0)", {"hnsw_config": {"payload_m": 0}}, "payload_m"),
]
# violation legs: below-minimum values, one PATCH per parameter. c1 tokens are
# the full field paths (plus the bare name where it is not a substring of
# surrounding prose by itself - the 3+ char names are safe substrings).
VIOLATION_LEGS = [
    ("ef_construct=3 (below min 4)", {"hnsw_config": {"ef_construct": 3}},
     ["hnsw_config.ef_construct", "ef_construct"]),
    ("full_scan_threshold=9 (below min 10)", {"hnsw_config": {"full_scan_threshold": 9}},
     ["hnsw_config.full_scan_threshold", "full_scan_threshold"]),
    ("m=-1 (below min 0)", {"hnsw_config": {"m": -1}},
     ["hnsw_config.m"]),
    ("payload_m=-1 (below min 0)", {"hnsw_config": {"payload_m": -1}},
     ["hnsw_config.payload_m", "payload_m"]),
]

FORMAT_HINTS = ["must be", "expected", "should be", "valid", "range", "minimum",
                "at least", "or larger", "from ", "usize", "u32", "u64",
                "integer", "invalid"]
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


def rubric_score(raw, param_tokens):
    """Type-2 rubric: c1 offending parameter path named, c2 format/range
    statement, c3 actionable hint. Returns (score 0..3, details).
    Tokens shorter than 3 chars (e.g. the single-letter field 'm') are
    matched with word boundaries so 'm' cannot false-positive on prose like
    'Format error in JSON body'; longer tokens use substring match."""
    low = str(raw).lower()
    c1 = False
    for t in param_tokens:
        tl = t.lower()
        if len(tl) <= 2:
            if re.search(r"(?<![a-z0-9_])" + re.escape(tl) + r"(?![a-z0-9_])", low):
                c1 = True
                break
        elif tl in low:
            c1 = True
            break
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
    print("[assertion quote] 'HnswConfigDiff (update): m minimum 0; ef_construct "
          "minimum 4; full_scan_threshold minimum 10 (KB); payload_m minimum 0'")
    try:
        ok, err = rt.setup_default(COL, dim=DIM, metric="Cosine")
        if not ok:
            script_error(f"premise create {COL} failed: {err}")
        print(f"[setup] created {COL} (dim={DIM})")

        # ---- closure legs: documented minima must be ACCEPTED (G4 ground) ----
        for tag, body, param in CLOSURE_LEGS:
            st, raw = safe_request("PATCH", "update_collection", body=body,
                                   path_params={"name": COL}, timeout=30)
            print(f"[closure {tag}] body={json.dumps(body)} -> status={st} raw={str(raw)[:300]}")
            transport_guard(f"closure {tag}", st, raw)
            if st != 200:
                defect("Type1_IllegalRejection",
                       f"legal minimum-value diff {json.dumps(body)} (constraint "
                       f"qdrant_range_collections_update_001 documents minimum "
                       f"for {param}) answered HTTP {st}; inclusive minima must "
                       f"be accepted: {str(raw)[:300]!r}")
            b = jload(raw)
            if b.get("result") is not True:
                defect("Type4_StateLogicViolation",
                       f"200 envelope result not true on closure leg {tag}: {str(raw)[:300]!r}")
            print(f"[closure {tag}] accepted 200 result:true")

        # ---- violation legs: below-minimum values, refused 4xx + rubric grade ----
        worst = 0
        for tag, body, tokens in VIOLATION_LEGS:
            st, raw = safe_request("PATCH", "update_collection", body=body,
                                   path_params={"name": COL}, timeout=30)
            print(f"[violation {tag}] body={json.dumps(body)} -> status={st} raw={str(raw)[:400]}")
            transport_guard(f"violation {tag}", st, raw)
            if 200 <= st < 300:
                defect("Type1_IllegalSuccess",
                       f"below-minimum diff {json.dumps(body)} answered HTTP {st} "
                       f"result-accepted; constraint documents minimum and the "
                       f"value violates it: {str(raw)[:300]!r}")
            if st not in (400, 422):
                defect("Type4_StateLogicViolation",
                       f"below-minimum diff {json.dumps(body)} answered HTTP {st}; "
                       f"expected a 4xx client error (400/422): {str(raw)[:300]!r}")
            score, details = rubric_score(raw, tokens)
            print(f"[violation {tag}] refused {st}; rubric={score}/3 {json.dumps(details)}")
            if score == 0:
                defect("Type2_PoorDiagnostics",
                       f"refusal body for {json.dumps(body)} scores 0/3 on the "
                       f"Type-2 rubric - names neither the offending parameter "
                       f"({tokens}) nor a format/range statement; developer "
                       f"cannot locate the problem: {str(raw)[:400]!r}")
            worst = max(worst, score)

        # ---- control: describe still healthy after all legs ----
        st, raw = safe_request("GET", "describe_collection", path_params={"name": COL},
                               timeout=30)
        print(f"[control describe {COL}] status={st} raw={str(raw)[:300]}")
        transport_guard("control describe", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"control describe on {COL} answered {st} after the closure/"
                   f"violation legs: {str(raw)[:300]!r}")

        print(f"OK: minima accepted (4/4 closure legs, 200 result:true); all "
              f"below-minimum values refused with 4xx; worst rubric score "
              f"{worst}/3 (claim threshold is 0/3)")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
