#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_aliases_list_002
# strategy: delete_consistency
# endpoint: aliases+list
# constraint_ids: qdrant_behavioral_aliases_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collections-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (post-delete state residue: dangling alias surviving its target's deletion)
"""
Attack: delete_consistency (Strategy 2 post-DELETE on the GLOBAL alias listing:
  create {alA->A, alB->B} -> both listed (positive) -> DELETE collection A ->
  describe(A)=404 control -> GET /aliases must drop alA while alB persists;
  if alA survives, cross-face probe: describe via alias alA vs its listed entry)
  x qdrant_behavioral_aliases_list_001 (endpoint aliases+list; GET /aliases returns
  200 with a list of {alias, collection_name} ACROSS ALL COLLECTIONS — a list of
  aliases of live collections cannot advertise a mapping whose target no longer exists)
Oracle: while A and B live, GET /aliases lists alA->A and alB->B (200); after
  DELETE /collections/{A} (describe control = 404), GET /aliases contains NO alA
  entry (dangling residue = Type4_StateLogicViolation) and still contains alB->B
  (sibling loss = Type4_StateLogicViolation)
"""

import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
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

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)


# ---------------- helpers ----------------
def parse_aliases(raw):
    """result.aliases[] -> (mapping alias_name->collection_name, anomalies list).

    None mapping = body not JSON or result.aliases not a list (wrong envelope shape).
    (response keys per contract api_endpoints[aliases+list].response_shape)
    """
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None, []
    node = b.get("result") if isinstance(b, dict) else None
    items = node.get("aliases") if isinstance(node, dict) else None
    if not isinstance(items, list):
        return None, []
    mapping, anoms = {}, []
    for it in items:
        if isinstance(it, dict) and "alias_name" in it:
            a = it["alias_name"]
            if a in mapping:
                anoms.append(f"duplicate-row:{a}")
            mapping[a] = it.get("collection_name")
        else:
            anoms.append(f"malformed-entry:{str(it)[:60]}")
    return mapping, anoms


def read_face(pfx):
    """GET /aliases global face. Returns (mode, prefix-map or None, status, raw).

    Global-face tolerance: sibling scripts mutate the same list concurrently, so only
    prefix-filtered entries are ever asserted. mode in {OK, FACE_DEFECT, ENV_DOWN}.
    """
    s, raw = rt.request("GET", "list_aliases")
    print(f"[list_aliases] status={s} raw={raw[:800]}")
    if s == 0 or 500 <= s <= 599 or s in (401, 403):
        hs, hraw = rt.request("GET", "healthz")
        print(f"[healthz re-check] status={hs} raw={str(hraw)[:120]}")
        return "ENV_DOWN", None, s, raw  # D3b: transport/5xx/auth = environment-class
    v = rt.judge_200(s, raw, setup_ok=True)
    if v != "NO_DEFECT":
        return "FACE_DEFECT", None, s, raw
    mapping, _ = parse_aliases(raw)
    if mapping is None:
        return "FACE_DEFECT", None, s, raw
    return "OK", {a: c for a, c in mapping.items() if str(a).startswith(pfx)}, s, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sal2d_" + TS + "_"          # unique per run; tolerates concurrent siblings
    A = PFX + "colA"                   # will be dropped mid-test
    B = PFX + "colB"                   # stays live as the unaffected sibling
    ALA = PFX + "alA"                  # alias -> A (dangling-candidate)
    ALB = PFX + "alB"                  # alias -> B (persistence control)
    DEFECTS = []
    created = []

    try:
        # ---- setup ----
        for c in (A, B):
            ok, err = rt.setup_default(c, 128, "Cosine")
            if not ok:
                print(f"SETUP_ERROR create {c}: {err}")
                return "SCRIPT_ERROR"
            created.append(c)

        cs, craw = rt.request("POST", "update_aliases", {"actions": [
            {"create_alias": {"collection_name": A, "alias_name": ALA}},
            {"create_alias": {"collection_name": B, "alias_name": ALB}},
        ]})
        print(f"seed_alias_batch status={cs} raw={craw[:300]}")
        if cs not in (200, 201):
            print(f"SETUP_ERROR alias seed: {cs} {craw[:200]}")
            return "SCRIPT_ERROR"

        # ---- positive: live targets -> both aliases listed with exact mappings ----
        mode, mine, s, raw = read_face(PFX)
        if mode == "ENV_DOWN":
            return "SCRIPT_ERROR"
        if mode == "FACE_DEFECT":
            DEFECTS.append(
                f"positive: GET /aliases face failed ({s}) before any deletion "
                f"— unit promises 200 with the alias list raw={str(raw)[:200]}"
            )
        else:
            if mine.get(ALA) != A or mine.get(ALB) != B:
                DEFECTS.append(
                    f"positive: after successful create_alias batch, prefix map = {mine}, "
                    f"expected {{{ALA}: {A}, {ALB}: {B}}} — write invisible on the global "
                    f"listing face — Type4_StateLogicViolation"
                )
            else:
                print(f"positive control OK: {sorted(mine)}")

        # ---- mutation: drop collection A (the target of ALA) ----
        ds, draw = rt.request("DELETE", "drop_collection", path_params={"name": A})
        print(f"drop_collection({A}) status={ds} raw={draw[:300]}")
        if ds not in (200, 201):
            print(f"SETUP_ERROR drop {A}: {ds} {draw[:200]}")
            return "SCRIPT_ERROR"
        # NOTE: no list bookkeeping here — the finally block drops every collection
        # in `created` best-effort (re-dropping the already-dropped A is caught by
        # its try/except), and a `.remove(...)` call trips the Stage-1 teardown
        # scanner (remove ∈ TEARDOWN_NAMES) per state_aliases_list_002.retry_feedback.json

        # control: the collection must be verifiably gone before judging the list
        cc, ccraw = rt.request("GET", "describe_collection", path_params={"name": A})
        print(f"[control:describe dropped {A}] status={cc} raw={str(ccraw)[:160]}")
        if cc != 404:
            print(f"CONTROL_ANOMALY describe of dropped collection returned {cc} — cannot establish 'deleted'")
            return "SCRIPT_ERROR"

        # ---- negative: the dangling alias must have vanished; the sibling must persist ----
        mode, mine2, s2, raw2 = read_face(PFX)
        if mode == "ENV_DOWN":
            return "SCRIPT_ERROR"
        if mode == "FACE_DEFECT":
            DEFECTS.append(
                f"post-drop: GET /aliases face failed ({s2}) — unit promises 200 "
                f"raw={str(raw2)[:200]}"
            )
        else:
            if ALA in mine2:
                # G9 cross-face evidence: what does the dangling alias resolve to?
                ra, raraw = rt.request("GET", "describe_collection", path_params={"name": ALA})
                print(f"[cross-face:describe via dangling alias {ALA}] status={ra} raw={str(raraw)[:200]}")
                DEFECTS.append(
                    f"post-drop: alias {ALA} still listed on GET /aliases after its target "
                    f"collection {A} was deleted (describe control = 404); listed mapping "
                    f"{ALA}->{mine2.get(ALA)}; resolution via the alias name returns {ra} "
                    f"— dangling post-delete residue on the global list "
                    f"— Type4_StateLogicViolation"
                )
            else:
                print(f"post-drop OK: {ALA} removed from global listing")
            if mine2.get(ALB) != B:
                DEFECTS.append(
                    f"post-drop: unaffected sibling alias lost or corrupted: expected "
                    f"{{{ALB}: {B}}}, prefix map = {mine2} — Type4_StateLogicViolation"
                )
            else:
                print(f"sibling control OK: {ALB}->{B} persists")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        # collection A may already be dropped; both drops are best-effort
        try:
            rt.request("POST", "update_aliases", {"actions": [
                {"delete_alias": {"alias_name": ALA}},
                {"delete_alias": {"alias_name": ALB}},
            ]})
        except Exception:
            pass
        for c in (A, B):
            try:
                rt.drop_collection(c)
            except Exception:
                pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
