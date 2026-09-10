#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_update_005
# strategy: state_readback_normalization
# endpoint: collections+update
# constraint_ids: qdrant_doccons_indexing_threshold_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: doc-internal conflict on the optimizers indexing_threshold
  default, measured against the runtime (PATCH collections+update +
  PUT collections+create + GET collections+get; runtime PATHS
  create_collection / describe_collection / update_collection,
  verbatim raw_knowledge api_endpoints[].url).
  qdrant_doccons_indexing_threshold_001: the versioned v-1-18-x
  OpenAPI describes 'Default value is 10,000' on the
  OptimizersConfig.indexing_threshold property (create/readback
  schema) and 'Default value is 20,000' on the
  OptimizersConfigDiff.indexing_threshold property (the diff schema
  accepted by PATCH update). The two documented defaults are
  mutually exclusive; the assertion says the v1.18.0 runtime
  resolves at 10000 and either documented side may be violated.
  Per doc_consistency construction, the spec side and the prose side
  are attacked SEPARATELY and each side's violation is recorded:
  (A spec side, create/readback) create a collection with the
      DEFAULT optimizers config -> describe
      config.optimizer_config.indexing_threshold = V_c. The
      OptimizersConfig-side claim is satisfied iff V_c == 10000.
  (B prose side, update diff) on the same collection PATCH a VALID
      optimizers_config diff that omits indexing_threshold
      ({"deleted_threshold": 0.2}) -> describe again = V_b. The
      OptimizersConfigDiff-side claim ('Default value is 20,000')
      is satisfied iff the diff merge materializes 20000
      (V_b == 20000); V_b == V_c means the documented diff default
      never materializes (claim contradicted).
  (C merge semantics control) create a second collection with an
      EXPLICIT indexing_threshold = 30000, then PATCH the same
      unrelated diff -> describe = V_cx. Option-merge semantics
      (unspecified diff fields keep the current value) pin
      V_cx == 30000; V_cx == 10000 would additionally mean a
      rejected-legit PATCH resets explicit config (stronger state
      anomaly), V_cx == 20000 would confirm the diff default claim.
  Adjudication (doc-stale family; run2r #1 measured the same
  conflict: docs default 20000 vs impl materializes 10000):
  - V_c != 10000 -> OptimizersConfig-side claim violated
    (DEFECT_FOUND, attribution: create/readback page).
  - V_b == 20000 AND V_c == 10000 -> both documented sides hold
    per-schema -> the doc numbers are per-schema defaults, no
    conflict materialized (NO_DEFECT on this leg).
  - otherwise (V_b == V_c == 10000 expected) -> the
    OptimizersConfigDiff 'Default value is 20,000' claim is
    contradicted by the runtime (DEFECT_FOUND, attribution: update
    page diff schema; docs stale vs impl self-consistent at 10000).
  - V_cx not preserved at 30000 -> merge-overwrite anomaly
    (DEFECT_FOUND, Type4).
  [chunk_collections+update coverage: state_readback_normalization
   (default-materialization readback) x
   qdrant_doccons_indexing_threshold_001]
Oracle: 200-returning create+describe paths read V_c == 10000 (satisfies
  the OptimizersConfig 'Default value is 10,000' claim); after a
  valid optimizers diff PATCH that omits indexing_threshold the
  readback V_b stays 10000, so the OptimizersConfigDiff 'Default
  value is 20,000' claim never materializes (DEFECT_FOUND with
  update-page attribution); explicit-30000 collection stays 30000
  after the same diff (merge keeps current value) — V_c==20000 or
  V_b==20000 would flip the attribution to the other side, V_cx
  reset = Type4 merge-overwrite; 5xx = Type3 only with /healthz
  liveness.
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

DIM = 4
CLAIM_CREATE = 10000   # OptimizersConfig.indexing_threshold description
CLAIM_DIFF = 20000     # OptimizersConfigDiff.indexing_threshold description
EXPLICIT_IT = 30000


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def get_it(raw):
    """indexing_threshold from a describe raw, or None."""
    b = parse_json(raw)
    res = b.get("result") if isinstance(b, dict) else None
    cfg = res.get("config") if isinstance(res, dict) else None
    op = cfg.get("optimizer_config") if isinstance(cfg, dict) else None
    if isinstance(op, dict):
        v = op.get("indexing_threshold")
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return None


def describe_it(tag, name):
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    print(f"[describe {tag}] status={s} raw={str(raw)[:260]}")
    return s, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scup5_" + TS + "_"
    C_DEF = PFX + "def"
    C_EXP = PFX + "exp"
    DEFECTS = []
    names = [C_DEF, C_EXP]

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def guard_describe(tag, name):
        s, raw = describe_it(tag, name)
        if s == 0:
            if not alive():
                return None, "TRANSPORT"
            DEFECTS.append(f"describe({tag}) transport failure with /healthz "
                           f"alive — Type3_RuntimeFailure")
            return None, "ERR"
        if 500 <= s <= 599:
            if not alive():
                return None, "TRANSPORT"
            DEFECTS.append(f"describe({tag}) returned {s} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            return None, "ERR"
        if s != 200:
            DEFECTS.append(f"describe({tag}) on the existing collection "
                           f"returned {s} — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")
            return None, "ERR"
        return get_it(raw), "OK"

    try:
        # ---- (A)+(B): default-config create + unrelated diff PATCH ----
        s, raw = safe_request("PUT", "create_collection",
                              {"vectors": {"size": DIM, "distance": "Cosine"}},
                              path_params={"name": C_DEF})
        print(f"[create default] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: create default {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        v_c, st = guard_describe("A_default", C_DEF)
        if st == "TRANSPORT":
            return "SCRIPT_ERROR"
        print(f"[leg A] V_c (default create readback) = {v_c!r} "
              f"(OptimizersConfig doc claim: {CLAIM_CREATE})")
        if v_c is None:
            DEFECTS.append("leg A: describe readback lacks an integer "
                           "optimizer_config.indexing_threshold — cannot "
                           "materialize ANY documented default — "
                           "Type4_StateLogicViolation")
        elif v_c != CLAIM_CREATE:
            DEFECTS.append(f"leg A: OptimizersConfig-side claim "
                           f"'Default value is {CLAIM_CREATE}' VIOLATED — "
                           f"default-config create readback "
                           f"indexing_threshold={v_c} — doc-stale on the "
                           f"create/readback side — "
                           f"Type4_StateLogicViolation")

        s, raw = safe_request("PATCH", "update_collection",
                              {"optimizers_config": {"deleted_threshold": 0.2}},
                              path_params={"name": C_DEF})
        print(f"[patch B unrelated diff] status={s} raw={str(raw)[:200]}")
        if s == 0:
            alive()
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"PATCH(B) returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif s not in (200, 400, 422):
            DEFECTS.append(f"PATCH(B) valid optimizers diff returned {s} "
                           f"(expected 200) — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")
        v_b, st = guard_describe("B_afterdiff", C_DEF)
        if st == "TRANSPORT":
            return "SCRIPT_ERROR"
        print(f"[leg B] V_b (after unrelated diff PATCH) = {v_b!r} "
              f"(OptimizersConfigDiff doc claim: {CLAIM_DIFF})")
        if v_c is not None and v_c == CLAIM_CREATE and v_b == CLAIM_DIFF:
            print("[leg B] OptimizersConfigDiff-side claim MATERIALIZED "
                  "(diff merge applies its documented default 20000); both "
                  "documented sides hold per-schema — doc conflict text "
                  "resolved")
        elif v_b is not None and v_b != CLAIM_DIFF:
            DEFECTS.append(f"leg B: OptimizersConfigDiff-side claim "
                           f"'Default value is {CLAIM_DIFF}' VIOLATED — after "
                           f"an optimizers diff PATCH omitting "
                           f"indexing_threshold the readback materializes "
                           f"{v_b} (impl self-consistent at the "
                           f"OptimizersConfig default) — doc-stale on the "
                           f"update-page diff schema — "
                           f"Type4_StateLogicViolation")

        # ---- (C) merge-semantics control: explicit 30000 must survive ----
        s, raw = safe_request("PUT", "create_collection",
                              {"vectors": {"size": DIM, "distance": "Cosine"},
                               "optimizer_config": {"indexing_threshold":
                                                    EXPLICIT_IT}},
                              path_params={"name": C_EXP})
        print(f"[create explicit it={EXPLICIT_IT}] status={s} "
              f"raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: create explicit {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        v_cx0, st = guard_describe("C_before", C_EXP)
        if st == "TRANSPORT":
            return "SCRIPT_ERROR"
        if v_cx0 != EXPLICIT_IT:
            DEFECTS.append(f"leg C setup: explicit create "
                           f"indexing_threshold={EXPLICIT_IT} not echoed "
                           f"(readback {v_cx0!r}) — "
                           f"Type4_StateLogicViolation")
        s, raw = safe_request("PATCH", "update_collection",
                              {"optimizers_config": {"deleted_threshold": 0.2}},
                              path_params={"name": C_EXP})
        print(f"[patch C unrelated diff] status={s} raw={str(raw)[:200]}")
        if s == 0:
            alive()
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"PATCH(C) returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif s not in (200, 400, 422):
            DEFECTS.append(f"PATCH(C) valid optimizers diff returned {s} "
                           f"(expected 200) — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")
        v_cx, st = guard_describe("C_after", C_EXP)
        if st == "TRANSPORT":
            return "SCRIPT_ERROR"
        print(f"[leg C] V_cx (explicit {EXPLICIT_IT} after unrelated diff "
              f"PATCH) = {v_cx!r}")
        if v_cx != EXPLICIT_IT:
            DEFECTS.append(f"leg C: explicit indexing_threshold="
                           f"{EXPLICIT_IT} was NOT preserved by an unrelated "
                           f"optimizers diff PATCH (readback {v_cx!r}) — "
                           f"option-merge semantics violated (explicit config "
                           f"overwritten) — Type4_StateLogicViolation")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for n in names:
            try:
                rt.drop_collection(n)
            except Exception:
                pass


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
