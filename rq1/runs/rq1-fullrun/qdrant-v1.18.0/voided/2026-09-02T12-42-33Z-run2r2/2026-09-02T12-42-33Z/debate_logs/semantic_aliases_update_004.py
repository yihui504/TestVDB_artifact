#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_aliases_update_004
# strategy: diagnosis_quality
# endpoint: aliases+update
# constraint_ids: qdrant_behavioral_aliases_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/update-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - Type-2 diagnostics quality of the documented error paths)
"""
Attack: diagnosis_quality x qdrant_behavioral_aliases_update_001 (chunk_aliases+update; strategy 2, documented error matrix + Type-2 rubric)
Oracle: for each documented error case the status lands in its documented set - (1) create_alias -> missing collection: exactly HTTP 404; (2) delete_alias of an unknown alias: 404 or 500; (3) rename_alias with unknown old_alias_name: 404 or 500 - and the rejection text scores >=1/3 on the rubric (parameter_named 1pt + format_hint 1pt + actionable 1pt); score 0/3 (names neither the offending parameter nor any format/action hint, e.g. a bare 'internal error') => Type2_PoorDiagnostics; a 2xx on any case => Type1_IllegalSuccess; create_alias-missing returning a NON-404 4xx => Type4 doc-drift (the assertion pins 404)

Assertion qdrant_behavioral_aliases_update_001 (evidence_tier=explicit):
  expected_behavior: "valid alias batch returns HTTP 200; create_alias on a
  missing collection returns 404; delete/rename of an unknown alias returns
  404 or 500" (source: v-1-18-x api-reference aliases/update-aliases).

Positive control first (G4): a valid create/delete pair on a real
collection must return 200, otherwise the error-path probing is
groundless. Then the three documented negative cases are fired and each
rejection text is scored with the Type-2 rubric from the spec:
  criterion 1 (parameter_named): the message mentions the offending
  entity class/parameter (collection / alias);
  criterion 2 (format_hint): 'must be' / 'expected' / 'valid' / 'type' /
  'range' / ... ;
  criterion 3 (actionable): 'use' / 'provide' / 'specify' / 'correct' /
  ... .
A rejection that scores 0/3 is unactionable - the user cannot tell WHICH
parameter was wrong nor what to do - which is exactly the Type2 class.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP
via rt.request path_key (update_aliases / create_collection via
setup_default / drop_collection / healthz); literal paths forbidden.
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
def error_text(raw):
    """Full rejection text (whole body lowercased - envelope fields like
    status.error are implementation detail per threat model, so the whole
    body is scanned)."""
    return str(raw).lower()


def check_error_quality(raw, expected_param):
    """Type-2 rubric (spec strategy 2): parameter_named + format_hint +
    actionable, each 1pt. Returns (score, max_score)."""
    msg = error_text(raw)
    score = 0
    if expected_param.lower() in msg:
        score += 1
    format_hints = ["must be", "expected", "should be", "valid", "range",
                    "type", "positive", "non-zero"]
    if any(h in msg for h in format_hints):
        score += 1
    action_hints = ["correct", "try", "use", "change", "specify", "provide"]
    if any(h in msg for h in action_hints):
        score += 1
    return score, 3


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
PREFIX = f"s2au4_{TS}_"
COL = PREFIX + "col"
MISSING = PREFIX + "no_such_collection"
CTRL = PREFIX + "ctrl"          # positive-control alias
DEL_UNK = PREFIX + "no_such_alias_del"
REN_UNK = PREFIX + "no_such_alias_old"
REN_NEW = PREFIX + "ren_new"
ALIASES = (CTRL, REN_NEW)
COLLECTIONS = (COL,)


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


try:
    # ---- setup + positive control (G4): valid create must be 200 ----
    ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL}: {err}")
    s, raw = rt.request("POST", "update_aliases", {"actions": [
        {"create_alias": {"collection_name": COL, "alias_name": CTRL}},
    ]})
    print(f"positive control create {CTRL}->{COL}: status={s} raw={raw[:200]}")
    if s == 0 or 500 <= s <= 599:
        alive = liveness_ok()
        script_error(f"alias API unavailable (status={s}, server alive={alive}); no defect conclusion")
    if s != 200:
        script_error(f"positive control create_alias failed: {s} {raw[:300]}")
    SETUP_OK = True

    findings = []

    # ---- case 1: create_alias -> missing collection (documented: exactly 404) ----
    st1, raw1 = rt.request("POST", "update_aliases", {"actions": [
        {"create_alias": {"collection_name": MISSING, "alias_name": PREFIX + "never"}},
    ]}, timeout=15)
    score1, _ = check_error_quality(raw1, "collection")
    print(f"case1 create_alias->missing collection: status={st1} score={score1}/3 raw={raw1[:300]}")
    if st1 in (200, 201):
        defect("Type1_IllegalSuccess",
               f"create_alias on missing collection '{MISSING}' returned {st1} - the assertion "
               f"documents 404. raw={raw1[:200]}")
    if st1 == 0 or 500 <= st1 <= 599:
        # 500 is NOT in case 1's documented set (only 404 is)
        alive = liveness_ok()
        if not alive:
            script_error(f"case1 failed at transport level (status={st1}) and /healthz dead; no defect conclusion")
        findings.append(("case1", st1, score1,
                         f"create_alias on a missing collection is documented to return exactly "
                         f"404, got {st1} while /healthz is alive (doc-drift); raw={raw1[:160]}"))
    elif st1 != 404:
        findings.append(("case1", st1, score1,
                         f"create_alias on a missing collection is documented to return exactly "
                         f"404, got {st1} (doc-drift); raw={raw1[:160]}"))
    if score1 == 0:
        defect("Type2_PoorDiagnostics",
               f"case1 (create_alias -> missing collection, status={st1}) rejection message "
               f"scores 0/3 on the diagnostics rubric - it names neither the offending "
               f"'collection' parameter nor any format/action hint, so the user cannot tell "
               f"what to fix; raw={raw1[:300]}")

    # ---- case 2: delete_alias of an unknown alias (documented: 404 or 500) ----
    st2, raw2 = rt.request("POST", "update_aliases", {"actions": [
        {"delete_alias": {"alias_name": DEL_UNK}},
    ]}, timeout=15)
    score2, _ = check_error_quality(raw2, "alias")
    print(f"case2 delete_alias unknown '{DEL_UNK}': status={st2} score={score2}/3 raw={raw2[:300]}")
    if st2 in (200, 201):
        defect("Type1_IllegalSuccess",
               f"delete_alias of unknown alias '{DEL_UNK}' returned {st2} - the assertion "
               f"documents 404 or 500. raw={raw2[:200]}")
    if st2 == 0 or 500 <= st2 <= 599:
        alive = liveness_ok()
        if not alive:
            script_error(f"case2 transport-level failure (status={st2}) and /healthz dead; no defect conclusion")
    elif st2 != 404:
        findings.append(("case2", st2, score2,
                         f"delete_alias of an unknown alias is documented to return 404 or 500, "
                         f"got {st2} (doc-drift); raw={raw2[:160]}"))
    if score2 == 0:
        defect("Type2_PoorDiagnostics",
               f"case2 (delete_alias of unknown alias, status={st2}) rejection message scores "
               f"0/3 on the diagnostics rubric - no offending parameter named, no format hint, "
               f"no actionable suggestion; raw={raw2[:300]}")

    # ---- case 3: rename_alias with unknown old_alias_name (documented: 404 or 500) ----
    st3, raw3 = rt.request("POST", "update_aliases", {"actions": [
        {"rename_alias": {"old_alias_name": REN_UNK, "new_alias_name": REN_NEW}},
    ]}, timeout=15)
    score3, _ = check_error_quality(raw3, "alias")
    print(f"case3 rename_alias unknown old '{REN_UNK}': status={st3} score={score3}/3 raw={raw3[:300]}")
    if st3 in (200, 201):
        defect("Type1_IllegalSuccess",
               f"rename_alias of unknown alias '{REN_UNK}' returned {st3} - the assertion "
               f"documents 404 or 500. raw={raw3[:200]}")
    if st3 == 0 or 500 <= st3 <= 599:
        alive = liveness_ok()
        if not alive:
            script_error(f"case3 transport-level failure (status={st3}) and /healthz dead; no defect conclusion")
    elif st3 != 404:
        findings.append(("case3", st3, score3,
                         f"rename of an unknown alias is documented to return 404 or 500, "
                         f"got {st3} (doc-drift); raw={raw3[:160]}"))
    if score3 == 0:
        defect("Type2_PoorDiagnostics",
               f"case3 (rename_alias with unknown old alias, status={st3}) rejection message "
               f"scores 0/3 on the diagnostics rubric - unactionable generic error; "
               f"raw={raw3[:300]}")

    # ---- post-condition: none of the failing cases may leave state behind ----
    stl, lraw = rt.request("GET", "list_aliases", timeout=10)
    try:
        lb = json.loads(lraw) if lraw else {}
        lres = lb.get("result") if isinstance(lb, dict) else None
        lentries = lres.get("aliases") if isinstance(lres, dict) else lres
    except Exception:
        lentries = None
    if stl == 200 and isinstance(lentries, list):
        leaked = [it for it in lentries if isinstance(it, dict)
                  and str(it.get("alias_name", "")).startswith(PREFIX)
                  and it.get("alias_name") not in (CTRL,)]
        print(f"scoped aliases after error cases: "
              f"{[it.get('alias_name') for it in lentries if isinstance(it, dict) and str(it.get('alias_name', '')).startswith(PREFIX)]}")
        if leaked:
            defect("Type4_StateLogicViolation",
                   f"rejected alias operations left state behind: {leaked} (only the positive "
                   f"control {CTRL} may exist in the prefix scope)")

    if findings:
        label, fst, score, msg = findings[0]
        defect("Type4_StateLogicViolation", f"[{label}] {msg}")

    print(f"rubric scores: case1={score1}/3 case2={score2}/3 case3={score3}/3 "
          f"(threshold for Type2 is 0/3; statuses all inside their documented sets)")
    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
