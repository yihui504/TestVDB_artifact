#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_exists_002
# strategy: behavioral_contract
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift / behavioral-consistency - the read
#   face is documented to resolve aliases, so existence by alias must track
#   the alias map; a face that resolves aliases for details but not for
#   existence - or a stale alias yielding phantom existence - is exactly the
#   documented-behavior-vs-implementation drift this blindspot covers)
"""
Attack: behavioral_contract (S1, alias-interplay variant) x
  qdrant_behavioral_collections_exists_001 on collections+exists
  (chunk_collections+exists unit
  assertions::qdrant_behavioral_collections_exists_001; R13 dispatch:
  "alias interplay is fair game - exists-by-alias semantics; the read face
  resolves aliases"). The assertion under test, quoted:
    "HTTP 200 with result being an object of shape {exists: bool}; a missing
     collection yields result.exists=false with HTTP 200 (never 404)"
  Applied to names that reach a collection ONLY through an alias:
    leg 0 premise     - create collection C; exists(C)=200/True
    leg 1 phantom     - exists(alias1) BEFORE any alias exists -> 200/False
                        (a True here is phantom existence)
    leg 2 resolution  - create_alias alias1->C; exists(alias1) must be
                        200 + result.exists=True (the read face resolves
                        aliases; false-negative here = alias ignored, 404 =
                        never-404 clause violated on an alias-routed name)
    leg 3 unlinked    - delete_alias alias1; exists(alias1) must be 200 +
                        False (the name no longer resolves; never 404)
    leg 4 stale       - create_alias alias2->C, then DELETE collection C
                        (with the alias still live). exists(alias2) must be
                        200 + False: no phantom existence through a stale
                        alias, and no 404 either. If the drop of C is
                        refused while an alias points at it, that refusal is
                        the DELETE face's documented right (boundary lane) -
                        leg 4 is skipped with a printed note, not a defect.
  G3 avoidance note: qdrant_behavioral_aliases_update_001 documents 404 for
  create_alias of a MISSING collection, so "alias -> never-existing target"
  cannot be constructed through the API and is not probed here.
  [chunk_collections+exists coverage: behavioral_contract x
   qdrant_behavioral_collections_exists_001 (alias interplay: resolution /
   unlinked / stale-alias legs) - this script; core truthfulness+shape =
   _001; cross-face equivalence = _003; error-body quality = _004;
   legal-name family = _005]
Oracle: exists(alias1) is 200+True only while alias1->C is live; 200+False
  before the alias exists, after delete_alias, and after the target
  collection's 200 delete (stale alias); any 404 on the exists face in these
  legs = Type4_StateLogicViolation (never-404 clause violated for an
  alias-routed name); exists=true through a stale/deleted alias or on a
  not-yet-existing alias = Type4 (phantom existence); exists=false on a live
  alias->live collection = Type4 (false negative - alias not resolved by the
  read face); alias setup/delete premise failures = SCRIPT_ERROR; 5xx with
  /healthz alive = Type3 (G8).

Rationale (G4/G6/G9): leg 1 is the negative control that makes leg 2's True
  attributable to alias resolution rather than phantom naming; leg 4's
  mutation (dropping the target while keeping the alias) is the most
  destructive point for an existence cache - it decouples the alias map from
  the collection state at the exact moment the read face must reconcile
  them, which is where a resolution cache most easily goes stale.
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

# exists face: URL registered verbatim from raw_knowledge api_endpoints
# [path=collections+exists].url (the runtime PATHS table has no key for it)
EXISTS_KEY = "collection_exists"
EXISTS_URL = "/collections/{collection_name}/exists"
if EXISTS_KEY not in rt.PATHS:
    rt.PATHS[EXISTS_KEY] = EXISTS_URL
print(f"[path derivation] {EXISTS_KEY} = {rt.PATHS[EXISTS_KEY]} "
      f"(raw_knowledge api_endpoints[collections+exists].url)")

PFX = "sce02" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4


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


def exists_val(name):
    """GET exists -> (status, exists_value, raw); exists_value is the boolean
    result.exists when the grid is honored, else None."""
    st, raw = safe_request("GET", EXISTS_KEY,
                           path_params={"collection_name": name}, timeout=30)
    val = None
    if st == 200:
        try:
            res = json.loads(raw).get("result")
            if isinstance(res, dict) and isinstance(res.get("exists"), bool):
                val = res["exists"]
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            val = None
    return st, val, raw


def judge_leg(label, name, st, val, raw, expected, findings):
    """Declare-then-compare for one alias-routed exists leg."""
    print(f"[{label}] name={name!r} status={st} result.exists={val!r} raw={str(raw)[:220]}")
    if st != 200:
        findings.append((2, f"Type4_StateLogicViolation: {label} - exists face "
                            f"returned HTTP {st} for alias-routed name {name!r}; "
                            f"qdrant_behavioral_collections_exists_001 requires "
                            f"200 with existence in the body (never 404): "
                            f"{str(raw)[:200]!r}"))
        return
    if val is not expected:
        got = "phantom existence" if val is True else \
              ("false negative (alias not resolved by the read face)" if expected is True
               else "untruthful value")
        findings.append((2, f"Type4_StateLogicViolation: {label} - result.exists="
                            f"{val!r} but ground truth is {expected!r} for {name!r} "
                            f"({got}): {str(raw)[:200]!r}"))
        return
    print(f"[conform] {label}: 200 with result.exists={val!r}")


def alias_action(action, findings, label):
    """POST one aliases+update action; returns True on 200 result=true."""
    st, raw = safe_request("POST", "update_aliases",
                           body={"actions": [action]}, timeout=30)
    print(f"[{label}] status={st} raw={str(raw)[:220]}")
    if not transport_gate(label, st, raw, findings):
        return False
    ok = False
    try:
        env = json.loads(raw) if raw else {}
        ok = isinstance(env.get("result"), bool) and env["result"]
    except (json.JSONDecodeError, ValueError, TypeError):
        ok = False
    if st != 200 or not ok:
        findings.append((3, f"SCRIPT-ERROR-setup: alias action '{label}' returned "
                            f"{st} (envelope ok={ok}); alias premise broken: {str(raw)[:150]}"))
        return False
    return True


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    real = PFX + "_real"     # the underlying collection
    al1 = PFX + "_al1"       # alias for resolution/unlinked legs
    al2 = PFX + "_al2"       # alias kept live across the target drop
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- leg 0 premise: create C, exists(C)=true ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": real}, timeout=60)
        print(f"[create {real}] status={st} raw={str(raw)[:200]}")
        if not transport_gate("create real", st, raw, findings):
            finish(findings)
            return
        if st not in (200, 201):
            findings.append((3, f"SCRIPT-ERROR-setup: create returned {st}: {str(raw)[:150]}"))
            finish(findings)
            return
        st, val, raw = exists_val(real)
        judge_leg("leg 0 premise direct name", real, st, val, raw, True, findings)
        if any(r != 0 for r, _ in findings):
            finish(findings)
            return

        # ---- leg 1 phantom guard: exists(al1) BEFORE the alias exists ----
        st, val, raw = exists_val(al1)
        judge_leg("leg 1 pre-alias phantom guard", al1, st, val, raw, False, findings)

        # ---- leg 2: live alias must resolve to true ----
        if not alias_action({"create_alias": {"collection_name": real, "alias_name": al1}},
                            findings, f"create_alias {al1}->{real}"):
            finish(findings)
            return
        st, val, raw = exists_val(al1)
        judge_leg("leg 2 live alias resolution", al1, st, val, raw, True, findings)

        # ---- leg 3: after delete_alias the name must answer false (200) ----
        if not alias_action({"delete_alias": {"alias_name": al1}},
                            findings, f"delete_alias {al1}"):
            finish(findings)
            return
        st, val, raw = exists_val(al1)
        judge_leg("leg 3 unlinked alias", al1, st, val, raw, False, findings)

        # ---- leg 4: stale alias after the target collection is dropped ----
        if not alias_action({"create_alias": {"collection_name": real, "alias_name": al2}},
                            findings, f"create_alias {al2}->{real}"):
            finish(findings)
            return
        st, val, raw = exists_val(al2)
        judge_leg("leg 4a alias2 live before drop", al2, st, val, raw, True, findings)
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": real}, timeout=120)
        print(f"[drop {real} with live alias {al2}] status={st} raw={str(raw)[:220]}")
        if not transport_gate("drop real (stale-alias leg)", st, raw, findings):
            finish(findings)
            return
        if st != 200:
            print(f"[note] drop of an alias-bearing collection returned {st} - "
                  f"disposition belongs to the boundary lane; leg 4b skipped (G3)")
        else:
            st, val, raw = exists_val(al2)
            judge_leg("leg 4b stale alias after target drop", al2, st, val, raw, False, findings)

        finish(findings)
    finally:
        # cleanup: remove self-created aliases best-effort, then the collection
        for al in (al1, al2):
            try:
                safe_request("POST", "update_aliases",
                             body={"actions": [{"delete_alias": {"alias_name": al}}]},
                             timeout=15)
            except Exception as e:
                print(f"cleanup warning (delete_alias {al}): {e}")
        try:
            rt.drop_collection(real)
        except Exception as e:
            print(f"cleanup warning (drop {real}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: existence by alias is truthful on the read face - 200/true only "
          "while alias->live collection; 200/false before the alias exists, "
          "after delete_alias and across a stale alias (never 404)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
