#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_get_006
# strategy: illegal_rejection
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - documented-legal names failing on
#   the describe face while the create face accepted them is exactly the
#   drift between the documented universal collection_name grammar and
#   per-face/per-route validation; the "aliases" candidate additionally
#   probes route shadowing: GET /collections/aliases shares its path space
#   with POST /collections/aliases)
"""
Attack: illegal_rejection (S3, Type-1 reverse) x
  qdrant_behavioral_collections_get_001 on collections+get
  (chunk_collections+get unit
  assertions::qdrant_behavioral_collections_get_001). Not "is illegal
  input accepted" but "is LEGAL input wrongly rejected". The legal family
  is shape-generalized (G3): every name below that the CREATE face
  accepts is by construction a legal collection_name, and the assertion's
  positive branch ("existing collection: HTTP 200 with resolved config")
  obliges the describe face to answer it with 200 + a config object:
    c1 plain control    - ordinary PFX-prefixed name
    c2 long-63          - exactly 63 chars (in-family length stress)
    c3 digits+hyphens   - mixed-grammar name
    c4-c6 routing edges - collections literally named "aliases", "points",
                          "exists": GET /collections/aliases shares its
                          path space with the POST alias-update route, and
                          all three segment values are other endpoints'
                          keywords - a router that treats the literal
                          segment as a keyword wrongly rejects a
                          create-verified legal name
  Negative pairing (G4, twin construction): for each candidate X the twin
  X[:-2]+"0g" (same length, same character classes, same grammar family,
  never created) must be answered 404 per the assertion's miss branch -
  200-with-config = Type1_IllegalSuccess (never-200 clause), and any
  OTHER non-404 status on the twin = inconsistent disposition within one
  grammar family (G9: create accepted X's grammar, describe 404s X, so a
  400/422 on the same-grammar twin is a family-internal asymmetry =
  Type4).
  Ownership guard: the routing-edge names are not PFX-prefixed, so each
  is created only if ABSENT from the collections list at setup (never
  touches another script's collection), and every created name is
  dropped in the finally block. If the create face rejects a candidate,
  that name's legality is not established -> leg skipped with a printed
  note (G3, no fabrication); the remaining legs still adjudicate.
  Corroboration: on a failed describe leg the exists face's answer is
  printed as supporting evidence (registering the exists URL verbatim
  from raw_knowledge as in R13) - it corroborates but never replaces the
  describe oracle.
  [chunk_collections+get coverage: illegal_rejection x
   qdrant_behavioral_collections_get_001 (legal-name family incl.
   routing-edge segment names + same-grammar never-created twins) - this
  script; 200-full-config grid vs 404 = _001; config-echo = _002; counter
   truthfulness = _003; metamorphic alias equivalence = _004; error-body
   quality = _005]
Oracle: every create-verified candidate returns 200 with result an
  object and result.config an object from the describe face - any 4xx
  (incl. 404) or other non-200 on these legal, existing names =
  Type1_IllegalRejection (the assertion's existing-collection branch is
  violated); a 200 whose result/config is not an object = Type4 (grid:
  result=object); every never-created same-grammar twin returns 404 -
  200-with-config = Type1_IllegalSuccess (never-200 clause), any other
  status = Type4 (inconsistent disposition within the accepted grammar
  family, G9); create-face rejection of a candidate = skip-with-note;
  5xx with /healthz alive = Type3; transport failure with healthy
  /healthz = SCRIPT_ERROR (G8).

Rationale (G3/G4/G9): legality is established empirically per candidate
  by the create face itself (the strongest available contract anchor for
  "this is a legal collection_name"), the twins differ from their
  candidates only in trailing characters of the same classes (so a twin's
  non-404 cannot be excused by grammar), and the routing-edge names
  target the one systematic way a read face rejects legal names - route
  keyword collision - rather than re-testing the create lane's own
  matrix.
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

# describe face: runtime PATHS key describe_collection, cross-checked against
# raw_knowledge api_endpoints[path=collections+get].url = /collections/{collection_name}
DESCRIBE_KEY = "describe_collection"
print(f"[path derivation] {DESCRIBE_KEY} = {rt.PATHS[DESCRIBE_KEY]} "
      f"(runtime PATHS; matches raw_knowledge api_endpoints[collections+get].url "
      f"/collections/{{collection_name}})")

# exists face (corroboration probe only): URL registered verbatim from
# raw_knowledge api_endpoints[path=collections+exists].url (R13 lesson)
EXISTS_KEY = "collection_exists"
EXISTS_URL = "/collections/{collection_name}/exists"
if EXISTS_KEY not in rt.PATHS:
    rt.PATHS[EXISTS_KEY] = EXISTS_URL
print(f"[path derivation] {EXISTS_KEY} = {rt.PATHS[EXISTS_KEY]} "
      f"(raw_knowledge api_endpoints[collections+exists].url; corroborating "
      f"probe only, never the adjudicator)")

PFX = "scg06" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
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


def describe_status(name):
    """GET /collections/{name} -> (status, raw, result_or_None)."""
    st, raw = safe_request("GET", DESCRIBE_KEY,
                           path_params={"name": name}, timeout=30)
    try:
        env = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        env = None
    res = env.get("result") if isinstance(env, dict) else None
    return st, raw, res


def exists_probe(name):
    """Corroborating exists probe -> printable evidence string."""
    st, raw = safe_request("GET", EXISTS_KEY,
                           path_params={"collection_name": name}, timeout=15)
    val = None
    if st == 200:
        try:
            res = json.loads(raw).get("result")
            if isinstance(res, dict):
                val = res.get("exists")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            val = None
    return f"exists({name!r}) -> HTTP {st}, result.exists={val!r}"


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
    c2 = (PFX + "-" + "x" * (63 - len(PFX) - 1))  # exactly 63 chars
    candidates = [
        ("c1 plain control", PFX + "_ctl"),
        ("c2 long-63", c2),
        ("c3 digits+hyphens", PFX + "-7h-42x"),
        ("c4 routing-edge 'aliases'", "aliases"),
        ("c5 routing-edge 'points'", "points"),
        ("c6 routing-edge 'exists'", "exists"),
    ]
    created = []  # names this script created (and will drop)
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        names_now = list_names()
        if names_now is None:
            print("VERDICT: SCRIPT_ERROR - list_collections unavailable; cannot "
                  "run the ownership guard for unprefixed routing-edge names")
            sys.exit(2)
        print(f"[setup] collections present at start: {names_now!r}")

        accepted = []
        for label, name in candidates:
            if name in names_now:
                print(f"[skip] {label}: {name!r} already exists and is not this "
                      f"script's (no PFX) - not touched, not adjudicated (G3)")
                continue
            st, raw = safe_request("PUT", "create_collection",
                                   body={"vectors": {"size": DIM, "distance": "Cosine"}},
                                   path_params={"name": name}, timeout=60)
            print(f"[create {label} {name!r}] status={st} raw={str(raw)[:200]}")
            if not transport_gate(f"create {label}", st, raw, findings):
                finish(findings)
                return
            if st in (200, 201):
                created.append(name)
                accepted.append((label, name))
            else:
                print(f"[skip] {label}: create face returned {st} - legality not "
                      f"established, nothing fabricated (G3); disposition belongs "
                      f"to the create lane")

        for label, name in accepted:
            # ---- positive: create-verified legal name must describe 200 ----
            st, raw, res = describe_status(name)
            print(f"[describe {label}] name={name!r} status={st} raw={str(raw)[:240]}")
            if not transport_gate(f"describe {label}", st, raw, findings):
                finish(findings)
                return
            if st != 200:
                findings.append((2, f"Type1_IllegalRejection: {label} - the create "
                                    f"face accepted {name!r} (it exists), but describe "
                                    f"returned HTTP {st}; "
                                    f"qdrant_behavioral_collections_get_001 requires "
                                    f"200 with the resolved config for an existing "
                                    f"collection. Corroboration: "
                                    f"{exists_probe(name)}: {str(raw)[:180]!r}"))
                continue
            if not (isinstance(res, dict) and isinstance(res.get("config"), dict)):
                findings.append((2, f"Type4_StateLogicViolation: {label} - 200 for "
                                    f"{name!r} but result/config is not an object "
                                    f"(grid: result=object, assertion: 'full "
                                    f"config'); result={res!r}"))
                continue
            print(f"[conform] {label}: 200 with a config object")

            # ---- negative twin: same grammar/length, never created -> 404 ----
            twin = name[:-2] + "0g"
            st2, raw2, _res2 = describe_status(twin)
            print(f"[twin {label}] name={twin!r} status={st2} raw={str(raw2)[:200]}")
            if not transport_gate(f"twin {label}", st2, raw2, findings):
                finish(findings)
                return
            if st2 == 200:
                findings.append((2, f"Type1_IllegalSuccess: {label} - twin "
                                    f"{twin!r} (never created, same grammar family "
                                    f"as the create-accepted {name!r}) got 200 with "
                                    f"a config body; the assertion's miss branch "
                                    f"requires 404, never 200 with config: "
                                    f"{str(raw2)[:180]!r}"))
            elif st2 != 404:
                findings.append((2, f"Type4_StateLogicViolation: {label} - twin "
                                    f"{twin!r} (same grammar family and length as "
                                    f"the create-accepted {name!r}, never created) "
                                    f"got HTTP {st2} instead of the documented 404 - "
                                    f"inconsistent disposition within one parameter "
                                    f"family (G9): {str(raw2)[:180]!r}"))
            else:
                print(f"[conform] twin of {label}: 404 on the never-created "
                      f"same-grammar name")

        finish(findings)
    finally:
        # destructive-safety: only names THIS script created are dropped
        for n in created:
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
    print("OK: every create-verified legal name (plain / 63-char / digits+hyphens "
          "/ routing-edge segments aliases, points, exists) is described with 200 "
          "+ a config object, and every never-created same-grammar twin gets the "
          "documented 404")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
