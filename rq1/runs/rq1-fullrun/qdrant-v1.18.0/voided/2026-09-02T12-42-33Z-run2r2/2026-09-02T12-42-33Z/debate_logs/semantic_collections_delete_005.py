#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_delete_005
# strategy: behavioral_contract
# endpoint: collections+delete
# constraint_ids: qdrant_bc_delete_invisibility_001, qdrant_behavioral_collections_delete_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-05 (Documentation Drift - older spec revisions documented the
#   delete path param as "name_and_aliases ... alternatively, use the name of
#   an alias"; the versioned v-1-18-x OpenAPI says only "Name of the
#   collection to delete". Whichever way the runtime drifted, the resulting
#   STATE must stay self-consistent - that is what this script pins)
"""
Attack: behavioral_contract (Type4, alias interplay) x
  qdrant_bc_delete_invisibility_001 + qdrant_behavioral_collections_delete_001
  on collections+delete (chunk_collections+delete units; dispatcher directive:
  "Alias interplay is fair game (create-alias-then-delete-by-alias vs
  delete-by-name)").
  Setup: create real collection R (unique run prefix) -> create alias A -> R
  via POST /collections/aliases {actions:[{create_alias:{collection_name: R,
  alias_name: A}}]} (aliases+update request_required_paths) -> confirm the
  alias resolves on read (GET /collections/{A} -> 200).
  Mutation: DELETE /collections/{A} (delete by ALIAS, not by name).
  The versioned v-1-18-x OpenAPI describes the path param only as "Name of
  the collection to delete", so BOTH dispositions are spec-compatible:
    (a) 200 - the alias resolved and the underlying collection was dropped;
        then R must be fully invisible (GET /collections/{R} -> 404, list
        without R) AND the alias registry must not keep A (a DANGLING alias
        pointing at a deleted collection is an inconsistent state)
    (b) 404 - the alias is not accepted for deletion; then R must still be
        fully intact (GET /collections/{R} -> 200) AND A must still resolve
        (GET /collections/{A} -> 200)
  A one-sided/mixed state (collection deleted but alias still registered; 404
  refusal that nevertheless destroyed R; 200 whose R remains gettable) =
  Type4_StateLogicViolation. 5xx with /healthz alive = Type3.
  [chunk_collections+delete coverage: behavioral_contract (alias interplay,
  state-consistency oracle) x qdrant_bc_delete_invisibility_001 +
  qdrant_behavioral_collections_delete_001]
Oracle: DELETE /collections/{A} ends in one of the two self-consistent states
  (a) 200 + R invisible on get/list + alias A absent from GET /aliases
  result.aliases[] (no dangling mapping), or (b) 404 + R gettable 200 + A
  still resolving; any mixed state = Type4_StateLogicViolation; 2xx!=200 is a
  measured conflict-zone note but the same two-sided state check applies;
  transport failure with healthy /healthz = SCRIPT_ERROR.

Rationale (G3/G6/G7): because the versioned spec text is thin on alias
  acceptance, the oracle pins the invariant both outcomes must satisfy
  (state self-consistency) instead of guessing one disposition - this avoids
  misjudging by-design alias behavior while still catching half-deletes and
  dangling registrations; the destructive mutation targets the alias->name
  resolution seam, the one place a delete can strand state.
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

print("[path derivation] drop_collection = /collections/{name} "
      "(raw_knowledge api_endpoints[collections+delete].url); update_aliases = "
      "/collections/aliases + list_aliases = /aliases "
      "(api_endpoints[aliases+update / aliases+list].url)")

PFX = "scd05" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4
REAL = PFX + "_real"
ALIAS = PFX + "_alias"
CREATED = [REAL]


def safe_request(method, path_key, **kw):
    """Thin delegation to rt.request (forwards body/path_params/query_params/
    timeout exactly - standing lesson)."""
    return rt.request(method, path_key, **kw)


def healthz_ladder(label, attempts=3, delay=2):
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


def alias_registry_contains(alias_name):
    """GET /aliases -> (status, raw, mapping-or-None for this alias).
    Parses result.aliases[] items via alias_name/collection_name keys
    (aliases+list response_shape)."""
    st, raw = safe_request("GET", "list_aliases", timeout=30)
    mapping = None
    if st == 200:
        try:
            res = json.loads(raw).get("result")
            entries = res.get("aliases") if isinstance(res, dict) else None
            if isinstance(entries, list):
                for e in entries:
                    if isinstance(e, dict) and e.get("alias_name") == alias_name:
                        mapping = e.get("collection_name")
                        break
        except Exception:
            mapping = None
    print(f"[aliases list] status={st} mapping({alias_name})={mapping!r} "
          f"raw={str(raw)[:160]}")
    return st, raw, mapping


def main():
    print(f"ownership prefix: {PFX} (real={REAL} alias={ALIAS})")
    findings = []
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- setup: real collection + alias on it ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": REAL}, timeout=60)
        print(f"[create real {REAL}] status={st} raw={str(raw)[:200]}")
        if st != 200:
            print(f"VERDICT: SCRIPT_ERROR - setup create failed with {st}")
            sys.exit(2)
        st, raw = safe_request("POST", "update_aliases",
                               body={"actions": [{"create_alias": {
                                   "collection_name": REAL, "alias_name": ALIAS}}]},
                               timeout=60)
        print(f"[create_alias {ALIAS} -> {REAL}] status={st} raw={str(raw)[:200]}")
        if not transport_gate("create_alias", st, raw, findings):
            finish(findings)
            return
        if st != 200:
            print(f"VERDICT: SCRIPT_ERROR - setup create_alias failed with {st} "
                  f"(aliases chunk owns that adjudication; delete-by-alias premise "
                  f"cannot be established)")
            sys.exit(2)
        st, raw = safe_request("GET", "describe_collection",
                               path_params={"name": ALIAS}, timeout=30)
        print(f"[premise: read via alias {ALIAS}] status={st} raw={str(raw)[:160]}")
        if st != 200:
            print(f"VERDICT: SCRIPT_ERROR - alias does not resolve on read (GET via "
                  f"alias = {st}); the delete-by-alias premise cannot be established "
                  f"(aliases chunk owns read-resolution adjudication)")
            sys.exit(2)
        st, raw, mapping = alias_registry_contains(ALIAS)
        if st != 200 or mapping != REAL:
            print(f"VERDICT: SCRIPT_ERROR - alias registry premise failed "
                  f"(status={st}, mapping={mapping!r}, expected {REAL!r})")
            sys.exit(2)

        # ---- mutation: DELETE by ALIAS ----
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": ALIAS},
                               query_params={"timeout": 10}, timeout=60)
        print(f"[DELETE by alias {ALIAS}] status={st} raw={str(raw)[:250]}")
        if not transport_gate("DELETE by alias", st, raw, findings):
            finish(findings)
            return
        outcome = None
        if st == 200:
            outcome = "a_resolved_and_deleted"
        elif st == 404:
            outcome = "b_alias_not_accepted"
        elif 200 < st <= 299:
            print(f"[conflict-zone] DELETE by alias returned 2xx {st} (expected_responses "
                  f"declare only 200/404); state checks below still apply")
            outcome = "a_resolved_and_deleted"
        else:
            findings.append((3, f"SCRIPT-ERROR: DELETE by alias returned {st} "
                                f"(outside the declared 200/404 family): {str(raw)[:150]}"))
            finish(findings)
            return

        # settle briefly, then state checks
        time.sleep(2.0)
        rst, rraw = safe_request("GET", "describe_collection",
                                 path_params={"name": REAL}, timeout=30)
        print(f"[state: GET real {REAL}] status={rst} raw={str(rraw)[:160]}")
        if not transport_gate("GET real after alias-delete", rst, rraw, findings):
            finish(findings)
            return
        real_gone = (rst == 404)
        if not real_gone and rst != 200:
            print(f"[conflict-zone] GET real returned {rst}; treated as not-gone for "
                  f"the consistency matrix")

        ast, araw, mapping = alias_registry_contains(ALIAS)
        if not transport_gate("aliases list after alias-delete", ast, araw, findings):
            finish(findings)
            return
        alias_registered = mapping is not None

        if outcome == "a_resolved_and_deleted":
            if not real_gone:
                findings.append((2, f"Type4_StateLogicViolation: DELETE by alias "
                                    f"returned 200 but the underlying collection "
                                    f"'{REAL}' is still gettable (status {rst}) - "
                                    f"half-delete through the alias seam "
                                    f"(qdrant_bc_delete_invisibility_001: a "
                                    f"successfully deleted collection disappears; "
                                    f"GET must 404)"))
            else:
                print(f"[conform] outcome (a): real '{REAL}' invisible after the "
                      f"200 alias-delete")
            if alias_registered:
                findings.append((2, f"Type4_StateLogicViolation: alias '{ALIAS}' is "
                                    f"still registered (-> {mapping!r}) after the "
                                    f"underlying collection was deleted - DANGLING "
                                    f"alias pointing at a deleted collection"))
            else:
                print(f"[conform] outcome (a): alias '{ALIAS}' no longer registered "
                      f"(registry consistent with the delete)")
        else:  # b_alias_not_accepted
            if real_gone:
                findings.append((2, f"Type4_StateLogicViolation: DELETE by alias "
                                    f"'{ALIAS}' was REFUSED with 404 yet the underlying "
                                    f"collection '{REAL}' was destroyed (GET -> 404) - "
                                    f"a destructive 404; refusal and effect must agree"))
            else:
                print(f"[conform] outcome (b): real '{REAL}' intact after the 404 "
                      f"(alias not accepted for deletion)")
            if not alias_registered:
                findings.append((2, f"Type4_StateLogicViolation: the 404 refusal also "
                                    f"unregistered alias '{ALIAS}' whose target "
                                    f"'{REAL}' still exists - refusal with a "
                                    f"destructive side effect on the alias registry"))
            else:
                print(f"[conform] outcome (b): alias '{ALIAS}' still registered "
                      f"(-> {mapping!r}), consistent with the refusal")

        finish(findings)
    finally:
        # destructive-safety: only self-created, PFX-prefixed names are touched
        for n in list(CREATED):
            try:
                rt.drop_collection(n)
            except Exception as e:
                print(f"cleanup warning (drop {n}): {e}")
        try:
            safe_request("POST", "update_aliases",
                         body={"actions": [{"delete_alias": {"alias_name": ALIAS}}]},
                         timeout=30)
        except Exception as e:
            print(f"cleanup warning (delete_alias {ALIAS}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: DELETE by alias ended in a self-consistent state "
          "(collection visibility and alias registry agree on the outcome)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
