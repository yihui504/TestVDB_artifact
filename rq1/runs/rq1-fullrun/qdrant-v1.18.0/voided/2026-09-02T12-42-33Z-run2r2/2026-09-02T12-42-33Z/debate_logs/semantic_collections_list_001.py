#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_list_001
# strategy: behavioral_contract
# endpoint: collections+list
# constraint_ids: qdrant_behavioral_collections_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collections
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - API contract verification of the
#   global listing face: the published face promises HTTP 200 with an array of
#   {name} CollectionDescription entries; a face that answers non-200, wraps
#   the array somewhere else, or emits malformed/duplicate/phantom rows is
#   exactly the documented-behavior-vs-implementation drift this blindspot
#   covers)
"""
Attack: behavioral_contract (S1) x qdrant_behavioral_collections_list_001
  (chunk_collections+list unit assertions::qdrant_behavioral_collections_list_001;
  R-dispatch: "Global-face listing: prefix-filter your assertions (sibling
  tolerance); cleanup only your own prefixed collections").
  [chunk_collections+list coverage: behavioral_contract x list_001 = this
   script (_001); metamorphic state-transition x list_001 = _002;
   metamorphic name-fidelity/stability x list_001 = _003; diagnosis_quality +
   method-face graceful degradation x list_001 = _004. type_coercion /
   filter_semantics: no applicable typed request parameter exists on this
   GET face (raw_knowledge parameters = api-key header only) - not fabricated
   (G10 honest-report).]
Oracle: GET /collections returns HTTP 200 and result.collections is a JSON
  array whose EVERY entry (global, siblings included) is a well-formed
  {name: non-empty string} CollectionDescription; before any setup the unique
  prefix scope is empty, and after creating 3 prefix-owned collections each
  appears exactly once, byte-identical to its create-request name - non-200 on
  the legal GET = Type1_IllegalRejection, missing/unparseable array or a
  malformed entry = Type4_StateLogicViolation, a missing/duplicate/mutated
  prefix-scoped name = Type4_StateLogicViolation; 5xx with /healthz alive =
  Type3; transport failure with healthy /healthz or create setup failure =
  SCRIPT_ERROR (G8, never a defect).

Contract assertion qdrant_behavioral_collections_list_001
  (evidence_tier=explicit, endpoint level):
    expected_behavior: "HTTP 200 with a JSON array of collection descriptions
    (each with a name field)"
  endpoint_registry doc_quote: "Returns 200 with an array of {name}
  CollectionDescription entries."
  (source_url v-1-18-x api-reference get-collections.)

Legs (G4 positive/negative pairing on one setup):
  (1) baseline negative-closure - a fresh unique prefix scope must list empty
      (empty is the minimal legal instance of the promised array);
  (2) positive - a legal GET is accepted with 200 (rt.judge_200 face) and the
      payload carries the promised array at result.collections (published
      OpenAPI shape: raw_knowledge expected_responses 200 = "list", envelope
      result.collections[] with items parsed via the "name" key - R14 standing
      lesson; a bare result list (legacy envelope) is tolerated defensively);
  (3) endpoint-level shape - EVERY entry in the global array is an object with
      a non-empty string name (the {name}-entry promise is row-wise, not just
      prefix-scoped; sibling tolerance applies to membership, never to row
      shape);
  (4) prefix-scoped membership - the 3 self-created collections each appear
      exactly once with byte-identical names and no phantom prefix rows.

Shape-oracle precedence note (D3b-2): the contract's materialized
  api_endpoints[collections+list].response_shape grid is a mechanical-backfill
  artifact of the single-collection describe schema (result.config.* etc.) and
  carries no list-row key; the spec-derived sources (raw_knowledge OpenAPI
  expected_responses + the unit's own "array of {name}" promise) win, per the
  R14 standing lesson "shape oracles cross-checked against published OpenAPI".

Global-face sibling tolerance (dispatch instruction): membership assertions
  are scoped to this script's unique ownership prefix; concurrent sibling
  scripts may legitimately contribute their own rows to the same global list,
  so exact-equality is only ever asserted inside the prefix scope.
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

# listing face: runtime PATHS key list_collections, cross-checked against
# raw_knowledge api_endpoints[path=collections+list].url = /collections
LIST_KEY = "list_collections"
print(f"[path derivation] {LIST_KEY} = {rt.PATHS[LIST_KEY]} "
      f"(runtime PATHS; matches raw_knowledge api_endpoints[collections+list].url /collections)")

PFX = "scl01" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4
MEMBERS = (PFX + "_m1", PFX + "_m2", PFX + "_m3")
ASSERT = ("HTTP 200 with a JSON array of collection descriptions "
          "(each with a name field)")


def safe_request(method, path_key, **kw):
    """Thin delegation to rt.request (DB-neutral path_key; forwards body/
    path_params/query_params/timeout exactly - standing lesson)."""
    return rt.request(method, path_key, **kw)


def healthz_ladder(label, attempts=3, delay=2):
    """G8 liveness re-check: inline safe_request('GET','healthz') probes."""
    for i in range(attempts):
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"Type3_RuntimeFailure(service-down) - '{label}': /healthz unreachable "
            f"after {attempts} attempts")


def transport_gate(label, st, raw, findings):
    """Three-outcome isolation (G8): True if adjudicable, False after recording."""
    if st <= 0:
        v = healthz_ladder(label)
        if v:
            findings.append((1, v))
        else:
            findings.append((3, f"SCRIPT-ERROR-transport: '{label}' failed with healthy /healthz: {str(raw)[:150]}"))
        return False
    if 500 <= st <= 599:
        v = healthz_ladder(label)
        findings.append((1, v if v else
                         f"Type3_RuntimeFailure: '{label}' got {st} with /healthz alive; body: {str(raw)[:200]}"))
        return False
    return True


def list_face():
    """GET /collections -> (status, raw, entries_or_None).
    Key extraction per R8/R14 lessons: result.collections[].name; a bare
    result list (legacy envelope) is tolerated; anything else -> None."""
    st, raw = safe_request("GET", LIST_KEY, timeout=30)
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        b = None
    entries = None
    if isinstance(b, dict):
        res = b.get("result")
        if isinstance(res, dict) and isinstance(res.get("collections"), list):
            entries = res["collections"]
        elif isinstance(res, list):
            entries = res
    return st, raw, entries


def scoped_names(entries):
    """Name-key extraction inside this script's prefix scope (never
    str-membership on object elements - R8 lesson)."""
    out = []
    for it in entries or []:
        if isinstance(it, dict) and isinstance(it.get("name"), str) \
                and it["name"].startswith(PFX):
            out.append(it["name"])
    return out


def cleanup():
    """Teardown: drop only this script's prefixed collections; failure non-fatal."""
    for name in MEMBERS:
        try:
            rt.drop_collection(name)
        except Exception as e:
            print(f"cleanup warning (drop {name}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: GET /collections answered 200 with a well-formed array of "
          "{name} entries; the 3 prefix-owned collections each appear exactly "
          "once with byte-identical names and the fresh prefix scope listed "
          "empty at baseline")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[assertion quote] {ASSERT}")
    findings = []
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- leg 1: baseline - fresh prefix scope must list empty ----
        st, raw, entries = list_face()
        print(f"[baseline GET /collections] status={st} raw={str(raw)[:400]}")
        if not transport_gate("baseline list", st, raw, findings):
            finish(findings)
            return
        if entries is None:
            findings.append((2, "Type4_StateLogicViolation: baseline - the promised "
                                "array is missing/unparseable (expected result.collections "
                                "list per published OpenAPI + assertion 'JSON array of "
                                "collection descriptions'): "
                                f"{str(raw)[:250]!r}"))
            finish(findings)
            return
        base_scoped = scoped_names(entries)
        print(f"[baseline] global rows={len(entries)} prefix-scope={base_scoped}")
        if base_scoped:
            findings.append((2, f"Type4_StateLogicViolation: baseline - fresh unique "
                                f"prefix scope must be empty before any create, found "
                                f"phantom rows: {base_scoped}"))
            finish(findings)
            return

        # ---- setup: 3 prefix-owned collections ----
        for name in MEMBERS:
            ok, err = rt.setup_default(name, dim=DIM, metric="Cosine")
            if not ok:
                findings.append((3, f"SCRIPT-ERROR-setup: create {name} failed: {err}"))
                finish(findings)
                return
        print(f"[setup] created {len(MEMBERS)} prefix-owned collections")

        # ---- leg 2: positive - legal GET accepted with 200 ----
        st, raw, entries = list_face()
        print(f"[attack GET /collections] status={st} raw={str(raw)[:500]}")
        v = rt.judge_200(st, raw, setup_ok=True)
        if v == "SCRIPT_ERROR":
            if not transport_gate("attack list", st, raw, findings):
                finish(findings)
                return
        if v == "DEFECT_FOUND":
            findings.append((2, f"Type1_IllegalRejection: legal GET /collections "
                                f"rejected with status={st}: {str(raw)[:250]!r} "
                                f"(assertion expects HTTP 200)"))
            finish(findings)
            return
        if entries is None:
            findings.append((2, "Type4_StateLogicViolation: attack - HTTP 200 but the "
                                "promised array is missing/unparseable (expected "
                                "result.collections list): "
                                f"{str(raw)[:250]!r}"))
            finish(findings)
            return

        # ---- leg 3: endpoint-level row shape (global, sibling rows included) ----
        for i, it in enumerate(entries):
            if not isinstance(it, dict):
                findings.append((2, f"Type4_StateLogicViolation: global row #{i} is not "
                                    f"an object ({type(it).__name__}); the assertion "
                                    f"promises '{{name}} CollectionDescription' entries: "
                                    f"{it!r}"))
                break
            nm = it.get("name")
            if not isinstance(nm, str) or not nm:
                findings.append((2, f"Type4_StateLogicViolation: global row #{i} lacks "
                                    f"a non-empty string name field: {it!r}"))
                break
        if any(r == 2 for r, _ in findings):
            finish(findings)
            return
        print(f"[shape] all {len(entries)} global rows are well-formed {{name: str}} entries")

        # ---- leg 4: prefix-scoped membership, exactly-once, byte-identical echo ----
        got = scoped_names(entries)
        print(f"[membership] prefix-scope={sorted(got)} expected={sorted(MEMBERS)}")
        if len(got) != len(set(got)):
            dupes = sorted({n for n in got if got.count(n) > 1})
            findings.append((2, f"Type4_StateLogicViolation: duplicate rows for the "
                                f"same collection name in the listing: {dupes}"))
        missing = sorted(set(MEMBERS) - set(got))
        foreign = sorted(set(got) - set(MEMBERS))
        # a case-mutated echo shows up as missing+foreign under casefold equality
        case_mutated = sorted(
            n for n in foreign
            if n.casefold() in {m.casefold() for m in MEMBERS})
        phantom = sorted(n for n in foreign if n not in case_mutated)
        if missing and case_mutated:
            findings.append((2, f"Type4_StateLogicViolation: listed names deviate from "
                                f"the create-request spelling (case-mutated echo): "
                                f"created={missing} listed={case_mutated}"))
        elif missing:
            findings.append((2, f"Type4_StateLogicViolation: collections created (and "
                                f"ACKed) in this script missing from the listing: "
                                f"{missing} (assertion: every collection description "
                                f"is listed)"))
        if phantom:
            findings.append((2, f"Type4_StateLogicViolation: phantom prefix-scoped rows "
                                f"never created by this script: {phantom}"))
        finish(findings)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
