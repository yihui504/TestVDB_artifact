#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_list_003
# strategy: metamorphic
# endpoint: collections+list
# constraint_ids: qdrant_behavioral_collections_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collections
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift / search-semantic correctness of the
#   listing face - name-namespace semantics: the listing must echo names
#   byte-identically, keep case-distinct names as distinct rows, and be a
#   stable pure read; case-folding, name mutation, or flickering rows are
#   exactly the documented-behavior-vs-implementation drift this blindspot
#   covers)
"""
Attack: metamorphic (S5/S6 name-fidelity + read-stability relations) x
  qdrant_behavioral_collections_list_001 (chunk_collections+list unit
  assertions::qdrant_behavioral_collections_list_001; strategy coverage slot
  "metamorphic name-fidelity/stability x list_001" - see _001's Attack block
  for the full chunk coverage list).
Oracle: the HTTP 200 listing of the 4-member legal-name family (the
  case-distinct pair alpha/Alpha, a dash/underscore/digit name, a short
  digit-suffix name) echoes
  every name byte-identically, lists the case-distinct pair as TWO distinct
  rows (case-folding/collision = Type4_StateLogicViolation), carries no
  duplicate rows, and three consecutive reads plus one read interleaved with
  an unrelated describe return the identical prefix-scoped multiset
  (row flicker or read-induced mutation = Type4_StateLogicViolation);
  non-200 on any legal GET = Type1_IllegalRejection; 5xx with /healthz
  alive = Type3; transport failure with healthy /healthz or create setup
  failure = SCRIPT_ERROR (G8, never a defect). A 4xx on creating a family
  member is a create-face disposition outside this unit: measured note +
  that member drops out of the expected set (premise adaptation, not a
  defect of the listing face, not grounds to abort).

Name-namespace semantics under test (the "search semantic correctness" slot
for a listing face - its result set IS its semantics):
  NR1 echo fidelity     : listed name == create-request name, byte for byte
                          (no trimming, no case mutation, no re-encoding);
  NR2 case distinctness : "alpha" and "Alpha" are different collection names;
                          the listing must carry both as distinct rows - a
                          folded single row would mean the registry collided
                          two live collections;
  NR3 repeat-read stability: with no state change in scope, repeated GETs
                          return the identical prefix-scoped multiset (pure
                          read, no flicker), also across an interleaved
                          describe read of one member.

Family members are deliberately spread over legal-name shapes (mixed case,
dash, underscore, digits, short) per the shape-generalization duty (G3):
the echo promise is a name-family property, not a single-name anecdote.
Sibling tolerance: membership equality is asserted only inside this
script's unique ownership prefix.
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

LIST_KEY = "list_collections"
DESCRIBE_KEY = "describe_collection"
print(f"[path derivation] {LIST_KEY} = {rt.PATHS[LIST_KEY]} (runtime PATHS; "
      f"matches raw_knowledge api_endpoints[collections+list].url /collections)")

PFX = "scl03" + uuid.uuid4().hex[:6]
DIM = 4
FAMILY = (PFX + "_alpha", PFX + "_Alpha", PFX + "_x-1_2", PFX + "_9")


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


def list_rows(label):
    """GET /collections -> (status, raw, rows) with rows = prefix-scoped
    names (duplicates preserved); None when the promised array is
    missing/unparseable. Name-key extraction only (R8 lesson)."""
    st, raw = safe_request("GET", LIST_KEY, timeout=30)
    print(f"[{label}] GET /collections status={st} raw={str(raw)[:300]}")
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
    if entries is None:
        return st, raw, None
    rows = [it["name"] for it in entries
            if isinstance(it, dict) and isinstance(it.get("name"), str)
            and it["name"].startswith(PFX)]
    return st, raw, rows


def cleanup(expected):
    """Teardown: drop only this script's prefixed collections (the full
    family, including any member whose create 4xx'd - idempotent drop);
    failure non-fatal."""
    for name in expected:
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
    print("OK: the listing echoed all family names byte-identically, kept the "
          "case-distinct pair as two distinct rows, and returned an identical "
          "prefix-scoped multiset across repeated and interleaved reads")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    expected = list(FAMILY)
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- setup: create the legal-name family ----
        for name in FAMILY:
            st, raw = safe_request("PUT", "create_collection",
                                   body={"vectors": {"size": DIM, "distance": "Cosine"}},
                                   path_params={"name": name}, timeout=60)
            print(f"[create {name}] status={st} raw={str(raw)[:200]}")
            if not transport_gate(f"create {name}", st, raw, findings):
                finish(findings)
                return
            if st not in (200, 201):
                # create-face disposition on this name: outside the listing
                # unit - measured note, member drops out of the expected set
                print(f"[measured note] create-face returned {st} for {name!r} "
                      f"(collections+create disposition, not adjudicated here); "
                      f"family shrinks to {len(expected) - 1}")
                expected = [n for n in expected if n != name]
        if len(expected) < 2:
            findings.append((3, "SCRIPT-ERROR-setup: fewer than 2 family members "
                                "created - name-fidelity oracle needs a comparable "
                                "family"))
            finish(findings)
            return
        case_pair = [n for n in expected if n.casefold() == (PFX + "_alpha").casefold()]
        if len(case_pair) == 2:
            print(f"[premise] case-distinct pair both live: {case_pair}")

        # ---- NR1+NR2: echo fidelity, case distinctness, duplicate-freedom ----
        st, raw, rows = list_rows("NR1/NR2 echo")
        if not transport_gate("NR1/NR2 list", st, raw, findings):
            finish(findings)
            return
        if rows is None:
            findings.append((2, "Type4_StateLogicViolation: NR1/NR2 - the promised "
                                "array is missing/unparseable: "
                                f"{str(raw)[:250]!r}"))
            finish(findings)
            return
        if st != 200:
            findings.append((2, f"Type1_IllegalRejection: legal GET /collections "
                                f"rejected with status={st}: {str(raw)[:250]!r}"))
            finish(findings)
            return
        print(f"[NR1/NR2] prefix-scope={sorted(rows)} expected={sorted(expected)}")
        if len(rows) != len(set(rows)):
            findings.append((2, f"Type4_StateLogicViolation: duplicate rows for the "
                                f"same collection name: "
                                f"{sorted({n for n in rows if rows.count(n) > 1})}"))
        folded = sorted({n for n in rows if n.casefold() in
                         {e.casefold() for e in expected} and n not in expected})
        if folded:
            findings.append((2, f"Type4_StateLogicViolation: NR1 echo fidelity - "
                                f"listed names deviate from the create-request "
                                f"spelling (case-mutated echo): {folded}"))
        missing = sorted(set(expected) - set(rows))
        if missing:
            findings.append((2, f"Type4_StateLogicViolation: ACKed family members "
                                f"missing from the listing: {missing}"))
        phantom = sorted(set(rows) - set(expected))
        if phantom:
            findings.append((2, f"Type4_StateLogicViolation: phantom prefix-scoped "
                                f"rows never created by this script: {phantom}"))
        if len(case_pair) == 2 and len(
                {n for n in rows if n in case_pair}) != 2:
            findings.append((2, f"Type4_StateLogicViolation: NR2 case distinctness - "
                                f"the two live case-distinct collections "
                                f"{case_pair} do not appear as two distinct rows "
                                f"(registry namespace collision): {sorted(rows)}"))
        if any(r == 2 for r, _ in findings):
            finish(findings)
            return

        # ---- NR3: repeat-read stability (pure read, no flicker) ----
        baseline = sorted(rows)
        for i in (1, 2, 3):
            st, raw, rows_i = list_rows(f"NR3 read#{i}")
            if not transport_gate(f"NR3 read#{i}", st, raw, findings):
                finish(findings)
                return
            if rows_i is None or sorted(rows_i) != baseline:
                findings.append((2, f"Type4_StateLogicViolation: NR3 repeat-read "
                                    f"stability - with no state change in scope, "
                                    f"read#{i} returned {sorted(rows_i or [])} "
                                    f"instead of the stable {baseline}"))
                finish(findings)
                return
        probe = expected[0]
        gst, graw = safe_request("GET", DESCRIBE_KEY,
                                 path_params={"name": probe}, timeout=30)
        print(f"[NR3 interleaved describe {probe}] status={gst} raw={str(graw)[:160]}")
        if not transport_gate(f"describe {probe}", gst, graw, findings):
            finish(findings)
            return
        if gst != 200:
            findings.append((3, f"SCRIPT-ERROR-control: describe of created {probe} "
                                f"returned {gst} - premise broken"))
            finish(findings)
            return
        st, raw, rows_4 = list_rows("NR3 read#4 post-describe")
        if not transport_gate("NR3 read#4", st, raw, findings):
            finish(findings)
            return
        if rows_4 is None or sorted(rows_4) != baseline:
            findings.append((2, f"Type4_StateLogicViolation: NR3 read stability - "
                                f"listing changed across an interleaved read-only "
                                f"describe: {sorted(rows_4 or [])} vs {baseline}"))
            finish(findings)
            return
        print(f"[NR3] 4 reads + interleaved describe all returned {baseline}")
        finish(findings)
    finally:
        cleanup(expected)


if __name__ == "__main__":
    main()
