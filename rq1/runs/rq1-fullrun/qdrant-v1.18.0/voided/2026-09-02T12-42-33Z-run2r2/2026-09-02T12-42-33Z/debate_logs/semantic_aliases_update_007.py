#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_aliases_update_007
# strategy: metamorphic
# endpoint: aliases+update
# constraint_ids: qdrant_state_aliases_update_001, qdrant_bc_alias_switch_atomic_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - two encodings of one semantic operation must not diverge)
"""
Attack: metamorphic x qdrant_state_aliases_update_001 + qdrant_bc_alias_switch_atomic_001 (chunk_aliases+update; strategy 6, rename_alias vs [delete_alias+create_alias] encoding equivalence)
Oracle: starting from identical prefix states, encoding R = single-action batch [rename_alias A0->A1] and encoding D = two-action batch [delete_alias B0 + create_alias B1->CA] BOTH return HTTP 200 with result=true and leave the SAME observable-state signature: (i) old name absent from the scoped alias map, (ii) new name present and owned by CA, (iii) scroll through the new name returns exactly the id set {1..5}; divergence in status or in ANY signature component between the two encodings => Type4_StateLogicViolation (and a non-200 on either encoding => Type1_IllegalRejection)

Metamorphic relation (follow-up relation over one semantic operation):
  semantic op: "re-point readers from alias name X to alias name Y while
  keeping the same target collection".
  encoding R (primitive): one rename_alias action.
  encoding D (composite): delete_alias X + create_alias Y in one atomic
  batch - the same "atomic request" unit the constraint
  qdrant_state_aliases_update_001 declares ("alias changes are ATOMIC: no
  collection modifications can happen between the alias operations of one
  request").
  Invariant: both encodings are documented to end in the same state; any
  component where they diverge (status class, map content, read-back ids)
  exposes a behavioral inconsistency between the primitive and composite
  paths of the same endpoint (BS-05).

Why this mutation point (G6): the two-action encoding is the exact
payload used for zero-downtime switching (semantic_aliases_update_001);
if the server applied it non-atomically or validated it against the
pre-batch state, encoding D fails while encoding R succeeds - maximal
divergence between two supposedly equivalent forms.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP
via rt.request path_key (update_aliases / list_aliases / upsert_points /
count / scroll / create_collection via setup_default / drop_collection /
healthz); literal paths forbidden.
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

SETUP_OK = False


# ---------------- helpers ----------------
def parse_json(raw):
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def scroll_ids(raw):
    b = parse_json(raw)
    if b is None:
        return None
    res = b.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("points"), list):
        return None
    return [p.get("id") for p in res["points"] if isinstance(p, dict)]


def count_value(raw):
    b = parse_json(raw)
    if b is None:
        return None
    res = b.get("result")
    if isinstance(res, dict) and isinstance(res.get("count"), int):
        return res["count"]
    return None


def scoped_map():
    st, raw = rt.request("GET", "list_aliases", timeout=10)
    if st != 200:
        return None
    b = parse_json(raw)
    if b is None:
        return None
    res = b.get("result")
    entries = None
    if isinstance(res, dict) and isinstance(res.get("aliases"), list):
        entries = res["aliases"]
    elif isinstance(res, list):
        entries = res
    if entries is None:
        return None
    return sorted((it.get("alias_name"), it.get("collection_name")) for it in entries
                  if isinstance(it, dict) and str(it.get("alias_name", "")).startswith(PREFIX))


def liveness_ok():
    try:
        st, _ = rt.request("GET", "healthz", timeout=5)
        return st == 200
    except Exception:
        return False


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


TS = str(int(time.time()))
PREFIX = f"s2au7_{TS}_"
CA = PREFIX + "ca"
A0 = PREFIX + "a0"   # encoding R: old name
A1 = PREFIX + "a1"   # encoding R: new name
B0 = PREFIX + "b0"   # encoding D: old name
B1 = PREFIX + "b1"   # encoding D: new name
IDS = frozenset(range(1, 6))
COLLECTIONS = (CA,)
ALIASES = (A0, A1, B0, B1)


def cleanup():
    for al in ALIASES:
        try:
            rt.request("POST", "update_aliases",
                       {"actions": [{"delete_alias": {"alias_name": al}}]}, timeout=15)
        except Exception:
            pass
    for name in COLLECTIONS:
        try:
            rt.drop_collection(name)
        except Exception:
            pass


def fire(label, actions):
    st, raw = rt.request("POST", "update_aliases", {"actions": actions}, timeout=15)
    print(f"{label}: status={st} raw={raw[:240]}")
    if st == 0 or 500 <= st <= 599:
        alive = liveness_ok()
        if not alive:
            script_error(f"{label}: transport-level failure (status={st}) and /healthz dead; no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"{label}: returned status={st} while /healthz is alive; raw={raw[:200]}")
    if st != 200:
        defect("Type1_IllegalRejection",
               f"{label}: legal alias batch rejected with status={st} "
               f"(qdrant_behavioral_aliases_update_001: valid alias batch returns HTTP 200); "
               f"raw={raw[:300]}")
    b = parse_json(raw)
    res = b.get("result") if b else None
    if res is not True:
        defect("Type4_StateLogicViolation",
               f"{label}: 200 envelope must carry result=true per aliases+update "
               f"response_shape (result:boolean), got {res!r}; raw={raw[:200]}")
    return st, raw


def signature(old, new):
    """Observable-state signature after the rename op: (old_absent, new_owner, read_ids)."""
    m = scoped_map()
    if m is None:
        script_error("alias listing unavailable while computing the metamorphic signature")
    old_absent = all(p[0] != old for p in m)
    new_owner = None
    for a, c in m:
        if a == new:
            new_owner = c
    rs, rraw = rt.request("POST", "scroll",
                          {"limit": 10, "with_payload": False, "with_vector": False},
                          path_params={"name": new}, timeout=10)
    ids = scroll_ids(rraw) if rs == 200 else None
    print(f"signature for {new}: old_absent={old_absent} new_owner={new_owner} read_ids={ids} (status={rs})")
    return {"old_absent": old_absent, "new_owner": new_owner,
            "read_ids": None if ids is None else sorted(ids), "read_status": rs}


try:
    # ---- setup: one collection with a 5-point fixture ----
    ok, err = rt.setup_default(CA, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {CA}: {err}")
    pts = [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in sorted(IDS)]
    s, raw = rt.request("PUT", "upsert_points", {"points": pts},
                        path_params={"name": CA})
    print(f"setup upsert {CA}: status={s} raw={raw[:160]}")
    if s not in (200, 201):
        script_error(f"setup upsert into {CA} failed: {s} {raw[:200]}")
    seen = None
    for _ in range(12):
        cs, craw = rt.request("POST", "count", {"exact": True},
                              path_params={"name": CA}, timeout=10)
        seen = count_value(craw) if cs == 200 else None
        if seen == 5:
            break
        time.sleep(0.3)
    if seen != 5:
        script_error(f"fixture {CA} not countable at 5 (last count={seen})")
    SETUP_OK = True

    # ---- phase R: primitive encoding (single rename_alias action) ----
    fire("phase R arrange create a0",
         [{"create_alias": {"collection_name": CA, "alias_name": A0}}])
    fire("phase R rename_alias a0->a1 (single-action batch)",
         [{"rename_alias": {"old_alias_name": A0, "new_alias_name": A1}}])
    sig_r = signature(A0, A1)

    # ---- phase D: composite encoding (delete + create in one atomic batch) ----
    fire("phase D arrange create b0",
         [{"create_alias": {"collection_name": CA, "alias_name": B0}}])
    fire("phase D [delete_alias b0 + create_alias b1] (two-action batch)",
         [{"delete_alias": {"alias_name": B0}},
          {"create_alias": {"collection_name": CA, "alias_name": B1}}])
    sig_d = signature(B0, B1)

    # ---- metamorphic comparison ----
    print(f"signature R (rename_alias)          : {sig_r}")
    print(f"signature D (delete+create batch)   : {sig_d}")

    if not sig_r["old_absent"]:
        defect("Type4_StateLogicViolation",
               f"encoding R (rename_alias) left the old name {A0} in the map - rename "
               f"semantics broken on the primitive path; map={scoped_map()}")
    if not sig_d["old_absent"]:
        defect("Type4_StateLogicViolation",
               f"encoding D (delete+create batch) left the old name {B0} in the map - "
               f"atomic two-action semantics broken; map={scoped_map()}")
    if sig_r["new_owner"] != CA or sig_d["new_owner"] != CA:
        defect("Type4_StateLogicViolation",
               f"the two encodings disagree on ownership: R new_owner={sig_r['new_owner']!r}, "
               f"D new_owner={sig_d['new_owner']!r}, both must be {CA}")
    if sig_r["read_ids"] != sorted(IDS) or sig_d["read_ids"] != sorted(IDS):
        defect("Type4_StateLogicViolation",
               f"reads through the renamed alias must return the fixture ids {sorted(IDS)} "
               f"under BOTH encodings; R read {sig_r['read_ids']}, D read {sig_d['read_ids']}")
    if sig_r["read_status"] != 200 or sig_d["read_status"] != 200:
        defect("Type4_StateLogicViolation",
               f"reads through the new alias names must return HTTP 200 under both "
               f"encodings; R status={sig_r['read_status']}, D status={sig_d['read_status']}")

    m = scoped_map()
    if m != [(A1, CA), (B1, CA)]:
        defect("Type4_StateLogicViolation",
               f"after both encodings the scoped map must be exactly "
               f"[({A1}, {CA}), ({B1}, {CA})], got {m}")

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
