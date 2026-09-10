#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_collection_info_001
# strategy: behavioral_contract
# endpoint: cluster+collection+info
# constraint_ids: qdrant_behavioral_cluster_collection_info_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - behavioral consistency of the documented 200/404 disposition)
"""
Attack: behavioral_contract x qdrant_behavioral_cluster_collection_info_001 (chunk_cluster+collection+info; strategy 1, both faces of the documented disposition)
Oracle: GET cluster info of an existing collection returns HTTP 200 with a result object; for a collection name that does not exist (never-created, or already deleted) it returns exactly HTTP 404 - a 2xx on an unknown name is Type1_IllegalSuccess, a non-404 4xx is a wrong-disposition Type4, and a 5xx with /healthz alive is Type3 (assertion qdrant_behavioral_cluster_collection_info_001)

Assertion qdrant_behavioral_cluster_collection_info_001 (evidence_tier=explicit):
  expected_behavior: "existing collection: HTTP 200 with cluster info; unknown
  collection: HTTP 404" (endpoint_registry doc_quote: "Returns 200 with
  CollectionClusterInfo; 404 for an unknown collection.", verified against the
  v-1-18-x api-reference collection-cluster-info page - so the 404 promise is
  doc-grounded, not synthesis).

Both faces are exercised (G4 positive-negative pairing):
  positive: a freshly created collection answers 200 with the CollectionClusterInfo
            object under the result envelope;
  negative (a): a never-created collection name answers 404. This is also the
            regression probe for this session's confirmed R1 defect family
            "per-collection listing answered 200-on-unknown" - the same
            wrong-disposition shape on this sibling endpoint would silently mask
            typos/races (caller cannot distinguish 'no cluster info' from 'wrong
            collection name');
  negative (b): a collection that existed and was deleted must not keep answering
            200 (state-transition variant of the same promise).

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (collection_cluster / create_collection via setup_default /
describe_collection / drop_collection / healthz); literal paths forbidden;
2-tuple (status, raw). Transport-failure branches re-check liveness via an
inline safe_request("GET","healthz") probe with a printed status (the probe
call is directly visible in the branch).
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


def parse_result(raw):
    """Extract the result object from a qdrant envelope (lesson: result.<field>)."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    if isinstance(b, dict):
        return b.get("result")
    return None


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


TS = str(int(time.time()))
PREFIX = f"s4ci1_{TS}_"
COL_LIVE = PREFIX + "col_live"
COL_DEL = PREFIX + "col_del"
GHOST = PREFIX + "no_such_collection"
COLLECTIONS = (COL_LIVE, COL_DEL)


def cleanup():
    for name in COLLECTIONS:
        try:
            rt.drop_collection(name)
        except Exception:
            pass


def expect_404(name, context):
    """Shared oracle: cluster info of a non-existent collection must be exactly
    HTTP 404 (explicit expected-vs-actual comparison; the assertion pins the
    status, so no generic helper fits)."""
    st, raw = rt.request("GET", "collection_cluster", path_params={"name": name})
    print(f"cluster info of {context} collection '{name}': status={st} raw={raw[:300]}")
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
               f"unknown collection '{name}' is documented to return 404; got server error "
               f"{st} while /healthz probe is 200 (alive); raw={raw[:200]}")
    if 200 <= st < 300:
        defect("Type1_IllegalSuccess",
               f"assertion promises HTTP 404 for unknown collection '{name}' ({context}); got {st} with a "
               f"success payload instead - the R1 '200-on-unknown' disposition family on this endpoint; "
               f"raw={raw[:200]}")
    if st != 404:
        defect("Type4_StateLogicViolation",
               f"assertion pins 404 for unknown collection '{name}' ({context}); got unexpected status "
               f"{st} (wrong rejection class / doc drift); raw={raw[:200]}")
    return True


try:
    # ---- guard: make sure the ghost name really is free before probing ----
    try:
        rt.drop_collection(GHOST)
    except Exception:
        pass

    # ---- negative face (a): never-created collection name must 404 ----
    expect_404(GHOST, "never-created")

    # ---- positive face: existing collection must answer 200 + result object ----
    ok, err = rt.setup_default(COL_LIVE, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL_LIVE}: {err}")
    SETUP_OK = True
    st, raw = rt.request("GET", "collection_cluster", path_params={"name": COL_LIVE})
    print(f"cluster info of live collection '{COL_LIVE}': status={st} raw={raw[:500]}")
    v = rt.judge_200(st, raw, setup_ok=SETUP_OK)
    if v == "SCRIPT_ERROR":
        hs, hraw = safe_request("GET", "healthz")
        print(f"[judge SCRIPT_ERROR] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"cluster info unavailable for an existing collection (status={st}, /healthz={hs}); no defect conclusion")
    if v == "DEFECT_FOUND":
        defect("Type1_IllegalRejection",
               f"legal GET cluster info of existing collection '{COL_LIVE}' rejected: status={st} "
               f"(assertion expects HTTP 200); raw={raw[:300]}")
    res = parse_result(raw)
    if not isinstance(res, dict):
        defect("Type4_StateLogicViolation",
               f"200 response must carry the CollectionClusterInfo object under the result envelope; "
               f"got: {raw[:300]}")

    # ---- negative face (b): deleted collection must not keep answering 200 ----
    ok, err = rt.setup_default(COL_DEL, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL_DEL}: {err}")
    st, raw = rt.request("GET", "collection_cluster", path_params={"name": COL_DEL})
    print(f"pre-delete sanity on '{COL_DEL}': status={st} raw={raw[:200]}")
    if st != 200:
        script_error(f"pre-delete sanity failed for {COL_DEL}: {st} {raw[:300]}")
    st, raw = rt.request("DELETE", "drop_collection", path_params={"name": COL_DEL}, timeout=20)
    print(f"delete {COL_DEL}: status={st} raw={raw[:200]}")
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
        script_error(f"collection {COL_DEL} still exists after delete (status {st}); cannot test the deleted-name promise")

    expect_404(COL_DEL, "deleted")

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
