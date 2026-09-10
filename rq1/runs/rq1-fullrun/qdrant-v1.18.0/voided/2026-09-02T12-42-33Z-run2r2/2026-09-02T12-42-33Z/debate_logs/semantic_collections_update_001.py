#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_update_001
# strategy: behavioral_contract
# endpoint: collections+update
# constraint_ids: qdrant_behavioral_collections_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - API contract verification of the
#   PATCH collections+update face: the published promise "valid update on an
#   existing collection returns HTTP 200; a missing collection returns 404; an
#   invalid diff returns 400" is verified here against the live v1.18.0
#   runtime, including the result:boolean envelope shape and the config echo
#   persistence that a "200 ok" answer implicitly promises)
"""
Attack: behavioral_contract (S1, G4 positive/negative pairing, G7 oracle-first)
  x qdrant_behavioral_collections_update_001 on collections+update
  (chunk_collections+update unit assertions::qdrant_behavioral_collections_update_001 -
  expected_behavior: "valid update on an existing collection returns HTTP 200;
  a missing collection returns 404; an invalid diff returns 400",
  evidence_tier=explicit, endpoint level, defect_type_if_violated =
  Type1_IllegalSuccess).
  R17 chunk_collections+update semantic coverage map (G10 reconciliation):
    _001 behavioral_contract x behavioral_collections_update_001 (this script);
    _004 behavioral_contract x state_collections_update_001 (immutability /
        changeability readback semantics);
    _005 doccons measurement x doccons_indexing_threshold_001 (indexing_threshold
        documented-default 10000-vs-20000 conflict, both sides constructed);
    _002 diagnosis_quality (S2 Type-2 rubric) x range_collections_update_001
        (HnswConfigDiff minima); _003 diagnosis_quality x range_collections_update_002
        (optimizers_config diff bounds).
    search_correctness / metamorphic / filter_semantics: NO applicable surface
    on this config-update face (no vector query, no filter, no result-ranking
    semantics) - honestly reported, not fabricated (G10). Illegal-rejection
    closure sweeps live in the boundary lane's range matrix; this script's
    positive legs carry the G4 ground for its own negative branches.
Oracle: PATCH of a legal diff on a self-created collection returns HTTP 200
  with envelope result===true (collections+update response_shape declares
  result:boolean) and the accepted value ECHOES in the describe readback
  (200-without-echo on a legal diff = Type4_StateLogicViolation silent-ignore,
  run2r #1 inline_storage family - R16 standing lesson: probe persistence via
  describe readback); PATCH on a never-created unique-prefix name returns HTTP
  404 twice without flapping (200 on a missing collection = Type1_IllegalSuccess
  phantom success; non-404 non-200 = Type4); an invalid diff is refused with a
  4xx client error - the versioned v-1-18-x OpenAPI documents BOTH 400
  (format/deserialization) and 422 (value validation) error responses for this
  endpoint, so a measured 422 satisfies the assertion's loose "400" wording
  (spec-derived fields win over doc paraphrase, D3b-2/R16 - conflict zones
  measured-only), while ANY 2xx on an invalid diff = Type1_IllegalSuccess per
  the assertion's own defect_type_if_violated; 5xx with healthy /healthz =
  Type3_RuntimeFailure; transport/setup failures never produce defect
  conclusions (G8).

Constraint anchor qdrant_behavioral_collections_update_001 (explicit,
  endpoint level):
  description: "update returns 200 ok; 404 when the collection is missing;
  400 on invalid diff"
  expected_behavior: "valid update on an existing collection returns HTTP 200;
  a missing collection returns 404; an invalid diff returns 400"
  (source_url https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection,
  doc_version 1.18.x (versioned v-1-18-x api-reference)).

Legs:
  leg 1 positive-valid - PATCH hnsw_config {ef_construct: 64} (value inside the
      documented HnswConfigDiff range) on a self-created collection -> HTTP 200
      + result===true + describe readback config.hnsw_config.ef_construct == 64
      (the "200 ok" answer promises the config change landed; echo absence =
      the silent-ignore defect family);
  leg 2 negative-missing - PATCH the SAME legal body on a never-created
      unique-prefix name -> HTTP 404 exactly, twice (stability, no flapping);
  leg 3 invalid-diff-format - PATCH {"optimizers_config": "not-an-object"}
      (wrong JSON type for a diff section) -> refused 4xx (measured 400);
  leg 4 invalid-diff-value - PATCH {"hnsw_config": {"ef_construct": 3}}
      (below the documented minimum 4) -> refused 4xx (measured 422; both
      400/422 spec-compliant per the versioned OpenAPI error responses);
  leg 5 control - after the 404/4xx legs the same legal PATCH on the existing
      collection answers 200 again (rejections are body-scoped, not face-level
      wreckage) and the config stays echoable.

URL derivation: raw_knowledge api_endpoints[collections+update].url is the
  update-collection reference; all calls go through runtime PATHS keys
  (update_collection PATCH /collections/{name}, describe_collection GET
  /collections/{name}, healthz GET /healthz) - literal path strings forbidden.
  R15/R16 lessons honored: constraint_id bare IDs; envelope result.<field>
  extraction (never fixed index chains); unique per-script prefixes;
  inline /healthz probes; safe_request forwards body/timeout/query_params
  exactly; cleanup drops only collections this script created.
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

PFX = "scu01" + uuid.uuid4().hex[:6]
DIM = 4
COL = PFX + "_live"
NEVER = PFX + "_never_" + uuid.uuid4().hex[:6]
assert NEVER != COL


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


def describe(name):
    """GET describe; returns (status, raw, result_dict_or_None)."""
    st, raw = safe_request("GET", "describe_collection", path_params={"name": name},
                           timeout=30)
    body = jload(raw)
    res = body.get("result") if isinstance(body, dict) else None
    return st, raw, (res if isinstance(res, dict) else None)


def get_hnsw_ef(name):
    st, raw, res = describe(name)
    if st != 200 or res is None:
        return None, f"describe failed: st={st} raw={str(raw)[:200]}"
    hnsw = (res.get("config") or {}).get("hnsw_config")
    if not isinstance(hnsw, dict):
        return None, f"config.hnsw_config not an object: {str(res.get('config'))[:300]}"
    return hnsw.get("ef_construct"), None


def patch_diff(name, body):
    st, raw = safe_request("PATCH", "update_collection", body=body,
                           path_params={"name": name}, timeout=30)
    print(f"[PATCH {name}] body={json.dumps(body)} -> status={st} raw={str(raw)[:400]}")
    return st, raw


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception as e:
        print(f"cleanup warning (drop {COL}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[assertion quote] expected_behavior: 'valid update on an existing "
          "collection returns HTTP 200; a missing collection returns 404; an "
          "invalid diff returns 400'")
    try:
        # ---- setup premise: one prefix-owned collection ----
        ok, err = rt.setup_default(COL, dim=DIM, metric="Cosine")
        if not ok:
            script_error(f"premise create {COL} failed: {err}")
        print(f"[setup] created {COL} (dim={DIM})")

        LEGAL = {"hnsw_config": {"ef_construct": 64}}

        # ---- leg 1: positive-valid - 200 + result:true + echo persistence ----
        st, raw = patch_diff(COL, LEGAL)
        transport_guard("leg1 legal patch", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"legal PATCH {json.dumps(LEGAL)} on existing collection {COL} "
                   f"answered HTTP {st}; assertion positive branch promises 200: "
                   f"{str(raw)[:300]!r}")
        body = jload(raw)
        if body.get("result") is not True:
            defect("Type4_StateLogicViolation",
                   f"200 body envelope result is not true: {str(raw)[:300]!r} "
                   f"(collections+update response_shape declares result:boolean)")
        ef, err = get_hnsw_ef(COL)
        if err:
            script_error(f"leg1 echo readback failed: {err}")
        print(f"[leg1 echo] describe hnsw_config.ef_construct={ef} (sent 64)")
        if ef != 64:
            defect("Type4_StateLogicViolation",
                   f"valid PATCH answered 200 result:true but the describe readback "
                   f"shows hnsw_config.ef_construct={ef} (sent 64) - 200-without-echo "
                   f"silent-ignore, run2r #1 inline_storage defect family; the '200 ok' "
                   f"promise of a landed config change is not kept")

        # ---- leg 2: negative-missing - 404 on never-created name, twice ----
        for rep in (1, 2):
            st, raw = patch_diff(NEVER, LEGAL)
            transport_guard(f"leg2 attempt {rep}", st, raw)
            if st == 200:
                defect("Type1_IllegalSuccess",
                       f"PATCH on never-created collection name {NEVER} answered "
                       f"HTTP 200 with result:true; assertion negative branch "
                       f"promises 404 for a missing collection (phantom success): "
                       f"{str(raw)[:300]!r}")
            if st != 404:
                defect("Type4_StateLogicViolation",
                       f"PATCH on never-created collection name {NEVER} answered "
                       f"HTTP {st}; assertion negative branch promises exactly 404: "
                       f"{str(raw)[:300]!r}")

        # ---- leg 3: invalid diff - wrong JSON type (format class, expect 400) ----
        st, raw = patch_diff(COL, {"optimizers_config": "not-an-object"})
        transport_guard("leg3 format-invalid diff", st, raw)
        if st not in (400, 422):
            if 200 <= st < 300:
                defect("Type1_IllegalSuccess",
                       f"format-invalid diff {{optimizers_config: 'not-an-object'}} "
                       f"answered HTTP {st}; invalid diff must be refused 4xx "
                       f"(defect_type_if_violated=Type1_IllegalSuccess): {str(raw)[:300]!r}")
            defect("Type4_StateLogicViolation",
                   f"format-invalid diff answered HTTP {st} (expected 4xx "
                   f"400/422 per versioned OpenAPI): {str(raw)[:300]!r}")

        # ---- leg 4: invalid diff - out-of-range value (validation class) ----
        st, raw = patch_diff(COL, {"hnsw_config": {"ef_construct": 3}})
        transport_guard("leg4 value-invalid diff", st, raw)
        if st not in (400, 422):
            if 200 <= st < 300:
                defect("Type1_IllegalSuccess",
                       f"value-invalid diff hnsw_config.ef_construct=3 (below "
                       f"documented minimum 4) answered HTTP {st}; invalid diff "
                       f"must be refused 4xx: {str(raw)[:300]!r}")
            defect("Type4_StateLogicViolation",
                   f"value-invalid diff answered HTTP {st} (expected 4xx "
                   f"400/422 per versioned OpenAPI): {str(raw)[:300]!r}")
        print(f"[leg3/leg4 note] measured rejection statuses 400/422 are both "
              f"documented error responses in the versioned v-1-18-x OpenAPI; "
              f"the assertion's loose '400' wording is satisfied by either "
              f"(spec wins, R16)")

        # ---- leg 5: control - legal patch still 200 + echo after rejections ----
        st, raw = patch_diff(COL, LEGAL)
        transport_guard("leg5 control patch", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"control: legal PATCH on existing {COL} answered {st} after "
                   f"the rejection legs; rejections must be body-scoped: {str(raw)[:300]!r}")
        ef, err = get_hnsw_ef(COL)
        if err:
            script_error(f"leg5 echo readback failed: {err}")
        if ef != 64:
            defect("Type4_StateLogicViolation",
                   f"control leg echo lost: hnsw_config.ef_construct={ef} (sent "
                   f"64) - config echo must stay stable across rejection legs")

        print(f"OK: legal PATCH on {COL} -> 200 result:true with ef_construct=64 "
              f"echoed in describe (twice, stable); never-created {NEVER} -> 404 "
              f"twice without flapping; format-invalid and value-invalid diffs "
              f"refused with 4xx as documented")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
