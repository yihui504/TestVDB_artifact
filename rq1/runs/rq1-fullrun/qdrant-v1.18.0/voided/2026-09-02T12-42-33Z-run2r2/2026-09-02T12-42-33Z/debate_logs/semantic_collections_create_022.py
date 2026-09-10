#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_022
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_005
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (documentation drift - the 'query schema minimum 1' is a
#   shared schema constraint; per-endpoint extractor wiring can drift so that
#   one face enforces it and a sibling face silently drops it)
"""
Attack: behavioral_contract (cross-face consistency, G9) x
  qdrant_behavioral_collections_create_005 (chunk_collections+create-2of2).
  The assertion (evidence_tier=explicit): timeout below 1 is rejected
  (query schema minimum 1) on collections+create. The boundary round
  (boundary_collections_create_007) already measured the create face alone
  (timeout=0 -> 422, timeout=1 -> 200, NO_DEFECT); re-testing those values
  on the same face would duplicate. This script anchors the create face
  ONCE (timeout=0 must be refused 4xx) and then asks the consistency
  question the boundary round could not: does the SAME shared-schema
  minimum hold on the sibling faces that accept the same query parameter
  (collections+update PATCH, collections+delete DELETE - both declare
  'timeout integer, query: min 1' in the contract parameter lists)?
  - update face: PATCH a benign legal diff (hnsw_config.m=16, the default)
      on an existing collection with ?timeout=0;
  - delete face: DELETE an existing collection with ?timeout=0 (on a
    sacrificial collection; if wrongly accepted the deletion side-effect
    is recorded, the defect is the acceptance);
  - closure on the sibling faces: the same calls with ?timeout=1 (the
    inclusive minimum) must be ACCEPTED - refusal there would be the
    opposite asymmetry (illegal rejection).
  Per G9: the same parameter accepted on one face while rejected on the
  anchor face = inconsistent disposition = defect signal, no extra
  contract endorsement needed.
  [chunk_collections+create-2of2 coverage: behavioral_contract x
   qdrant_behavioral_collections_create_005 (timeout-min-1 anchor +
   update/delete cross-face consistency + min-closure on sibling faces)]
Oracle: create with ?timeout=0 is refused 4xx (anchor; 200 here =
  Type1_IllegalSuccess); update-face PATCH (benign legal diff) ?timeout=0 and delete-face
  DELETE ?timeout=0 are ALSO refused 4xx - any sibling-face 200 =
  DEFECT_FOUND (Type1_IllegalSuccess, inconsistent disposition of the
  same parameter across interface faces per G9); the ?timeout=1 closure
  calls on both sibling faces return 2xx (refusal = Type1_Illegal-
  Rejection); 5xx with /healthz alive = Type3_RuntimeFailure -
  constraint qdrant_behavioral_collections_create_005.

Rationale (G6/G9): the mutation point is the FACE, not the value - the
  value's ground is settled; face wiring is where shared-schema validation
  historically leaks (one endpoint deserializes into the validating
  extractor, another into a lenient one). The delete-face leg uses a
  sacrificial collection so the destructive side-effect of a wrongly
  accepted call cannot corrupt shared state.
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
            _sd = str(_p)
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

print("[path derivation] create_collection/update_collection/drop_collection = "
      "/collections/{name} (raw_knowledge api_endpoints[].url); timeout is a URL "
      "query parameter on all three faces (v34 R1 S1 lesson: never in body)")

PREFIX = "scc022_"
RUN = str(int(time.time()))
CREATED = []


def safe_request(method, path_key, body=None, path_params=None, query_params=None, timeout=60):
    """All HTTP through the runtime; forwards method/path_key/body/path_params/
    query_params/timeout exactly (standing lesson). Returns (status, raw_text)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz", timeout=15)
    print(f"[{tag}] /healthz probe status={hs} raw={str(hraw)[:120]}")
    return hs


def mkn(tag):
    return f"{PREFIX}{RUN}_{tag}"


def make_coll(name):
    st, raw = safe_request("PUT", "create_collection",
                           {"vectors": {"size": 4, "distance": "Cosine"}},
                           path_params={"name": name})
    print(f"[create {name}] status={st} raw={str(raw)[:200]}")
    if st not in (200, 201):
        script_error(f"setup create {name} returned {st}; raw={str(raw)[:200]}")
    CREATED.append(name)


def guard(st, raw, tag):
    """Shared transport/5xx guard. Returns True when adjudication may proceed."""
    if st == 0:
        if liveness(f"transport-{tag}") != 200:
            script_error(f"{tag}: transport failure and /healthz down; no defect conclusion")
        script_error(f"{tag}: transport failure; /healthz alive; no defect conclusion")
    if 500 <= st <= 599:
        if liveness(f"5xx-{tag}") != 200:
            script_error(f"{tag}: 5xx ({st}) and /healthz not 200; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"{tag}: raised server error {st} while /healthz is alive; raw={str(raw)[:200]}")
    return True


def cleanup():
    for n in list(CREATED):
        try:
            rt.drop_collection(n)
        except Exception:
            pass


def main():
    hs, hraw = safe_request("GET", "healthz", timeout=15)
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")

    try:
        # ---- anchor face: collections+create with ?timeout=0 must be refused ----
        anchor = mkn("anchor_t0")
        st, raw = safe_request("PUT", "create_collection",
                               {"vectors": {"size": 4, "distance": "Cosine"}},
                               path_params={"name": anchor},
                               query_params={"timeout": 0})
        print(f"[anchor create ?timeout=0] status={st} raw={str(raw)[:300]}")
        guard(st, raw, "anchor-create-t0")
        if st in (200, 201):
            CREATED.append(anchor)
            defect("Type1_IllegalSuccess",
                   f"create accepted ?timeout=0 - the query schema minimum 1 is not "
                   f"enforced (assertion qdrant_behavioral_collections_create_005; "
                   f"boundary round measured 422 here); raw={str(raw)[:250]}")
        if not (400 <= st <= 499):
            script_error(f"anchor create ?timeout=0 returned unexpected {st}; raw={str(raw)[:200]}")
        print(f"[anchor] create ?timeout=0 refused with {st} - minimum enforced on the anchor face")

        # ---- sibling face 1: collections+update (PATCH) with ?timeout=0 ----
        upd = mkn("upd")
        make_coll(upd)
        st, raw = safe_request("PATCH", "update_collection", {"hnsw_config": {"m": 16}},
                               path_params={"name": upd},
                               query_params={"timeout": 0})
        print(f"[update ?timeout=0] status={st} raw={str(raw)[:300]}")
        guard(st, raw, "update-t0")
        if st in (200, 201):
            defect("Type1_IllegalSuccess",
                   f"collections+update ACCEPTED ?timeout=0 with {st} while the same "
                   f"shared-schema value is refused 4xx on collections+create - "
                   f"inconsistent disposition of the same parameter across interface "
                   f"faces (G9); raw={str(raw)[:250]}")
        if not (400 <= st <= 499):
            script_error(f"update ?timeout=0 returned unexpected {st}; raw={str(raw)[:200]}")
        print(f"[update] ?timeout=0 refused with {st} - consistent with the anchor face")

        # ---- sibling face 2: collections+delete (DELETE) with ?timeout=0 ----
        dele = mkn("del")
        make_coll(dele)
        st, raw = safe_request("DELETE", "drop_collection", None,
                               path_params={"name": dele},
                               query_params={"timeout": 0})
        print(f"[delete ?timeout=0] status={st} raw={str(raw)[:300]}")
        guard(st, raw, "delete-t0")
        if st in (200, 201):
            # record the side-effect: was the sacrificial collection actually dropped?
            dst, draw = safe_request("GET", "describe_collection",
                                     path_params={"name": dele})
            print(f"[delete side-effect check] describe status={dst} raw={str(draw)[:150]}")
            defect("Type1_IllegalSuccess",
                   f"collections+delete ACCEPTED ?timeout=0 with {st} "
                   f"(describe afterwards: {dst}) while the same shared-schema value "
                   f"is refused 4xx on collections+create - inconsistent disposition "
                   f"of the same parameter across interface faces (G9); raw={str(raw)[:250]}")
        if not (400 <= st <= 499):
            script_error(f"delete ?timeout=0 returned unexpected {st}; raw={str(raw)[:200]}")
        print(f"[delete] ?timeout=0 refused with {st} - consistent with the anchor face")

        # ---- closure on sibling faces: ?timeout=1 (inclusive minimum) must be accepted ----
        st, raw = safe_request("PATCH", "update_collection", {"hnsw_config": {"m": 16}},
                               path_params={"name": upd},
                               query_params={"timeout": 1})
        print(f"[update ?timeout=1 closure] status={st} raw={str(raw)[:300]}")
        guard(st, raw, "update-t1")
        if st not in (200, 201):
            defect("Type1_IllegalRejection",
                   f"collections+update refused ?timeout=1 with {st} - the minimum "
                   f"itself is inclusive (boundary round measured timeout=1 accepted "
                   f"on create); refusing it on the sibling face is the mirror "
                   f"asymmetry; raw={str(raw)[:250]}")
        print("[update] ?timeout=1 accepted - min-closure holds on the sibling face")

        st, raw = safe_request("DELETE", "drop_collection", None,
                               path_params={"name": dele},
                               query_params={"timeout": 1})
        print(f"[delete ?timeout=1 closure] status={st} raw={str(raw)[:300]}")
        guard(st, raw, "delete-t1")
        if st not in (200, 201):
            defect("Type1_IllegalRejection",
                   f"collections+delete refused ?timeout=1 with {st} - the minimum "
                   f"itself is inclusive; raw={str(raw)[:250]}")
        print("[delete] ?timeout=1 accepted - sacrificial collection dropped via the min closure call")

        print("[summary] ?timeout=0 uniformly refused across create/update/delete "
              "faces and ?timeout=1 uniformly accepted - the query-schema minimum "
              "is wired consistently (constraint "
              "qdrant_behavioral_collections_create_005, G9 no-asymmetry)")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
