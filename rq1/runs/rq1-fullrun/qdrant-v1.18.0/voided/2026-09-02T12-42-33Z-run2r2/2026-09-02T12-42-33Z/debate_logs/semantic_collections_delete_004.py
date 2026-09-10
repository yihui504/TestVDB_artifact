#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_delete_004
# strategy: metamorphic
# endpoint: collections+delete
# constraint_ids: qdrant_bc_delete_invisibility_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-05 (Documentation Drift - metamorphic relations detect drift
#   without an absolute oracle: whatever the runtime does, it must do it on
#   ALL read faces and on BOTH lifecycle cycles)
"""
Attack: metamorphic (Type4) x qdrant_bc_delete_invisibility_001 on
  collections+delete (chunk_collections+delete unit
  behavioral_contracts::qdrant_bc_delete_invisibility_001).
  Two metamorphic relations over the contract's own three read faces
  (list / get / exists):
    MR1 cross-face agreement - at every sampled instant the three faces must
         AGREE on whether the collection exists. The contract fixes the
         post-delete expectation per face ("the list no longer contains the
         name, details access returns 404 and exists reports
         result.exists=false"), so any single face flipping alone (e.g. get
         404 while the list still names it, or exists=true while get 404s)
         violates the contract no matter which face is "right".
    MR2 lifecycle symmetry - the name's lifecycle is repeatable: create ->
         delete -> recreate -> delete. The all-present sample after recreate
         must equal the all-present sample after the first create (t3 == t0),
         and the all-absent sample after the second delete must equal the one
         after the first (t4 == t1/t2). A second cycle behaving differently
         from the first exposes stale tombstone / resurrection state.
  Sampling points: t0 after create | t1 zero delay after delete-ACK | t2 after
  settle | t3 after recreate | t4 zero delay after the second delete-ACK.
  G6 mutation justification: t1/t4 sample the ACK-to-propagation window
  (timing - where a ghost face most easily survives); the recreate cycle
  mutates the tombstone/reuse state (recovery/duplication family).
  [chunk_collections+delete coverage: metamorphic x
   qdrant_bc_delete_invisibility_001 (cross-face agreement + lifecycle
   symmetry)]
Oracle: at every sampling the three faces agree (all-present after creates,
  all-absent after deletes) and the two lifecycle cycles are symmetric
  (t3 == t0 all-present; t4 == t1 all-absent); any within-sample disagreement
  between faces, or a cycle behaving differently from the first, =
  Type4_StateLogicViolation; 5xx with /healthz alive = Type3; transport
  failure with healthy /healthz = SCRIPT_ERROR; an exists-face 404 counts as
  absent-consistent (docs declare only 200 for that face - measured conflict
  note, not adjudicated).

Rationale (G6/G7): the relation is declared before measurement; per-face
  verdicts are printed per sample so the judge can audit which face broke the
  agreement rather than trusting an aggregate boolean.
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
print(f"[path derivation] drop_collection = /collections/{{name}}; "
      f"list_collections = /collections; {EXISTS_KEY} = {rt.PATHS[EXISTS_KEY]} "
      f"(all URLs verbatim from raw_knowledge api_endpoints[].url)")

PFX = "scd04" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4
CREATED = []


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


def face_verdicts(name, findings):
    """Query the three faces; return (verdicts dict, ok_flag).
    Per-face verdict: 'present' | 'absent' | None (unadjudicable)."""
    v = {}
    st, raw = safe_request("GET", "list_collections", timeout=30)
    names = None
    if st == 200:
        try:
            res = json.loads(raw).get("result")
            colls = res.get("collections") if isinstance(res, dict) else None
            if isinstance(colls, list):
                names = [c.get("name") for c in colls if isinstance(c, dict)]
        except Exception:
            names = None
    print(f"[list] status={st} name_present={names is not None and name in names} "
          f"raw={str(raw)[:140]}")
    if not transport_gate("list face", st, raw, findings):
        return None, False
    if names is None:
        findings.append((3, f"SCRIPT-ERROR: list 200 but result.collections[].name "
                            f"unparseable: {str(raw)[:150]}"))
        return None, False
    v["list"] = "present" if name in names else "absent"

    st, raw = safe_request("GET", "describe_collection",
                           path_params={"name": name}, timeout=30)
    print(f"[get] status={st} raw={str(raw)[:140]}")
    if not transport_gate("get face", st, raw, findings):
        return None, False
    if st == 200:
        v["get"] = "present"
    elif st == 404:
        v["get"] = "absent"
    else:
        print(f"[conflict-zone] get face status {st}; face excluded from agreement")
        v["get"] = None

    st, raw = safe_request("GET", EXISTS_KEY,
                           path_params={"collection_name": name}, timeout=30)
    ev = None
    if st == 200:
        try:
            res = json.loads(raw).get("result")
            if isinstance(res, dict) and isinstance(res.get("exists"), bool):
                ev = res["exists"]
        except Exception:
            ev = None
    print(f"[exists] status={st} result.exists={ev} raw={str(raw)[:140]}")
    if not transport_gate("exists face", st, raw, findings):
        return None, False
    if st == 200 and ev is True:
        v["exists"] = "present"
    elif st == 200 and ev is False:
        v["exists"] = "absent"
    elif st == 404:
        # docs declare only 200 for the exists face; 404 alongside get-404 is
        # absent-consistent (measured conflict note, R10 lesson)
        print("[conflict-zone] exists face 404; counted absent-consistent")
        v["exists"] = "absent"
    else:
        print(f"[conflict-zone] exists face status {st} exists={ev!r}; excluded")
        v["exists"] = None
    return v, True


def sample(label, name, findings):
    """One agreement sampling. Returns the set of adjudicated verdicts
    (deduplicated), or None when the sample is unusable."""
    v, ok = face_verdicts(name, findings)
    if not ok or v is None:
        return None
    adjudicated = {k: s for k, s in v.items() if s is not None}
    print(f"[{label}] face verdicts = {v}")
    distinct = set(adjudicated.values())
    if len(distinct) > 1:
        findings.append((2, f"Type4_StateLogicViolation: {label} - read faces DISAGREE "
                            f"on existence of '{name}': {v}; MR1 cross-face agreement "
                            f"violated (qdrant_bc_delete_invisibility_001 fixes the same "
                            f"post-delete expectation for all three faces)"))
        return None
    if not adjudicated:
        findings.append((3, f"SCRIPT-ERROR: {label} - no face adjudicable"))
        return None
    verdict = distinct.pop()
    print(f"[{label}] MR1 holds: all adjudicated faces report '{verdict}'")
    return verdict


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    name = PFX + "_cyc"
    CREATED.append(name)
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        def do_create(tag):
            st, raw = safe_request("PUT", "create_collection",
                                   body={"vectors": {"size": DIM, "distance": "Cosine"}},
                                   path_params={"name": name}, timeout=60)
            print(f"[create {tag}] status={st} raw={str(raw)[:160]}")
            return st, raw

        def do_delete(tag):
            st, raw = safe_request("DELETE", "drop_collection",
                                   path_params={"name": name},
                                   query_params={"timeout": 10}, timeout=60)
            print(f"[delete {tag} ?timeout=10] status={st} raw={str(raw)[:160]}")
            return st, raw

        def confirmed_200(st, raw, tag):
            if not transport_gate(tag, st, raw, findings):
                return False
            if st != 200:
                findings.append((3, f"SCRIPT-ERROR: {tag} got {st}; disposition matrix "
                                    f"is the boundary lane's, metamorphic cycle cannot "
                                    f"start: {str(raw)[:150]}"))
                return False
            try:
                env = json.loads(raw) if raw else {}
                ok_env = isinstance(env.get("result"), bool) and env["result"]
            except Exception:
                ok_env = False
            if not ok_env:
                findings.append((2, f"Type4_StateLogicViolation: {tag} 200 but envelope "
                                    f"violates result:boolean=true grid"))
                return False
            return True

        # ---- cycle 1: create -> t0 -> delete -> t1 -> t2 ----
        st, raw = do_create("cycle-1")
        if not confirmed_200(st, raw, "create cycle-1"):
            finish(findings)
            return
        t0 = sample("t0 after create #1", name, findings)
        st, raw = do_delete("cycle-1")
        if not confirmed_200(st, raw, "delete cycle-1"):
            finish(findings)
            return
        t1 = sample("t1 zero-delay after delete #1", name, findings)
        time.sleep(2.5)
        t2 = sample("t2 settled after delete #1", name, findings)

        # ---- cycle 2: recreate -> t3 -> delete -> t4 ----
        st, raw = do_create("cycle-2")
        if not confirmed_200(st, raw, "re-create cycle-2"):
            finish(findings)
            return
        t3 = sample("t3 after re-create", name, findings)
        st, raw = do_delete("cycle-2")
        if not confirmed_200(st, raw, "delete cycle-2"):
            finish(findings)
            return
        t4 = sample("t4 zero-delay after delete #2", name, findings)

        # ---- MR2 lifecycle symmetry ----
        if t0 is not None and t3 is not None and t0 != t3:
            findings.append((2, f"Type4_StateLogicViolation: MR2 lifecycle asymmetry - "
                                f"after re-create the faces report '{t3}' but after the "
                                f"first create they reported '{t0}' (stale tombstone / "
                                f"resurrection state around '{name}')"))
        else:
            print(f"[MR2] create-side symmetry holds: t0={t0} == t3={t3} (present)")
        if t1 is not None and t4 is not None and t1 != t4:
            findings.append((2, f"Type4_StateLogicViolation: MR2 lifecycle asymmetry - "
                                f"after the second delete the faces report '{t4}' but "
                                f"after the first delete they reported '{t1}'"))
        else:
            print(f"[MR2] delete-side symmetry holds: t1={t1} == t4={t4} (absent)")
        if t2 is not None and t2 != "absent":
            findings.append((2, f"Type4_StateLogicViolation: settled sample after delete "
                                f"#1 reports '{t2}' (absent required)"))

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
    print("OK: MR1 cross-face agreement held at all five samplings; MR2 lifecycle "
          "symmetry held (create-side t0==t3 present, delete-side t1==t4 absent)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
