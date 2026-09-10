#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_optimizations_002
# strategy: metamorphic
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift / behavioral-consistency detection -
#   three registry-tracking faces of the same collection namespace must agree
#   on which names exist; a name for which the optimizer-status face and the
#   describe face and the global listing disagree is the documented-behavior-
#   vs-implementation drift this blindspot covers)
"""
Attack: metamorphic (S6, cross-face registry equivalence) x
  qdrant_behavioral_collections_optimizations_001 on collections+optimizations
  (chunk_collections+optimizations unit
  assertions::qdrant_behavioral_collections_optimizations_001).
  [chunk coverage slot: "metamorphic registry relation x optimizations_001" -
  see _001's Attack block for the full chunk coverage list.]
Oracle: the registry relation R holds for every probe -
    optimizations(n)==HTTP 200  <=>  describe(n)==HTTP 200  <=>  n listed
    optimizations(n)==HTTP 404  <=>  describe(n)==HTTP 404  <=>  n not listed
  on (MR1) each self-created collection, (MR2) a never-created unique-prefix
  name, and (MR3) a collection immediately after its 200 delete ACK (the
  face must flip to 404 together with describe, never lagging or phantoming);
  any cross-face disagreement on a name - e.g. optimizations 200 while
  describe 404s or while the name is absent from the listing, or a lagging
  200 after the delete ACK - = Type4_StateLogicViolation; 5xx with /healthz
  alive = Type3_RuntimeFailure; transport failure with healthy /healthz or
  create/drop setup-premise failure = SCRIPT_ERROR (G8, never a defect).

Metamorphic relation under test (declared before measurement): the
  existence VALUE each registry-tracking face reports for the SAME name must
  agree at every observed moment. All three faces declare the same status
  semantics for missing names (collections+get and collections+optimizations
  both declare 404 "not found"; the listing simply has no row), so the
  relation compares status classes directly - there is no by-design face
  asymmetry here (G3: no near-difference trap).
Probes (G4 both directions on one setup):
  MR1 positive - two self-created collections: optimizations 200, describe
      200, listed exactly once (name-key parse of result.collections[].name -
      R11/R15 lessons; membership asserted only inside this script's unique
      prefix - sibling tolerance).
  MR2 negative - a never-created unique-prefix name: optimizations 404,
      describe 404, not listed.
  MR3 transient - collection B immediately after its 200 delete ACK (no
      settle delay; G6 mutation justification: the ACK-to-propagation window
      is where an async registry most easily drifts - a deleted collection
      whose optimizations face still answers 200 would be exactly that):
      optimizations(B) 404, describe(B) 404, B absent from the listing,
      while control A stays 200/200/listed.
Cross-face note: describe (collections+get, R14-covered) and list
  (collections+list, R15-covered) are corroborating oracles only; the unit
  under attack here remains the optimizations face.
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

# ---- runtime PATHS gap: register the contract-derived URL (raw_knowledge only) ----
OPT_KEY = "collection_optimizations"
if OPT_KEY not in rt.PATHS:
    rt.PATHS[OPT_KEY] = "/collections/{collection_name}/optimizations"
print(f"[path derivation] {OPT_KEY} = {rt.PATHS[OPT_KEY]} (raw_knowledge "
      f"api_endpoints[collections+optimizations].url); describe = "
      f"{rt.PATHS['describe_collection']}; list = {rt.PATHS['list_collections']}")

PFX = "sco02" + uuid.uuid4().hex[:6]
DIM = 4
A, B = PFX + "_a", PFX + "_b"
NEVER = PFX + "_never_" + uuid.uuid4().hex[:6]


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
    """G8 three-outcome isolation."""
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


def optim_face(name):
    """GET optimizations -> (status, raw)."""
    return safe_request("GET", OPT_KEY, path_params={"collection_name": name}, timeout=30)


def describe_face(name):
    """GET /collections/{name} (collections+get) -> (status, raw)."""
    return safe_request("GET", "describe_collection", path_params={"name": name}, timeout=30)


def listed_names():
    """result.collections[].name key extraction (R11/R15 lessons); None when
    the promised list is missing/unparseable."""
    st, raw = safe_request("GET", "list_collections", timeout=30)
    if st != 200:
        return st, None, raw
    body = jload(raw)
    res = body.get("result") if isinstance(body, dict) else None
    if isinstance(res, dict) and isinstance(res.get("collections"), list):
        names = [it.get("name") for it in res["collections"] if isinstance(it, dict)]
        return st, names, raw
    if isinstance(res, list):
        return st, res, raw
    return st, None, raw


def probe_one(name, expect_ok, tag):
    """Cross-face probe of one name. expect_ok=True: optimizations 200 and
    describe 200 and name listed. expect_ok=False: optimizations 404 and
    describe 404 and name NOT listed."""
    st_o, raw_o = optim_face(name)
    print(f"[{tag}] optimizations({name}) status={st_o} raw={str(raw_o)[:250]}")
    transport_guard(f"{tag} optimizations", st_o, raw_o)
    st_d, raw_d = describe_face(name)
    print(f"[{tag}] describe({name}) status={st_d} raw={str(raw_d)[:250]}")
    transport_guard(f"{tag} describe", st_d, raw_d)
    st_l, names, raw_l = listed_names()
    print(f"[{tag}] list status={st_l} prefix-scope-listed={name in (names or [])}")
    transport_guard(f"{tag} list", st_l, raw_l)
    if names is None:
        script_error(f"{tag}: list face 200 but promised array missing/unparseable: {str(raw_l)[:200]!r}")

    o_ok, d_ok = (st_o == 200), (st_d == 200)
    listed = name in names
    if expect_ok:
        if not (o_ok and d_ok and listed):
            defect("Type4_StateLogicViolation",
                   f"{tag}: registry disagreement for self-created {name} - "
                   f"optimizations 200?={o_ok}, describe 200?={d_ok}, listed?={listed}; "
                   f"relation R promises 200/200/listed (optimizations raw={str(raw_o)[:250]!r})")
    else:
        if not ((st_o == 404) and (st_d == 404) and not listed):
            defect("Type4_StateLogicViolation",
                   f"{tag}: registry disagreement for never-created/deleted {name} - "
                   f"optimizations status={st_o} (expect 404), describe status={st_d} "
                   f"(expect 404), listed?={listed} (expect False); relation R promises "
                   f"404/404/unlisted (optimizations raw={str(raw_o)[:250]!r})")


def cleanup():
    """Teardown: drop only collections created by this script; never-created
    names are never dropped. Cleanup failure must never fail the script."""
    for name in (A, B):
        try:
            rt.drop_collection(name)
        except Exception as e:
            print(f"cleanup warning (drop {name}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[assertion quote] existing collection: HTTP 200 with per-shard "
          "optimizer status; missing collection: HTTP 404")
    try:
        # ---- setup premise: two prefix-owned collections ----
        for name in (A, B):
            ok, err = rt.setup_default(name, dim=DIM, metric="Cosine")
            if not ok:
                script_error(f"premise create {name} failed: {err}")
        print(f"[setup] created {A} and {B}")

        # ---- MR1: existing members satisfy 200/200/listed ----
        probe_one(A, expect_ok=True, tag="MR1a")
        probe_one(B, expect_ok=True, tag="MR1b")

        # ---- MR2: never-created unique name satisfies 404/404/unlisted ----
        probe_one(NEVER, expect_ok=False, tag="MR2")

        # ---- MR3: immediately after the 200 delete ACK of B (no settle) ----
        st, raw = safe_request("DELETE", "drop_collection", path_params={"name": B},
                               query_params={"wait": "true"}, timeout=30)
        print(f"[MR3 delete ACK of {B}] status={st} raw={str(raw)[:200]}")
        transport_guard("MR3 delete", st, raw)
        if st not in (200, 201):
            script_error(f"premise delete of {B} failed: {st} {str(raw)[:200]}")
        probe_one(B, expect_ok=False, tag="MR3-deleted")
        probe_one(A, expect_ok=True, tag="MR3-control")

        print(f"OK: relation R held on every probe - existing {A}/{B} answered "
              f"optimizations 200 + describe 200 + listed; never-created {NEVER} and "
              f"deleted {B} answered optimizations 404 + describe 404 + unlisted; "
              f"control {A} unaffected after the delete ACK")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
