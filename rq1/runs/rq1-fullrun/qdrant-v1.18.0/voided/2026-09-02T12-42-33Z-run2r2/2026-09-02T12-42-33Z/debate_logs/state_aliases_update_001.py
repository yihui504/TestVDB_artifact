#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_aliases_update_001
# strategy: transaction
# endpoint: aliases+update
# constraint_ids: qdrant_state_aliases_update_001, qdrant_behavioral_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (partial commit: alias operations of ONE request applied non-atomically)
"""
Attack: transaction (batch all-or-nothing on the alias mutation face,
  POST /collections/aliases = contract path aliases+update): positive = a
  valid-only batch [create al1->A, create al2->B] must return 200 and both
  rows must be visible on GET /aliases; negative = mixed batches embedding
  ONE illegal action (create_alias -> a missing collection, promised 404 by
  the behavioral assertion) next to valid actions in BOTH orders, plus a
  destructive rollback probe [delete_alias al1 + create_alias -> missing]:
  a rejected batch must leave ZERO of its actions applied
  x qdrant_state_aliases_update_001 (alias operations of one request are ATOMIC)
  x qdrant_behavioral_aliases_update_001 (create_alias on a missing collection -> 404)
  [chunk_aliases+update coverage: transaction x qdrant_state_aliases_update_001;
   transaction x qdrant_behavioral_aliases_update_001 (404 leg)]
Oracle: valid-only batch -> 200 with al1->A and al2->B listed; every mixed
  batch -> non-2xx and NONE of its own alias names (al3..al5) listed
  afterwards while al1 survives the rejected [delete al1 + invalid create]
  batch (any partially-applied row = Type4_StateLogicViolation; a 2xx for a
  batch containing a missing-collection create = Type1_IllegalSuccess)
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
    """GET /aliases global face. Returns (mode, prefix-map or None, status, raw).

    mode in {OK, FACE_DEFECT, ENV_DOWN}. Sibling-tolerant: only prefix-filtered
    entries are asserted (sandbox is shared between concurrently running scripts).
    """
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
    my_anoms = [x for x in anoms if pfx in str(x)]
    if my_anoms:
        print(f"[face anomalies within prefix] {my_anoms}")
    return "OK", (mine, my_anoms), s, raw


def apply_batch(label, actions):
    s, raw = rt.request("POST", "update_aliases", {"actions": actions})
    print(f"[{label}] status={s} raw={raw[:300]}")
    return s, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sau1_" + TS + "_"
    A = PFX + "colA"
    B = PFX + "colB"
    MISSING = PFX + "no_such_col"
    AL1, AL2 = PFX + "al1", PFX + "al2"          # positive-control aliases
    AL3, AL4 = PFX + "al3", PFX + "al4"          # mixed batch #1 (valid+invalid)
    AL5, AL6 = PFX + "al5", PFX + "al6"          # mixed batch #2 (invalid+valid, reversed)
    DEFECTS = []

    try:
        # ---- setup ----
        for c in (A, B):
            ok, err = rt.setup_default(c, 4, "Cosine")
            if not ok:
                print(f"SETUP_ERROR create {c}: {err}")
                return "SCRIPT_ERROR"

        # ---- positive: valid-only batch -> 200 + both rows visible ----
        s, raw = apply_batch("positive valid batch", [
            {"create_alias": {"collection_name": A, "alias_name": AL1}},
            {"create_alias": {"collection_name": B, "alias_name": AL2}},
        ])
        if s == 0 or 500 <= s <= 599 or s in (401, 403):
            alive()
            return "SCRIPT_ERROR"
        if s != 200:
            DEFECTS.append(
                f"positive: valid-only create batch returned {s} (promised 200 by "
                f"qdrant_behavioral_aliases_update_001) raw={str(raw)[:200]}"
            )
        else:
            mode, payload, fs, fraw = alias_face(PFX)
            if mode == "ENV_DOWN":
                return "SCRIPT_ERROR"
            if mode == "FACE_DEFECT":
                DEFECTS.append(
                    f"positive: GET /aliases face failed ({fs}) after a 200 alias batch "
                    f"raw={str(fraw)[:200]}"
                )
            else:
                mine, anoms = payload
                if anoms:
                    DEFECTS.append(f"positive: malformed/duplicate alias rows: {anoms}")
                if mine.get(AL1) != A or mine.get(AL2) != B:
                    DEFECTS.append(
                        f"positive: after a 200 create batch, prefix map = {mine}, "
                        f"expected {{{AL1}: {A}, {AL2}: {B}}} — write invisible on the "
                        f"listing face — Type4_StateLogicViolation"
                    )
                else:
                    print(f"positive control OK: {AL1}->{A}, {AL2}->{B}")

        # ---- negative: mixed batches (one illegal create -> missing collection) ----
        # atomicity promise: a rejected request applies NONE of its actions
        mixed_batches = [
            ("mixed#1 valid-then-invalid", [
                {"create_alias": {"collection_name": B, "alias_name": AL3}},
                {"create_alias": {"collection_name": MISSING, "alias_name": AL4}},
            ], {AL3, AL4}, {}),
            ("mixed#2 invalid-then-valid (reversed)", [
                {"create_alias": {"collection_name": MISSING, "alias_name": AL5}},
                {"create_alias": {"collection_name": A, "alias_name": AL6}},
            ], {AL5, AL6}, {}),
            ("mixed#3 destructive rollback (valid delete + invalid create)", [
                {"delete_alias": {"alias_name": AL1}},
                {"create_alias": {"collection_name": MISSING, "alias_name": PFX + "al7"}},
            ], {PFX + "al7"}, {AL1: A}),
        ]
        for label, actions, forbidden, must_survive in mixed_batches:
            s, raw = apply_batch(label, actions)
            if s == 0 or (500 <= s <= 599):
                # 5xx: batch WAS rejected; liveness first, then still check rollback
                if not alive():
                    return "SCRIPT_ERROR"
                print(f"NOTE: {label} rejected with {s} (promised face for the "
                      f"embedded create-on-missing is 404) — disposition recorded")
            elif 200 <= s <= 299:
                DEFECTS.append(
                    f"{label}: batch containing create_alias -> missing collection "
                    f"{MISSING} returned {s} — the assertion promises 404 for that "
                    f"action, so the whole batch must fail — Type1_IllegalSuccess "
                    f"raw={str(raw)[:200]}"
                )
            # any non-2xx (and also after a 2xx, for evidence) -> no action may persist
            mode, payload, fs, fraw = alias_face(PFX)
            if mode == "ENV_DOWN":
                return "SCRIPT_ERROR"
            if mode == "FACE_DEFECT":
                DEFECTS.append(
                    f"{label}: GET /aliases face failed ({fs}) after batch "
                    f"raw={str(fraw)[:200]}"
                )
                continue
            mine, anoms = payload
            leaked = sorted(n for n in forbidden if n in mine)
            if leaked:
                how = "despite the batch being rejected" if not (200 <= s <= 299) \
                    else "while the batch illegally succeeded"
                DEFECTS.append(
                    f"{label}: alias row(s) {leaked} visible {how} — partial commit "
                    f"of a one-request alias batch — Type4_StateLogicViolation "
                    f"(qdrant_state_aliases_update_001 atomicity)"
                )
            else:
                print(f"{label}: rollback clean ({sorted(forbidden)} all absent)")
            for survivor, target in must_survive.items():
                if mine.get(survivor) != target:
                    DEFECTS.append(
                        f"{label}: destructive action leaked through the rejected "
                        f"batch — {survivor} should still map to {target}, face says "
                        f"{mine.get(survivor)} — Type4_StateLogicViolation"
                    )
                else:
                    print(f"{label}: {survivor}->{target} survived the rejected batch")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        my_aliases = [AL1, AL2, AL3, AL4, AL5, AL6, PFX + "al7"]
        try:
            rt.request("POST", "update_aliases",
                       {"actions": [{"delete_alias": {"alias_name": a}} for a in my_aliases]})
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
