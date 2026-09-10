#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_013
# strategy: diagnosis_quality
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_004
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence on optimizer-bound refusals) +
#   BS-04 (one-below/one-above boundary probes on every bound)
"""
Attack: diagnosis_quality x qdrant_range_collections_create_004
  (chunk_collections+create-1of2; PUT /collections/{name}, path_key
  create_collection from runtime PATHS, URL from raw_knowledge
  api_endpoints[collections+create].url). The assertion (evidence_tier=
  explicit): optimizers_config bounds deleted_threshold in [0, 1],
  vacuum_min_vector_number minimum 100, max_segment_size minimum 1 (KB),
  memmap_threshold minimum 0, indexing_threshold minimum 0 (KB). Violation
  direction - each bound crossed by its smallest step on an otherwise-legal
  create, fresh name each:
    deleted_threshold=-0.1, deleted_threshold=1.1,
    vacuum_min_vector_number=99, max_segment_size=0,
    memmap_threshold=-1, indexing_threshold=-1
  Each must be refused 400/422 (acceptance = Type1_IllegalSuccess) and each
  rejection is scored on the Type-2 rubric (parameter named / range hint /
  actionable).
  [chunk_collections+create-1of2 coverage: diagnosis_quality x
   qdrant_range_collections_create_004 (6 bound-crossing refusals +
   per-field Type-2 rubric scoring)]
Oracle: each of the six bound-crossing creates is refused 400/422 (any 2xx =
  Type1_IllegalSuccess; 5xx with /healthz alive = Type3_RuntimeFailure) and
  no rejection message scores 0/3 on the Type-2 rubric (0/3 =
  Type2_PoorDiagnostics) - constraint qdrant_range_collections_create_004.

Rationale (G4/G5/G7): paired with semantic_collections_create_012 (closure),
this owns every bound's violation side; per-field rubric reporting makes the
diagnostics claim falsifiable per parameter instead of on average.
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

# ---- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p)
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

print("[path derivation] create_collection = /collections/{name} "
      "(raw_knowledge api_endpoints[collections+create].url = /collections/{collection_name})")

PREFIX = "scc13_"
RUN = str(int(time.time()))
CREATED = []
DENSE = {"size": 4, "distance": "Cosine"}


def safe_request(method, path_key, body=None, path_params=None, query_params=None, timeout=60):
    """All HTTP through the runtime; forwards method/path_key/body/path_params/
    query_params/timeout exactly (standing lesson). Returns (status, raw_text)."""
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


def mkn(tag):
    return f"{PREFIX}{RUN}_{tag}"


def create(name, optimizers):
    st, raw = safe_request("PUT", "create_collection",
                           {"vectors": DENSE, "optimizers_config": optimizers},
                           path_params={"name": name})
    print(f"[create {name}] status={st} raw={str(raw)[:300]}")
    if st in (200, 201):
        CREATED.append(name)
    return st, raw


def check_error_quality(raw, expected_param):
    """Type-2 rubric: parameter_named + format_hint + actionable."""
    body = jload(raw) if isinstance(raw, str) else raw
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    criteria = []
    if expected_param.lower() in error_msg:
        score += 1
        criteria.append("param_named")
    format_hints = ["must be", "expected", "should be", "valid", "range", "type",
                    "at least", "minimum", "maximum", "between", "greater", "less"]
    hit = [h for h in format_hints if h in error_msg]
    if hit:
        score += 1
        criteria.append(f"format_hint({hit[0]})")
    action_hints = ["correct", "try", "use", "change", "specify", "provide"]
    hit2 = [h for h in action_hints if h in error_msg]
    if hit2:
        score += 1
        criteria.append(f"actionable({hit2[0]})")
    return score, criteria, error_msg


def cleanup():
    for n in list(CREATED):
        try:
            rt.drop_collection(n)
        except Exception:
            pass


def main():
    hs, hraw = safe_request("GET", "healthz", timeout=15)
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")
    try:
        ok, err = rt.setup_default(mkn("ctl"), 4, "Cosine")
        if not ok:
            script_error(f"control setup_default failed: {err}")
        print("[control] setup_default create OK (deployment healthy)")
        try:
            rt.drop_collection(mkn("ctl"))
        except Exception:
            pass

        cases = [
            ("dt_low", "deleted_threshold", -0.1,
             "deleted_threshold=-0.1 (below the [0,1] interval)"),
            ("dt_high", "deleted_threshold", 1.1,
             "deleted_threshold=1.1 (above the [0,1] interval)"),
            ("vacuum", "vacuum_min_vector_number", 99,
             "vacuum_min_vector_number=99 (minimum 100)"),
            ("maxseg", "max_segment_size", 0,
             "max_segment_size=0 (minimum 1 KB)"),
            ("memmap", "memmap_threshold", -1,
             "memmap_threshold=-1 (minimum 0)"),
            ("indexing", "indexing_threshold", -1,
             "indexing_threshold=-1 (minimum 0)"),
        ]
        rubric_report = []
        for tag, field, value, why in cases:
            name = mkn(f"bad_{tag}")
            st, raw = create(name, {field: value})
            if st == 0:
                liveness("transport")
                script_error(f"transport failure on {tag}; no defect conclusion")
            if 500 <= st <= 599:
                if liveness("5xx") != 200:
                    script_error(f"{tag} 5xx ({st}) and /healthz not 200; deployment unstable")
                defect("Type3_RuntimeFailure",
                       f"[{tag}] bound-crossing create raised server error {st} while "
                       f"/healthz is alive; a range violation must be a clean 4xx; "
                       f"raw={str(raw)[:200]}")
            if 200 <= st <= 299:
                defect("Type1_IllegalSuccess",
                       f"[{tag}] optimizers_config.{why} was ACCEPTED with status {st}; "
                       f"constraint qdrant_range_collections_create_004 fixes the "
                       f"bound; raw={str(raw)[:250]}")
            if st not in (400, 422):
                script_error(f"[{tag}] unadjudicable refusal status {st} "
                             f"(expected 400/422); raw={str(raw)[:200]}")
            score, criteria, msg = check_error_quality(raw, field)
            rubric_report.append((field, score, criteria))
            print(f"[{tag}] refused with {st}; rubric score={score}/3 "
                  f"criteria={criteria}; message={msg[:250]}")
            if score == 0:
                defect("Type2_PoorDiagnostics",
                       f"[{tag}] the refusal for optimizers_config.{why} names no "
                       f"parameter, gives no range/format hint and no actionable "
                       f"suggestion (0/3 on the Type-2 rubric); message={msg[:250]}")

        print("[summary] 6/6 optimizers bound-crossings refused with clean 4xx; "
              "rubric scores: " +
              ", ".join(f"{f}={s}/3" for f, s, _ in rubric_report) +
              " - violation + diagnostics promise holds per "
              "qdrant_range_collections_create_004")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
