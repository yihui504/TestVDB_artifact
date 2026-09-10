#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_collection_info_003
# strategy: diagnosis_quality
# endpoint: cluster+collection+info
# constraint_ids: qdrant_behavioral_cluster_collection_info_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - Type-2 diagnostics quality of the documented 404 path)
"""
Attack: diagnosis_quality x qdrant_behavioral_cluster_collection_info_001 (chunk_cluster+collection+info; strategy 2, documented 404 path + Type-2 rubric)
Oracle: for both unknown-collection faces (never-created name and already-deleted name) the status is exactly 404 and the rejection text scores >= 1/3 on the rubric (named 1pt + hint 1pt + actionable 1pt); score 0/3 - a rejection that names neither the collection nor any existence/format hint nor any action - is Type2_PoorDiagnostics; a 2xx on either face is Type1_IllegalSuccess (disposition defect, cross-ref script 001); a 5xx with /healthz alive is Type3

Assertion qdrant_behavioral_cluster_collection_info_001 (evidence_tier=explicit):
  "existing collection: HTTP 200 with cluster info; unknown collection: HTTP
  404" (doc-grounded endpoint_registry quote, not synthesis).

Type-2 rubric (spec strategy 2), adapted to 404-not-found semantics and
declared here per G7 (envelope field names like status/error are implementation
detail per the threat model, so the whole body text is scanned):
  criterion 1 (named):    the offending collection NAME appears in the message;
  criterion 2 (hint):     an existence/format statement - "not found",
                          "not exist", "unknown", "missing", "no collection",
                          or the spec's format hints (must be / expected /
                          valid / type / range / ...);
  criterion 3 (action):   an actionable suggestion - the spec's action hints
                          (use / provide / specify / correct / ...) or
                          404-appropriate actions (check / verify / list).
A 0/3 rejection (e.g. bare "internal error" or an empty body) leaves the user
unable to tell WHICH name was wrong or what to do - exactly the Type2 class.

G9 consistency: never-created and deleted names are the same "unknown
collection" family on this endpoint; both faces are scored and both must clear
the threshold. Positive control first (G4): an existing collection must answer
200, otherwise error-path probing is groundless.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (collection_cluster / create_collection via setup_default /
describe_collection / drop_collection / healthz); literal paths forbidden.
Transport-failure branches re-check liveness via an inline
safe_request("GET","healthz") probe with a printed status (the probe call is
directly visible in the branch).
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
def safe_request(method, path_key, path_params=None):
    """Health-probe form over the target runtime (DB-neutral path_key): a thin
    delegation to rt.request so transport-failure branches carry a directly
    visible probe call (same fix shape as state_cluster_collection_info_001)."""
    return rt.request(method, path_key, path_params=path_params)


def check_error_quality(raw, collection_name):
    """Type-2 rubric (spec strategy 2) adapted to 404 semantics:
    named + hint + actionable, 1pt each. Returns (score, 3)."""
    msg = str(raw).lower()
    score = 0
    # criterion 1: the offending parameter (the collection name) is named
    if collection_name.lower() in msg:
        score += 1
    # criterion 2: existence/format statement
    hints = ["not found", "not exist", "doesn't exist", "does not exist",
             "unknown", "missing", "no collection",
             "must be", "expected", "should be", "valid", "range", "type",
             "positive", "non-zero"]
    if any(h in msg for h in hints):
        score += 1
    # criterion 3: actionable suggestion
    actions = ["correct", "try", "use", "change", "specify", "provide",
               "check", "verify", "list", "make sure"]
    if any(h in msg for h in actions):
        score += 1
    return score, 3


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


TS = str(int(time.time()))
PREFIX = f"s4ci3_{TS}_"
COL = PREFIX + "col_ctrl"
COL_DEL = PREFIX + "col_del"
GHOST = PREFIX + "no_such_collection"
COLLECTIONS = (COL, COL_DEL)


def cleanup():
    for name in COLLECTIONS:
        try:
            rt.drop_collection(name)
        except Exception:
            pass


def probe_404_face(name, context):
    """Fire the documented 404 path once; returns (status, raw, score).
    Disposition defects (2xx / 5xx-alive / non-404 4xx) exit here, mirroring
    script 001's oracle so this script stays self-contained."""
    st, raw = rt.request("GET", "collection_cluster", path_params={"name": name})
    score, _ = check_error_quality(raw, name)
    print(f"[{context}] cluster info of '{name}': status={st} score={score}/3 raw={raw[:300]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure probing {context} name (status=0, /healthz={hs}); no defect conclusion")
    if 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[5xx liveness] /healthz probe status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            script_error(f"5xx probing {context} name and /healthz probe not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"unknown collection '{name}' ({context}) is documented to return 404; got server error "
               f"{st} while /healthz probe is 200 (alive); raw={raw[:200]}")
    if 200 <= st < 300:
        defect("Type1_IllegalSuccess",
               f"assertion promises HTTP 404 for unknown collection '{name}' ({context}); got {st}; "
               f"raw={raw[:200]}")
    if st != 404:
        defect("Type4_StateLogicViolation",
               f"assertion pins 404 for unknown collection '{name}' ({context}); got unexpected "
               f"status {st}; raw={raw[:200]}")
    return st, raw, score


try:
    # ---- positive control (G4): existing collection must answer 200 ----
    ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL}: {err}")
    SETUP_OK = True
    st, raw = rt.request("GET", "collection_cluster", path_params={"name": COL})
    print(f"positive control on '{COL}': status={st} raw={raw[:200]}")
    if st == 0 or 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[positive control transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"cluster info unavailable for existing collection (status={st}, /healthz={hs})")
    if st != 200:
        script_error(f"positive control failed: existing collection '{COL}' answered {st}: {raw[:300]}")

    # ---- face (a): never-created collection name ----
    st_a, raw_a, score_a = probe_404_face(GHOST, "never-created")
    if score_a == 0:
        defect("Type2_PoorDiagnostics",
               f"[never-created] the 404 rejection for '{GHOST}' scores 0/3 on the diagnostics rubric - "
               f"it names neither the offending collection name nor any existence/format hint nor any "
               f"actionable suggestion, so the user cannot tell what to fix; raw={raw_a[:300]}")

    # ---- face (b): collection that existed and was deleted ----
    ok, err = rt.setup_default(COL_DEL, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL_DEL}: {err}")
    st, raw = rt.request("DELETE", "drop_collection", path_params={"name": COL_DEL}, timeout=20)
    print(f"delete {COL_DEL}: status={st} raw={raw[:160]}")
    if st == 0 or 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[delete transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport/server failure deleting {COL_DEL} (status={st}, /healthz={hs})")
    if st != 200:
        script_error(f"setup delete failed for {COL_DEL}: {st} {raw[:300]}")
    gone = False
    for _ in range(50):
        st, _raw = rt.request("GET", "describe_collection", path_params={"name": COL_DEL}, timeout=10)
        if st == 404:
            gone = True
            break
        time.sleep(0.2)
    if not gone:
        script_error(f"collection {COL_DEL} still exists after delete (status {st}); cannot test the deleted-name face")

    st_b, raw_b, score_b = probe_404_face(COL_DEL, "deleted")
    if score_b == 0:
        defect("Type2_PoorDiagnostics",
               f"[deleted] the 404 rejection for '{COL_DEL}' scores 0/3 on the diagnostics rubric - "
               f"unactionable generic rejection with no collection named and no existence hint; "
               f"raw={raw_b[:300]}")

    # ---- G9 note: same family, both faces scored; both must clear 0/3 ----
    print(f"rubric scores: never-created={score_a}/3 deleted={score_b}/3 "
          f"(threshold for Type2 is 0/3; both statuses were exactly 404)")
    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
