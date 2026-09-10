#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_exists_005
# strategy: illegal_rejection
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - documented-legal names failing on
#   one face while the create face accepted them is exactly the drift between
#   the documented universal collection_name grammar and per-face validation)
"""
Attack: illegal_rejection (S3, Type-1 reverse) x
  qdrant_behavioral_collections_exists_001 on collections+exists
  (chunk_collections+exists unit
  assertions::qdrant_behavioral_collections_exists_001). Not "is illegal
  input accepted" but "is LEGAL input wrongly rejected". The legal family is
  shape-generalized (G3: the same parameter family, not one case): every
  name below that the CREATE face accepts is by construction a legal
  collection_name, and the exists face must answer it with 200 +
  result.exists=true:
    c1 plain control    - ordinary PFX-prefixed name
    c2 long-63          - exactly 63 chars (in-family length stress)
    c3 digits+hyphens   - mixed-grammar name
    c4-c6 routing edges - collections literally named "points", "exists",
                          "aliases": GET /collections/points/exists etc.
                          must route to the exists handler with
                          collection_name="points" - a router that treats
                          the literal segment as another route's keyword
                          wrongly rejects a create-verified legal name
  Negative pairing (G4): for each candidate X the name X+"0g" is never
  created and must be answered 200 + result.exists=false (never 404 -
  the assertion's in-body-existence clause makes answering these names the
  endpoint's documented job, so a refusal is a wrongly-rejected legal
  request, Type1).
  Ownership guard: the routing-edge names are not PFX-prefixed, so each is
  created only if ABSENT from the collections list at setup (never touches
  another script's collection), and every created name is dropped in the
  finally block. If the create face rejects a candidate, that name is not
  legal on this deployment -> leg skipped with a printed note (G3, no
  fabrication), and the remaining legs still adjudicate.
  [chunk_collections+exists coverage: illegal_rejection x
   qdrant_behavioral_collections_exists_001 (legal-name family incl.
   routing-edge segment names + never-created negative pairing) - this
   script; core truthfulness+shape = _001; alias interplay = _002;
   cross-face equivalence = _003; error-body quality = _004]
Oracle: every create-verified candidate returns 200 with result.exists
  boolean True from the exists face; every never-created X+"0g" twin
  returns 200 with result.exists boolean False; any 4xx (incl. 404 - the
  never-404 clause) or other non-200 on these legal-format names =
  Type1_IllegalRejection; result.exists=false on a create-verified name or
  true on a never-created twin = Type4_StateLogicViolation (untruthful);
  create-face rejection of a candidate = skip-with-note (legality not
  established, nothing fabricated); 5xx with /healthz alive = Type3;
  transport failure with healthy /healthz = SCRIPT_ERROR (G8).

Rationale (G3/G4/G9): legality is established empirically per candidate by
  the create face itself (the strongest available contract anchor for
  "this is a legal collection_name"), and the same parameter is then probed
  on the exists face - an asymmetry between the two faces of one parameter
  is the face-consistency defect signal, with the negative twins proving
  the exists face distinguishes existence rather than name grammar.
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

PFX = "sce05" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
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
    """-> (status, exists_value_or_None, raw)"""
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


def list_names():
    """GET /collections -> names list or None (key extraction first, R11)."""
    st, raw = safe_request("GET", "list_collections", timeout=30)
    if st != 200:
        return None
    try:
        res = json.loads(raw).get("result")
        colls = res.get("collections") if isinstance(res, dict) else None
        if isinstance(colls, list):
            return [c.get("name") for c in colls if isinstance(c, dict)]
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        pass
    return None


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    long63 = (PFX + "-L-")[:11].ljust(63, "a")  # exactly 63 chars
    candidates = [
        ("c1 plain control", PFX + "_ctl"),
        ("c2 long-63", long63),
        ("c3 digits+hyphens", PFX + "-123-abc-456"),
        ("c4 routing-edge 'points'", "points"),
        ("c5 routing-edge 'exists'", "exists"),
        ("c6 routing-edge 'aliases'", "aliases"),
    ]
    created = []
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        names = list_names()
        if names is None:
            print("VERDICT: SCRIPT_ERROR - collections list unparseable (ownership guard)")
            sys.exit(2)

        for label, name in candidates:
            print(f"---- {label}: {name!r} (len={len(name)}) ----")
            if not name.startswith(PFX) and name in names:
                print(f"[skip-note] {label}: '{name}' already exists and is not "
                      f"owned by this script (ownership guard) - leg skipped (G3)")
                continue
            st, raw = safe_request("PUT", "create_collection",
                                   body={"vectors": {"size": DIM, "distance": "Cosine"}},
                                   path_params={"name": name}, timeout=60)
            print(f"[create {name}] status={st} raw={str(raw)[:200]}")
            if not transport_gate(f"create {label}", st, raw, findings):
                continue
            if st not in (200, 201):
                print(f"[skip-note] {label}: create face rejected the candidate "
                      f"({st}) - legality not established on this deployment; "
                      f"exists leg not fabricated (G3): {str(raw)[:150]}")
                continue
            created.append(name)

            # positive: create-verified legal name must be answered 200/true
            est, ev, eraw = exists_val(name)
            print(f"[exists {name}] status={est} result.exists={ev!r} raw={str(eraw)[:200]}")
            if not transport_gate(f"exists {label}", est, eraw, findings):
                continue
            if est != 200:
                findings.append((2, f"Type1_IllegalRejection: {label} - the create "
                                    f"face accepted {name!r} but the exists face "
                                    f"returned HTTP {est}; answering legal-format "
                                    f"names in-body (200, never 404) is the "
                                    f"endpoint's documented job "
                                    f"(qdrant_behavioral_collections_exists_001): "
                                    f"{str(eraw)[:200]!r}"))
            elif ev is not True:
                findings.append((2, f"Type4_StateLogicViolation: {label} - "
                                    f"create-verified name {name!r} answered 200 "
                                    f"with result.exists={ev!r} (untruthful): "
                                    f"{str(eraw)[:200]!r}"))
            else:
                print(f"[conform] {label}: 200 with result.exists=true")

            # negative pairing: the never-created twin must be 200/false
            twin = name + "0g"
            est, ev, eraw = exists_val(twin)
            print(f"[exists twin {twin}] status={est} result.exists={ev!r} raw={str(eraw)[:200]}")
            if not transport_gate(f"exists twin {label}", est, eraw, findings):
                continue
            if est != 200:
                findings.append((2, f"Type1_IllegalRejection: {label} twin - the "
                                    f"never-created but legal-format name {twin!r} "
                                    f"was refused with HTTP {est} instead of the "
                                    f"documented 200 in-body false answer "
                                    f"(never-404 clause): {str(eraw)[:200]!r}"))
            elif ev is not False:
                findings.append((2, f"Type4_StateLogicViolation: {label} twin - "
                                    f"never-created name {twin!r} answered 200 "
                                    f"with result.exists={ev!r} (phantom): "
                                    f"{str(eraw)[:200]!r}"))
            else:
                print(f"[conform] {label} twin: 200 with result.exists=false")

        finish(findings)
    finally:
        # destructive-safety: drop only collections this script created
        for n in list(created):
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
    print("OK: every create-verified legal name (incl. routing-edge segment "
          "names points/exists/aliases) is answered 200+true, and every "
          "never-created legal-format twin 200+false - no legal input wrongly "
          "rejected on the exists face")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
