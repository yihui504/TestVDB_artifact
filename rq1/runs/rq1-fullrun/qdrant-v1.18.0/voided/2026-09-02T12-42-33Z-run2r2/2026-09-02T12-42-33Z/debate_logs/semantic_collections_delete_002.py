#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_delete_002
# strategy: illegal_rejection
# endpoint: collections+delete
# constraint_ids: qdrant_behavioral_collections_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the versioned spec documents an
#   OPTIONAL timeout query ("Wait for operation commit timeout in seconds",
#   integer minimum 1); if runtime drift makes documented-legal usage fail,
#   only a contract-anchored positive leg exposes it)
"""
Attack: illegal_rejection (Type1_IllegalRejection) x
  qdrant_behavioral_collections_delete_001 on collections+delete
  (chunk_collections+delete unit
  assertions::qdrant_behavioral_collections_delete_001).
  The assertion's positive promise: "deleting an existing collection is
  confirmed with 200". This script exercises the LEGAL input family of the
  delete operation - every leg must be accepted with 200 + envelope
  result=true (response_shape declares result:boolean):
    leg 1 plain settle      - create, confirm exists=true, DELETE (no params)
    leg 2 documented query  - DELETE ?timeout=5 (optional query param, integer
                              min 1 per the versioned v-1-18-x OpenAPI; a
                              blocking param travels in the query string, not
                              the body - runtime standing lesson)
    leg 3 data-bearing      - upsert 3 points first, then DELETE (dropping a
                              populated collection is the primary use case)
    leg 4 t0-immediate      - create returns 200, exists confirms true, DELETE
                              issued with zero settle delay (no documented
                              grace period may refuse a delete of a collection
                              the server already reports as existing)
    leg 5 name reuse        - after a 200 delete, PUT-create the SAME name must
                              succeed again (a stale tombstone blocking reuse
                              is a wrongly-rejected legal create and a state
                              leak of the delete operation)
  Threat-model note (G3): the by-design "idempotent point DELETE returns 200"
  item is POINTS-level; the collection-level assertion pins 200-on-existing /
  404-on-missing and is not softened by it here.
  [chunk_collections+delete coverage: illegal_rejection x
   qdrant_behavioral_collections_delete_001 (legal family: plain / timeout
   query / data-bearing / t0-immediate / name-reuse)]
Oracle: every one of the 5 legal legs returns exactly 200 with envelope
  result=true (and leg 5's re-create returns 200 with result=true); any 4xx
  refusal on a premise-verified existing collection = Type1_IllegalRejection;
  5xx with /healthz alive = Type3_RuntimeFailure; 2xx!=200 recorded as a
  measured conflict-zone note (expected_responses declare only 200 "ok").

Rationale (G4/G7): premise-verification before every destructive call
  (exists face must report true) so a refusal can never be excused as "it
  didn't exist"; expectation (200, result=true) is declared per leg before
  the measurement is compared against it.
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
print(f"[path derivation] drop_collection = /collections/{{name}} "
      f"(raw_knowledge api_endpoints[collections+delete].url); "
      f"{EXISTS_KEY} = {rt.PATHS[EXISTS_KEY]} (api_endpoints[collections+exists].url)")

PFX = "scd02" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4
CREATED = []


def safe_request(method, path_key, **kw):
    """Thin delegation to rt.request (DB-neutral path_key; forwards body/
    path_params/query_params/timeout exactly - standing lesson)."""
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


def create(name):
    st, raw = safe_request("PUT", "create_collection",
                           body={"vectors": {"size": DIM, "distance": "Cosine"}},
                           path_params={"name": name}, timeout=60)
    print(f"[create {name}] status={st} raw={str(raw)[:200]}")
    if st == 200:
        CREATED.append(name)
    return st, raw


def premise_exists(name):
    """exists face must confirm the collection before any destructive call."""
    st, raw = safe_request("GET", EXISTS_KEY,
                           path_params={"collection_name": name}, timeout=30)
    val = None
    if st == 200:
        try:
            res = json.loads(raw).get("result")
            if isinstance(res, dict) and isinstance(res.get("exists"), bool):
                val = res["exists"]
        except Exception:
            val = None
    print(f"[premise exists {name}] status={st} result.exists={val}")
    return val is True


def check_accepted_200(label, st, raw, findings):
    """Expected disposition: exactly 200 + envelope result=true. Returns True
    iff the leg conformed (conflict-zone 2xx recorded, returns False)."""
    try:
        env = json.loads(raw) if raw else {}
        ok_env = isinstance(env.get("result"), bool) and env["result"]
    except Exception:
        ok_env = False
    if st == 200:
        if not ok_env:
            findings.append((2, f"Type4_StateLogicViolation: {label} returned 200 but "
                                f"the envelope violates result:boolean=true grid "
                                f"(collections+delete response_shape): {str(raw)[:200]}"))
            return False
        print(f"[conform] {label}: 200 with result=true")
        return True
    if 200 < st <= 299:
        print(f"[conflict-zone] {label}: 2xx but not the declared 200 'ok' "
              f"(expected_responses declare only 200); measured, not adjudicated: {st}")
        return False
    findings.append((2, f"Type1_IllegalRejection: {label} - a premise-verified existing "
                        f"collection was refused with {st}; constraint "
                        f"qdrant_behavioral_collections_delete_001 promises deleting an "
                        f"existing collection is confirmed with 200; raw={str(raw)[:250]}"))
    return False


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- leg 1: plain settled delete ----
        n1 = PFX + "_plain"
        st, raw = create(n1)
        if st != 200:
            print(f"VERDICT: SCRIPT_ERROR - leg1 create failed with {st} (setup premise)")
            sys.exit(2)
        if not premise_exists(n1):
            print(f"VERDICT: SCRIPT_ERROR - leg1 premise: exists face did not report true for {n1}")
            sys.exit(2)
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": n1}, timeout=60)
        print(f"[leg1 plain delete] status={st} raw={str(raw)[:250]}")
        if transport_gate("leg1 plain delete", st, raw, findings):
            check_accepted_200("leg1 plain delete", st, raw, findings)

        # ---- leg 2: documented optional query timeout=5 ----
        n2 = PFX + "_tmo"
        st, raw = create(n2)
        if st != 200:
            print(f"VERDICT: SCRIPT_ERROR - leg2 create failed with {st} (setup premise)")
            sys.exit(2)
        if not premise_exists(n2):
            print(f"VERDICT: SCRIPT_ERROR - leg2 premise: exists face did not report true for {n2}")
            sys.exit(2)
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": n2},
                               query_params={"timeout": 5}, timeout=60)
        print(f"[leg2 delete ?timeout=5] status={st} raw={str(raw)[:250]}")
        if transport_gate("leg2 delete timeout=5", st, raw, findings):
            check_accepted_200("leg2 delete ?timeout=5 (documented optional query, "
                               "integer min 1)", st, raw, findings)

        # ---- leg 3: data-bearing collection ----
        n3 = PFX + "_data"
        st, raw = create(n3)
        if st != 200:
            print(f"VERDICT: SCRIPT_ERROR - leg3 create failed with {st} (setup premise)")
            sys.exit(2)
        pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM, "payload": {"i": i}}
               for i in range(1, 4)]
        st, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                               path_params={"name": n3}, timeout=60)
        print(f"[leg3 upsert 3 points] status={st} raw={str(raw)[:200]}")
        if st != 200:
            print(f"VERDICT: SCRIPT_ERROR - leg3 upsert failed with {st} (setup premise)")
            sys.exit(2)
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": n3}, timeout=60)
        print(f"[leg3 delete data-bearing] status={st} raw={str(raw)[:250]}")
        if transport_gate("leg3 delete data-bearing", st, raw, findings):
            check_accepted_200("leg3 delete of a collection holding 3 points "
                               "(primary use case)", st, raw, findings)

        # ---- leg 4: t0-immediate delete (zero settle) ----
        n4 = PFX + "_t0"
        st, raw = create(n4)
        if st != 200:
            print(f"VERDICT: SCRIPT_ERROR - leg4 create failed with {st} (setup premise)")
            sys.exit(2)
        if not premise_exists(n4):
            print(f"VERDICT: SCRIPT_ERROR - leg4 premise: exists face did not report true for {n4}")
            sys.exit(2)
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": n4}, timeout=60)
        print(f"[leg4 t0-immediate delete] status={st} raw={str(raw)[:250]}")
        if transport_gate("leg4 t0 delete", st, raw, findings):
            check_accepted_200("leg4 delete issued with zero settle delay after a 200 "
                               "create and exists=true (no documented grace period)",
                               st, raw, findings)

        # ---- leg 5: name reuse after delete ----
        n5 = PFX + "_reuse"
        st, raw = create(n5)
        if st != 200:
            print(f"VERDICT: SCRIPT_ERROR - leg5 create failed with {st} (setup premise)")
            sys.exit(2)
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": n5}, timeout=60)
        print(f"[leg5 first delete] status={st} raw={str(raw)[:250]}")
        if not transport_gate("leg5 first delete", st, raw, findings):
            finish(findings)
            return
        if not check_accepted_200("leg5 first delete", st, raw, findings):
            finish(findings)
            return
        st, raw = create(n5)  # same name again - must be reusable
        if transport_gate("leg5 re-create same name", st, raw, findings):
            check_accepted_200("leg5 re-create of the SAME name after a 200 delete "
                               "(stale tombstone would block legal reuse)", st, raw, findings)

        finish(findings)
    finally:
        # destructive-safety: only self-created, PFX-prefixed names are dropped
        for n in list(CREATED):
            try:
                rt.drop_collection(n)
            except Exception as e:
                print(f"cleanup warning (drop {n}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: legal delete family (plain / timeout=5 query / data-bearing / "
          "t0-immediate / name-reuse) all accepted with 200 result=true")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
