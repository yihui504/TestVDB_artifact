#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_update_005
# strategy: behavioral_contract
# endpoint: collections+update
# constraint_ids: qdrant_doccons_indexing_threshold_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the versioned v-1-18-x OpenAPI
#   carries two mutually contradictory 'Default value' statements for the
#   SAME indexing_threshold property depending on which schema page you read:
#   OptimizersConfig says 10,000 (the schema behind create/describe readback)
#   while OptimizersConfigDiff - the schema accepted by PATCH update - says
#   20,000. A user who plans storage/optimizer capacity from the PATCH
#   page's 20,000 default plans against a value the runtime never
#   materializes. This script constructs against BOTH documented sides and
#   records which one the v1.18.0 runtime contradicts.)
"""
Attack: doc_consistency class (Rule 2.9, new-class fallback path - empty
  bound_strategies -> general testing principles both-direction construction,
  D2/G4) x qdrant_doccons_indexing_threshold_001 on collections+update
  (chunk_collections+update unit
  constraints::qdrant_doccons_indexing_threshold_001 - assertion: "doc-internal
  conflict: spec says default ten thousand (OptimizersConfig, create/readback)
  vs twenty thousand (OptimizersConfigDiff, update diff); either side may be
  violated", evidence_tier=explicit, system level).
  BOTH documented sides are constructed separately and each measurement is
  recorded:
    side A (OptimizersConfig, create/readback page claim: "Default value is
      10,000"): full-omission create (no optimizers_config at all) -> the
      readback value IS the create-side default - construct A1;
      partial-diff create (optimizers_config present but indexing_threshold
      omitted) -> the same default-resolution path - construct A2 (this is
      the face where the diff schema's own default WOULD apply if it had one);
    side B (OptimizersConfigDiff, PATCH page claim: "Default value is
      20,000"): PATCH a partial optimizers_config diff (indexing_threshold
      omitted) on a live collection -> an update-diff default of 20000, if it
      existed, would surface here as a readback jump - construct B1.
  Explicit-value controls: PATCH indexing_threshold=20000 must land (20000 is
  reachable when EXPLICIT - the conflict is confined to the *default*, which
  is exactly what both doc sentences claim).
  R17 reconciliation (G10): this doccons unit is owned here (_005); the
  pure range face (indexing_threshold minimum 0) is exercised inside
  semantic_collections_update_003 on range_collections_update_002.
Oracle: the full-omission create readback (side-A construct A1) and the
  partial-diff create readback (A2) both resolve to ONE integer default D;
  the partial-diff PATCH (side-B construct B1) must NOT change the readback
  away from D (diff-omitted members preserve the current value); and the
  explicit PATCH indexing_threshold=20000 echoes 20000 in readback. Verdict:
  DEFECT_FOUND (Type4_StateLogicViolation, doc-drift family - run2r #1
  defects 9/11/14 precedent) whenever the two documented defaults (10,000 vs
  20,000) are not both honored by the materialized default D - since the doc
  sentences contradict each other, D can equal only one of them and the
  OTHER documented side is thereby violated: D==20000 -> side A (the
  OptimizersConfig "Default value is 10,000" sentence) violated; D==10000 ->
  side B (the OptimizersConfigDiff "Default value is 20,000" sentence) never
  materializes on any construct (A1/A2/B1 all read 10000) and is violated;
  D==neither -> BOTH sides violated (recorded additionally); D_D (explicit
  20000 PATCH echo) != 20000 with a 200 answer = Type4 200-without-echo
  silent-ignore; 5xx with healthy /healthz = Type3_RuntimeFailure; setup or
  transport failure = SCRIPT_ERROR (G8 - measurements above never become
  defect conclusions on a broken premise).

Constraint anchor qdrant_doccons_indexing_threshold_001 (explicit, system):
  description: "doc-internal conflict inside the versioned v-1-18-x OpenAPI:
  the OptimizersConfig.indexing_threshold property description states
  'Default value is 10,000', while the OptimizersConfigDiff.indexing_threshold
  property description (the schema accepted by PATCH update) states 'Default
  value is 20,000'; the v1.18.0 runtime readback resolves at 10000 - behavior
  follows the implementation and either documented side may be violated"
  assertion: "doc-internal conflict: spec says default ten thousand
  (OptimizersConfig, create/readback) vs twenty thousand (OptimizersConfigDiff,
  update diff); either side may be violated"
  (versioned OpenAPI quotes verified verbatim in the local .sourcedeps
  v1.18.0 api shards before writing: OptimizersConfig desc '...Default value
  is 10,000, based on experiments and observations...' vs OptimizersConfigDiff
  desc '...Default value is 20,000, based on <scann docs>...' - spec wins,
  the doc conflict is real.)
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

PFX = "scu05" + uuid.uuid4().hex[:6]
COL_A = PFX + "_fullomit"
COL_B = PFX + "_partdiff"
DIM = 4
SIDE_A_DOC = 10000   # OptimizersConfig description: "Default value is 10,000"
SIDE_B_DOC = 20000   # OptimizersConfigDiff description: "Default value is 20,000"


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


def read_indexing_threshold(name):
    """describe readback of the effective optimizer config (readback key is
    optimizer_config per the collections+get response_shape grid)."""
    st, raw = safe_request("GET", "describe_collection", path_params={"name": name},
                           timeout=30)
    if st != 200:
        return None, f"describe failed: st={st} raw={str(raw)[:200]}"
    body = jload(raw)
    res = body.get("result") if isinstance(body, dict) else None
    cfg = (res or {}).get("config") if isinstance(res, dict) else None
    opt = (cfg or {}).get("optimizer_config") if isinstance(cfg, dict) else None
    if not isinstance(opt, dict):
        return None, f"config.optimizer_config missing: {str(cfg)[:300]}"
    return opt.get("indexing_threshold"), None


def cleanup():
    for name in (COL_A, COL_B):
        try:
            rt.drop_collection(name)
        except Exception as e:
            print(f"cleanup warning (drop {name}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[assertion quote] 'doc-internal conflict: spec says default ten "
          "thousand (OptimizersConfig, create/readback) vs twenty thousand "
          "(OptimizersConfigDiff, update diff); either side may be violated'")
    results = {}
    try:
        # ---- construct A1 (side A): full-omission create default ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": COL_A}, timeout=30)
        print(f"[A1 create {COL_A} (optimizers_config omitted)] status={st} raw={str(raw)[:300]}")
        transport_guard("A1 create", st, raw)
        if st not in (200, 201):
            script_error(f"A1 create failed: {st} {str(raw)[:200]}")
        d_a1, err = read_indexing_threshold(COL_A)
        if err:
            script_error(f"A1 readback failed: {err}")
        results["A1_full_omission_create"] = d_a1
        print(f"[A1 readback] optimizer_config.indexing_threshold = {d_a1} "
              f"(side-A doc default 10000, side-B doc default 20000)")

        # ---- construct A2 (side A): partial-diff create (diff schema in use,
        #      indexing_threshold omitted - where a diff default WOULD apply) ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"},
                                     "optimizers_config": {"deleted_threshold": 0.5}},
                               path_params={"name": COL_B}, timeout=30)
        print(f"[A2 create {COL_B} (partial optimizers_config diff)] status={st} raw={str(raw)[:300]}")
        transport_guard("A2 create", st, raw)
        if st not in (200, 201):
            script_error(f"A2 create failed: {st} {str(raw)[:200]}")
        d_a2, err = read_indexing_threshold(COL_B)
        if err:
            script_error(f"A2 readback failed: {err}")
        results["A2_partial_diff_create"] = d_a2
        print(f"[A2 readback] optimizer_config.indexing_threshold = {d_a2}")

        # ---- construct B1 (side B): partial-diff PATCH on a live collection ----
        st, raw = safe_request("PATCH", "update_collection",
                               body={"optimizers_config": {"deleted_threshold": 0.7}},
                               path_params={"name": COL_A}, timeout=30)
        print(f"[B1 PATCH {COL_A} partial optimizers_config diff] status={st} raw={str(raw)[:300]}")
        transport_guard("B1 patch", st, raw)
        if st != 200:
            script_error(f"B1 partial-diff PATCH refused: {st} {str(raw)[:200]} "
                         f"(premise for the update-diff-default construct)")
        d_b1, err = read_indexing_threshold(COL_A)
        if err:
            script_error(f"B1 readback failed: {err}")
        results["B1_partial_diff_patch"] = d_b1
        print(f"[B1 readback] optimizer_config.indexing_threshold = {d_b1} "
              f"(must equal A1={d_a1}: diff-omitted members preserve, no "
              f"20,000 default materialization)")

        # ---- explicit control: indexing_threshold=20000 must land ----
        st, raw = safe_request("PATCH", "update_collection",
                               body={"optimizers_config": {"indexing_threshold": 20000}},
                               path_params={"name": COL_A}, timeout=30)
        print(f"[D1 PATCH {COL_A} indexing_threshold=20000 explicit] status={st} raw={str(raw)[:300]}")
        transport_guard("D1 explicit patch", st, raw)
        if st != 200:
            script_error(f"D1 explicit PATCH refused: {st} {str(raw)[:200]}")
        d_d1, err = read_indexing_threshold(COL_A)
        if err:
            script_error(f"D1 readback failed: {err}")
        results["D1_explicit_20000"] = d_d1
        print(f"[D1 readback] optimizer_config.indexing_threshold = {d_d1} "
              f"(sent explicit 20000)")
        if d_d1 != 20000:
            defect("Type4_StateLogicViolation",
                   f"explicit PATCH indexing_threshold=20000 answered 200 but "
                   f"describe echoes {d_d1} - 200-without-echo silent-ignore "
                   f"(run2r #1 family); the explicit-value control must land")

        # ---- doc-consistency verdict: which documented side is contradicted ----
        print(f"[doccons measurements] {json.dumps(results)}")
        d = d_a1
        if d not in (SIDE_A_DOC, SIDE_B_DOC):
            defect("Type4_StateLogicViolation",
                   f"materialized default D={d} matches NEITHER documented side "
                   f"(10,000 / 20,000) - both OptimizersConfig and "
                   f"OptimizersConfigDiff 'Default value' sentences violated; "
                   f"raw measurements: {json.dumps(results)}")
        violated = SIDE_A_DOC if d == SIDE_B_DOC else SIDE_B_DOC
        other = SIDE_B_DOC if d == SIDE_B_DOC else SIDE_A_DOC
        inconsistency = []
        for k, v in results.items():
            if k == "D1_explicit_20000":
                continue  # explicit values are not defaults
            if v != d:
                inconsistency.append(f"{k}={v} (expected same default {d})")
        if inconsistency:
            defect("Type4_StateLogicViolation",
                   f"default-resolution inconsistent across constructs: "
                   f"{'; '.join(inconsistency)} - the same omitted "
                   f"indexing_threshold resolved differently on one face")
        defect("Type4_StateLogicViolation",
               f"doc-consistency unit qdrant_doccons_indexing_threshold_001: "
               f"the versioned v-1-18-x OpenAPI documents 'Default value is "
               f"10,000' (OptimizersConfig, create/readback) AND 'Default "
               f"value is 20,000' (OptimizersConfigDiff, the schema accepted "
               f"by PATCH); the v1.18.0 runtime materializes D={d} on every "
               f"default construct (full-omission create, partial-diff create, "
               f"partial-diff PATCH - see measurements), so the documented "
               f"side claiming {violated} is contradicted by the API while "
               f"only the {other} sentence holds - doc-drift family, run2r #1 "
               f"defects 9/11/14 precedent (docs 20000 vs impl 10000; "
               f"implementation self-consistent, documentation internally "
               f"contradictory). Note: 20000 remains reachable when set "
               f"explicitly (control D1), confining the falsehood to the "
               f"'default' claim itself")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
