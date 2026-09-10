#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_aliases_update_002
# strategy: delete_consistency
# endpoint: aliases+update
# constraint_ids: qdrant_behavioral_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (post-failure state residue: phantom alias rows created by a FAILED batch)
"""
Attack: delete_consistency (post-failure state on the alias mutation face,
  POST /collections/aliases = contract path aliases+update): positive = a
  valid single create_alias batch must 200 and be listed; negatives = the
  three failure promises of the assertion, each followed by a face check
  that NOTHING appeared: (N1) create_alias -> missing collection promised
  404; (N2) delete_alias of an unknown alias promised 404 or 500; (N3)
  rename_alias with an unknown old_alias_name promised 404 or 500 and its
  new_alias_name must not be born as a phantom row
  x qdrant_behavioral_aliases_update_001
  [chunk_aliases+update coverage: delete_consistency x
   qdrant_behavioral_aliases_update_001 (all three status promises)]
Oracle: valid batch -> 200 (judge_200) with al1->A listed at the end; N1 ->
  404 exactly (2xx = Type1_IllegalSuccess; 400/422 = rejection with a
  differing disposition, recorded as a G9 note); N2/N3 -> 404 or 500 (200 =
  Type1_IllegalSuccess); after every failure GET /aliases prefix face is
  unchanged: no phantom bad/unknown/renamed-new rows (phantom =
  Type4_StateLogicViolation)
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


def alive():
    """D3b liveness re-check via the lightweight health endpoint."""
    hs, hraw = rt.request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def alias_face(pfx):
    """GET /aliases global face -> (mode, prefix-map or None, status, raw)."""
    s, raw = rt.request("GET", "list_aliases")
    print(f"[list_aliases] status={s} raw={raw[:800]}")
    if s == 0 or 500 <= s <= 599 or s in (401, 403):
        alive()
        return "ENV_DOWN", None, s, raw
    if s != 200:
        return "FACE_DEFECT", None, s, raw
    mapping, anoms = parse_aliases(raw)
    if mapping is None:
        return "FACE_DEFECT", None, s, raw
    mine = {a: c for a, c in mapping.items() if str(a).startswith(pfx)}
    return "OK", mine, s, raw


def judge_failure_promise(label, s, raw, promised):
    """Expected-vs-actual comparison against an explicit failure promise.

    promised = set of status codes the contract assertion accepts for this
    action. 2xx = the promised failure did not happen (Type1_IllegalSuccess);
    4xx outside the promise = rejection with differing disposition (G9 note,
    not a defect); 5xx outside the promise = liveness-gated Type3.
    Returns (kind, detail) with kind in {OK, NOTE, DEFECT, ENV_DOWN}.
    """
    if s == 0:
        return ("ENV_DOWN", f"{label}: transport failure {str(raw)[:120]}")
    if 200 <= s <= 299:
        return ("DEFECT",
                f"{label}: returned {s} but the assertion promises failure "
                f"{sorted(promised)} — Type1_IllegalSuccess raw={str(raw)[:200]}")
    if s in promised:
        return ("OK", f"{label}: {s} matches the promise {sorted(promised)}")
    if 400 <= s <= 499:
        return ("NOTE",
                f"{label}: rejected with {s}, promise was {sorted(promised)} — "
                f"disposition differs (G9 observation, rejection is not a defect) "
                f"raw={str(raw)[:200]}")
    # 5xx outside the promise: liveness re-check before any Type3 claim
    if alive():
        return ("DEFECT",
                f"{label}: 5xx ({s}) outside the promise {sorted(promised)} while the "
                f"service is alive — Type3_RuntimeFailure raw={str(raw)[:200]}")
    return ("ENV_DOWN", f"{label}: 5xx ({s}) and healthz down — environment failure")


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sau2_" + TS + "_"
    A = PFX + "colA"
    MISSING = PFX + "no_such_col"
    AL1 = PFX + "al1"                 # positive-control alias (must survive everything)
    BAD_CREATE = PFX + "bad_create"   # N1 alias name (must never exist)
    UNKNOWN_DEL = PFX + "unknown_del" # N2 alias name (never created)
    REN_OLD = PFX + "ren_old"         # N3 old name (never created)
    REN_NEW = PFX + "ren_new"         # N3 new name (must not be born as phantom)
    DEFECTS = []
    NOTES = []

    try:
        # ---- setup ----
        ok, err = rt.setup_default(A, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {A}: {err}")
            return "SCRIPT_ERROR"

        # ---- positive: valid single create_alias batch -> 200 ----
        s, raw = rt.request("POST", "update_aliases", {"actions": [
            {"create_alias": {"collection_name": A, "alias_name": AL1}},
        ]})
        print(f"[positive valid create] status={s} raw={raw[:300]}")
        v = rt.judge_200(s, raw, setup_ok=True)
        if v == "SCRIPT_ERROR":
            alive()
            return "SCRIPT_ERROR"
        if v == "DEFECT_FOUND":
            DEFECTS.append(
                f"positive: valid create_alias batch returned {s}, promised 200 "
                f"raw={str(raw)[:200]}"
            )

        mode, mine, fs, fraw = alias_face(PFX)
        if mode == "ENV_DOWN":
            return "SCRIPT_ERROR"
        if mode == "FACE_DEFECT":
            DEFECTS.append(f"positive: GET /aliases face failed ({fs}) raw={str(fraw)[:200]}")
        elif mine.get(AL1) != A:
            DEFECTS.append(
                f"positive: after a 200 create batch, {AL1} maps to {mine.get(AL1)} "
                f"instead of {A} — write invisible on the listing face — "
                f"Type4_StateLogicViolation"
            )
        else:
            print(f"positive control OK: {AL1}->{A}")

        # ---- N1: create_alias -> missing collection, promised 404 ----
        s, raw = rt.request("POST", "update_aliases", {"actions": [
            {"create_alias": {"collection_name": MISSING, "alias_name": BAD_CREATE}},
        ]})
        print(f"[N1 create-on-missing] status={s} raw={raw[:300]}")
        kind, detail = judge_failure_promise("N1 create-on-missing", s, raw, {404})
        print(f"N1 verdict: {kind} — {detail}")
        if kind == "DEFECT":
            DEFECTS.append(detail)
        elif kind == "NOTE":
            NOTES.append(detail)
        elif kind == "ENV_DOWN":
            return "SCRIPT_ERROR"

        # ---- N2: delete_alias of an unknown alias, promised 404 or 500 ----
        s, raw = rt.request("POST", "update_aliases", {"actions": [
            {"delete_alias": {"alias_name": UNKNOWN_DEL}},
        ]})
        print(f"[N2 delete-unknown] status={s} raw={raw[:300]}")
        kind, detail = judge_failure_promise("N2 delete-unknown", s, raw, {404, 500})
        print(f"N2 verdict: {kind} — {detail}")
        if kind == "DEFECT":
            DEFECTS.append(detail)
        elif kind == "NOTE":
            NOTES.append(detail)
        elif kind == "ENV_DOWN":
            return "SCRIPT_ERROR"

        # ---- N3: rename_alias with unknown old name, promised 404 or 500 ----
        s, raw = rt.request("POST", "update_aliases", {"actions": [
            {"rename_alias": {"old_alias_name": REN_OLD, "new_alias_name": REN_NEW}},
        ]})
        print(f"[N3 rename-unknown] status={s} raw={raw[:300]}")
        kind, detail = judge_failure_promise("N3 rename-unknown", s, raw, {404, 500})
        print(f"N3 verdict: {kind} — {detail}")
        if kind == "DEFECT":
            DEFECTS.append(detail)
        elif kind == "NOTE":
            NOTES.append(detail)
        elif kind == "ENV_DOWN":
            return "SCRIPT_ERROR"

        # ---- post-failure residue: no phantom rows, control alias intact ----
        mode, mine2, fs2, fraw2 = alias_face(PFX)
        if mode == "ENV_DOWN":
            return "SCRIPT_ERROR"
        if mode == "FACE_DEFECT":
            DEFECTS.append(f"post-failure: GET /aliases face failed ({fs2}) raw={str(fraw2)[:200]}")
        else:
            phantoms = sorted(n for n in (BAD_CREATE, UNKNOWN_DEL, REN_OLD, REN_NEW)
                              if n in mine2)
            if phantoms:
                DEFECTS.append(
                    f"post-failure: alias row(s) {phantoms} exist on GET /aliases "
                    f"although every operation that could create them was rejected "
                    f"— phantom residue — Type4_StateLogicViolation"
                )
            else:
                print("post-failure residue check OK: no phantom rows")
            if mine2.get(AL1) != A:
                DEFECTS.append(
                    f"post-failure: control alias {AL1} maps to {mine2.get(AL1)} "
                    f"instead of {A} — collateral damage from rejected batches — "
                    f"Type4_StateLogicViolation"
                )
            else:
                print(f"control alias intact: {AL1}->{A}")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.request("POST", "update_aliases", {"actions": [
                {"delete_alias": {"alias_name": n}} for n in
                (AL1, BAD_CREATE, UNKNOWN_DEL, REN_OLD, REN_NEW)
            ]})
        except Exception:
            pass
        try:
            rt.drop_collection(A)
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
