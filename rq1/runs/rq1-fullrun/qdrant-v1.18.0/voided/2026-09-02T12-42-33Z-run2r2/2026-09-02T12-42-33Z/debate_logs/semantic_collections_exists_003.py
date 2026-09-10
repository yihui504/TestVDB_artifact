#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_exists_003
# strategy: metamorphic
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (behavioral-consistency detection - three faces of the
#   SAME parameter collection_name must agree on existence; the face-status
#   asymmetry is documented, but the existence VALUE may not disagree)
"""
Attack: metamorphic (S6, cross-face existence equivalence) x
  qdrant_behavioral_collections_exists_001 on collections+exists
  (chunk_collections+exists unit
  assertions::qdrant_behavioral_collections_exists_001).
  Metamorphic relation (declared before measurement):
    R:  exists(n)==True  <=>  describe(n)==HTTP 200  <=>  n in list_collections
       exists(n)==False <=>  describe(n)==HTTP 404  <=>  n not in list
  The status asymmetry across faces is BY DESIGN (collections+get declares
  404 "not found" for missing; collections+exists declares 200-always) - the
  relation is on the existence VALUE each face reports, not on the status
  class, so no by-design face difference is misjudged (threat-model G3).
  Probes (G4 both directions on one setup):
    P1 positive  - a self-created collection: exists true, describe 200,
                   listed
    P2 negative  - a never-created unique-prefix name: exists false (200),
                   describe 404, not listed
    P3 transient - the P1 collection after a 200 delete: exists false,
                   describe 404, not listed
    P4 reverse   - every name of THIS script's ownership prefix found in the
                   live list must report exists=true (list->exists direction;
                   catches listing ghosts from the other side)
  List extraction uses result.collections[].name key extraction first (R11
  lesson: `name in [objects]` is a vacuous-true trap).
  [chunk_collections+exists coverage: metamorphic x
   qdrant_behavioral_collections_exists_001 (3-face existence equivalence,
   both directions + reverse list direction) - this script; core
   truthfulness+shape = _001; alias interplay = _002; error-body quality =
   _004; legal-name family = _005]
Oracle: for each probe the three faces agree exactly per R; any disagreement
  (exists=true with describe 404, exists=false with describe 200, listed
  with exists=false, unlisted with exists=true) = Type4_StateLogicViolation
  (cross-face state inconsistency for the same collection_name); exists
  returning non-200 (incl. 404 - never-404 clause) = Type4; describe/list
  transport failures with healthy /healthz = SCRIPT_ERROR; 5xx with
  /healthz alive = Type3; create/delete setup failures = SCRIPT_ERROR (G8).

Rationale (G7/G9): the relation is a pure equivalence between documented
  faces of one parameter - it needs no extra spec beyond each face's
  declared response, yet it catches exactly the class where one face's view
  of existence drifts from another's (e.g. a list built from a stale
  registry while exists reads live state); every leg prints all three
  measured values before the comparison so the judge can audit each cell.
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

PFX = "sce03" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
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


def exists_face(name):
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


def list_face(findings, label="list_collections"):
    """GET /collections -> (names list or None); key extraction first."""
    st, raw = safe_request("GET", "list_collections", timeout=30)
    print(f"[{label}] status={st} raw={str(raw)[:200]}")
    if not transport_gate(label, st, raw, findings):
        return None
    names = None
    if st == 200:
        try:
            res = json.loads(raw).get("result")
            colls = res.get("collections") if isinstance(res, dict) else None
            if isinstance(colls, list):
                names = [c.get("name") for c in colls if isinstance(c, dict)]
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            names = None
    return names


def probe(label, name, expected_exists, findings):
    """Measure all three faces for one name and adjudicate relation R."""
    est, ev, eraw = exists_face(name)
    print(f"[{label}/exists] name={name!r} status={est} value={ev!r} raw={str(eraw)[:180]}")
    dst, draw = safe_request("GET", "describe_collection",
                             path_params={"name": name}, timeout=30)
    print(f"[{label}/describe] status={dst} raw={str(draw)[:180]}")
    names = list_face(findings, label=f"{label}/list")
    ok = True

    if not transport_gate(f"{label}/exists", est, eraw, findings):
        return
    if est != 200:
        findings.append((2, f"Type4_StateLogicViolation: {label} - exists face returned "
                            f"HTTP {est} for {name!r}; qdrant_behavioral_collections_"
                            f"exists_001 requires 200 with existence in the body "
                            f"(never 404): {str(eraw)[:180]!r}"))
        return
    if ev is None:
        findings.append((2, f"Type4_StateLogicViolation: {label} - exists 200 but "
                            f"result.exists is not a boolean (response-shape grid): "
                            f"{str(eraw)[:180]!r}"))
        return
    if ev != expected_exists:
        findings.append((2, f"Type4_StateLogicViolation: {label} - exists reports "
                            f"{ev!r} but ground truth for {name!r} is "
                            f"{expected_exists!r}: {str(eraw)[:180]!r}"))
        ok = False
    if not transport_gate(f"{label}/describe", dst, draw, findings):
        return
    # documented face asymmetry: describe 404s for missing, exists 200s - so
    # the expected describe status mirrors the existence value
    if ev is True and dst != 200:
        findings.append((2, f"Type4_StateLogicViolation: {label} - faces disagree: "
                            f"exists=true but describe returned {dst} for {name!r} "
                            f"(relation R broken on the details face)"))
        ok = False
    if ev is False and dst == 200:
        findings.append((2, f"Type4_StateLogicViolation: {label} - faces disagree: "
                            f"exists=false but describe returned 200 for {name!r} "
                            f"(ghost details face)"))
        ok = False
    if names is None:
        findings.append((3, f"SCRIPT-ERROR: {label} - collections list 200 but "
                            f"result.collections[].name unparseable"))
        return
    listed = name in names
    if listed is not ev:
        findings.append((2, f"Type4_StateLogicViolation: {label} - faces disagree: "
                            f"exists={ev!r} but list membership={listed!r} for "
                            f"{name!r} ({'ghost listing' if listed and not ev else 'unlisted but existing'})"))
        ok = False
    if ok:
        print(f"[conform] {label}: three faces agree - exists={ev!r}, "
              f"describe={'200' if dst == 200 else dst}, listed={listed!r}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[relation R] exists(n)==True <=> describe(n)==200 <=> n in list; "
          "exists(n)==False <=> describe(n)==404 <=> n not in list "
          "(status asymmetry by design; the VALUE may not disagree)")
    findings = []
    live = PFX + "_live"
    never = PFX + "_never"
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": live}, timeout=60)
        print(f"[create {live}] status={st} raw={str(raw)[:200]}")
        if not transport_gate("create live", st, raw, findings):
            finish(findings)
            return
        if st not in (200, 201):
            findings.append((3, f"SCRIPT-ERROR-setup: create returned {st}: {str(raw)[:150]}"))
            finish(findings)
            return

        # P1 positive: existing collection -> all faces affirmative
        probe("P1 positive", live, True, findings)

        # P2 negative: never-created name -> all faces negative
        probe("P2 negative", never, False, findings)

        # P3 transient: after a 200 delete -> all faces negative
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": live}, timeout=120)
        print(f"[delete {live}] status={st} raw={str(raw)[:200]}")
        if not transport_gate("delete live", st, raw, findings):
            finish(findings)
            return
        if st != 200:
            findings.append((3, f"SCRIPT-ERROR-setup: delete returned {st} "
                                f"(transition premise): {str(raw)[:150]}"))
            finish(findings)
            return
        probe("P3 post-delete", live, False, findings)

        # P4 reverse: every owned name still in the list must exist=true
        names = list_face(findings, label="P4 list")
        if names is not None:
            owned_listed = [n for n in names if isinstance(n, str) and n.startswith(PFX)]
            print(f"[P4] owned names still listed: {owned_listed!r}")
            for n in owned_listed:
                est, ev, eraw = exists_face(n)
                print(f"[P4/exists] name={n!r} status={est} value={ev!r}")
                if not transport_gate(f"P4 exists {n}", est, eraw, findings):
                    continue
                if est != 200 or ev is not True:
                    findings.append((2, f"Type4_StateLogicViolation: P4 reverse "
                                        f"direction - '{n}' is in the collections "
                                        f"list but exists reports status={est} "
                                        f"value={ev!r} (listed ghost)"))
            if not owned_listed:
                print("[conform] P4: no owned names remain listed after the delete")

        finish(findings)
    finally:
        # destructive-safety: only self-created, PFX-prefixed names are dropped
        try:
            rt.drop_collection(live)
        except Exception as e:
            print(f"cleanup warning (drop {live}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: exists/describe/list faces agree on existence in both directions "
          "for live, never-created and just-deleted names (relation R holds)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
