#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_list_002
# strategy: metamorphic
# endpoint: collections+list
# constraint_ids: qdrant_behavioral_collections_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collections
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift / behavioral-consistency detection -
#   the listing is the registry's public truth: a 200 create/drop ACK that is
#   not reflected immediately and exactly in the global listing is the
#   documented-behavior-vs-implementation drift this blindspot covers)
"""
Attack: metamorphic (S6 state-transition relations) x
  qdrant_behavioral_collections_list_001 (chunk_collections+list unit
  assertions::qdrant_behavioral_collections_list_001; strategy coverage slot
  "metamorphic state-transition x list_001" - see _001's Attack block for the
  full chunk coverage list).
Oracle: the HTTP 200 listing is a faithful registry of create/drop ACKs:
  (MR1) immediately after the 3rd create 200
  ACK (no settle delay) the prefix scope lists exactly {A,B,C}; (MR2)
  immediately after a 200 drop ACK of B the prefix scope lists exactly {A,C}
  with B absent AND the describe face answers 404 for B while still 200 for
  control A; (MR3) after re-creating the dropped name B the prefix scope
  lists {A,B,C} with B appearing exactly once - any membership deviation,
  duplicate row from lifecycle churn, or list/describe disagreement =
  Type4_StateLogicViolation; 5xx with /healthz alive = Type3; transport
  failure with healthy /healthz, create/drop setup-premise failure =
  SCRIPT_ERROR (G8, never a defect).

Metamorphic relations under test (transformations of the registry state, the
listing content must follow deterministically):
  MR1 create-ACK => membership   : a 200 create ACK is the server's own
      "done" signal; the listing (which the assertion defines as the array of
      ALL collection descriptions) must already contain the name at the very
      next read - measured immediately, before any settle sleep.
  MR2 drop-ACK => exactly-one-exit: dropping ONE of three prefix-owned
      collections removes exactly that row (differential mutation - siblings
      A and C must survive untouched), corroborated cross-face by the
      describe face (404 for B, 200 for A).
  MR3 recreate-after-drop => no-churn-duplicates: re-creating the same name
      after a drop must yield exactly one row for it (registry tombstone
      handling), never zero and never two.

Mutation justification (G6): the ACK-to-propagation window is where this
  invariant most easily breaks (async registry update, tombstone left behind
  on recreate), so every membership sample is taken IMMEDIATELY after the
  mutating ACK, before any settle delay - a defect that only shows in that
  window would be masked by a sleep-first oracle.

Cross-face note: the describe face (collections+get, R14-covered unit) is
  used only as a corroborating oracle for MR2 membership; the unit under
  attack here remains the listing face. Sibling tolerance: all membership
  assertions are scoped to this script's unique ownership prefix; the global
  array may legitimately carry other scripts' rows.
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
print(f"[path derivation] {LIST_KEY} = {rt.PATHS[LIST_KEY]}; {DESCRIBE_KEY} = "
      f"{rt.PATHS[DESCRIBE_KEY]} (runtime PATHS; matches raw_knowledge "
      f"api_endpoints[collections+list].url /collections and "
      f"[collections+get].url /collections/{{collection_name}})")

PFX = "scl02" + uuid.uuid4().hex[:6]
DIM = 4
A, B, C = PFX + "_a", PFX + "_b", PFX + "_c"
MEMBERS = (A, B, C)


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


def list_face(label):
    """GET /collections -> (status, raw, rows) where rows is the raw list of
    prefix-scoped names (with duplicates preserved), or None when the
    promised array is missing/unparseable. Key extraction via the "name"
    key only (R8 lesson)."""
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


def expect_scope(label, st, raw, rows, expected, findings):
    """Declare-then-compare for prefix-scoped membership (G7)."""
    if rows is None:
        findings.append((2, f"Type4_StateLogicViolation: {label} - the promised "
                            f"array is missing/unparseable: {str(raw)[:250]!r}"))
        return
    print(f"[{label}] prefix-scope={sorted(rows)} expected={sorted(expected)}")
    if len(rows) != len(set(rows)):
        findings.append((2, f"Type4_StateLogicViolation: {label} - duplicate rows "
                            f"for the same collection name: "
                            f"{sorted({n for n in rows if rows.count(n) > 1})}"))
    if set(rows) != set(expected):
        findings.append((2, f"Type4_StateLogicViolation: {label} - listing deviates "
                            f"from the ACKed registry state: expected exactly "
                            f"{sorted(expected)}, got {sorted(rows)} "
                            f"(missing={sorted(set(expected) - set(rows))}, "
                            f"unacknowledged={sorted(set(rows) - set(expected))})"))


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
    print("OK: the listing followed all three registry transitions exactly - "
          "create-ACK => immediate membership, drop-ACK => exactly-one-exit "
          "(corroborated by the describe face), recreate => exactly-once row")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- setup: create A, B, C; premise = each ACKs 200 ----
        for name in MEMBERS:
            st, raw = safe_request("PUT", "create_collection",
                                   body={"vectors": {"size": DIM, "distance": "Cosine"}},
                                   path_params={"name": name}, timeout=60)
            print(f"[create {name}] status={st} raw={str(raw)[:200]}")
            if not transport_gate(f"create {name}", st, raw, findings):
                finish(findings)
                return
            if st not in (200, 201):
                findings.append((3, f"SCRIPT-ERROR-setup: create {name} returned "
                                    f"{st}: {str(raw)[:150]}"))
                finish(findings)
                return

        # ---- MR1: create-ACK => immediate membership (no settle delay) ----
        st, raw, rows = list_face("MR1 post-create")
        if not transport_gate("MR1 list", st, raw, findings):
            finish(findings)
            return
        expect_scope("MR1 post-create", st, raw, rows, MEMBERS, findings)
        if any(r == 2 for r, _ in findings):
            finish(findings)
            return

        # ---- MR2: drop B => exactly {A,C}; describe cross-face corroboration ----
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": B}, timeout=120)
        print(f"[drop {B}] status={st} raw={str(raw)[:200]}")
        if not transport_gate(f"drop {B}", st, raw, findings):
            finish(findings)
            return
        if st != 200:
            findings.append((3, f"SCRIPT-ERROR-setup: drop of existing {B} returned "
                                f"{st} (transition premise broken): {str(raw)[:150]}"))
            finish(findings)
            return
        st, raw, rows = list_face("MR2 post-drop")
        if not transport_gate("MR2 list", st, raw, findings):
            finish(findings)
            return
        expect_scope("MR2 post-drop", st, raw, rows, (A, C), findings)

        gst, graw = safe_request("GET", DESCRIBE_KEY,
                                 path_params={"name": B}, timeout=30)
        print(f"[MR2 describe {B}] status={gst} raw={str(graw)[:260]}")
        if not transport_gate(f"describe {B}", gst, graw, findings):
            finish(findings)
            return
        if gst == 200:
            findings.append((2, f"Type4_StateLogicViolation: list/describe "
                                f"disagreement - listing dropped {B} but the describe "
                                f"face still answers 200 for it (cross-face "
                                f"disagreement on a 200 drop ACK)"))
        elif gst != 404:
            findings.append((2, f"Type4_StateLogicViolation: describe face answered "
                                f"{gst} for dropped {B} (expected 404) - cross-face "
                                f"disagreement on a 200 drop ACK"))
        gst, graw = safe_request("GET", DESCRIBE_KEY,
                                 path_params={"name": A}, timeout=30)
        print(f"[MR2 describe control {A}] status={gst} raw={str(graw)[:160]}")
        if not transport_gate(f"describe control {A}", gst, graw, findings):
            finish(findings)
            return
        if gst != 200:
            findings.append((3, f"SCRIPT-ERROR-control: describe of surviving "
                                f"collection {A} returned {gst} - differential premise "
                                f"broken, no defect conclusion"))
        if findings:
            finish(findings)
            return

        # ---- MR3: recreate dropped name => exactly one row for B ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": B}, timeout=60)
        print(f"[recreate {B}] status={st} raw={str(raw)[:200]}")
        if not transport_gate(f"recreate {B}", st, raw, findings):
            finish(findings)
            return
        if st not in (200, 201):
            findings.append((3, f"SCRIPT-ERROR-setup: recreate {B} returned {st}: "
                                f"{str(raw)[:150]}"))
            finish(findings)
            return
        st, raw, rows = list_face("MR3 post-recreate")
        if not transport_gate("MR3 list", st, raw, findings):
            finish(findings)
            return
        expect_scope("MR3 post-recreate", st, raw, rows, MEMBERS, findings)
        finish(findings)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
