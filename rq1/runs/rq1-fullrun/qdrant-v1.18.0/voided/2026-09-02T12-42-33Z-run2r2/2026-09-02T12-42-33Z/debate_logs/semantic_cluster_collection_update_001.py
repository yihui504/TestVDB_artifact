#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_collection_update_001
# strategy: behavioral_contract
# endpoint: cluster+collection+update
# constraint_ids: qdrant_behavioral_cluster_collection_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - behavioral consistency of the documented 200/400/404 dispositions)
"""
Attack: behavioral_contract x qdrant_behavioral_cluster_collection_update_001 (chunk_cluster+collection+update; strategy 1 - all three documented dispositions: 404 missing collection / 400 invalid peer / 200 valid op accepted; G4 both faces)
Oracle: POST cluster op on a never-created collection returns exactly HTTP 404; the same op with a non-existent to_peer_id (424242) on an existing collection returns exactly HTTP 400; a documented-valid op (create_sharding_key on a custom-sharded collection) returns HTTP 200 - a 2xx on the missing collection or on the invalid peer is Type1_IllegalSuccess, any other status class is Type4 wrong-disposition, and a 5xx with /healthz alive is Type3 (assertion qdrant_behavioral_cluster_collection_update_001)

Assertion qdrant_behavioral_cluster_collection_update_001 (evidence_tier=explicit):
  expected_behavior: "valid cluster operation returns HTTP 200 (accepted); invalid
  peer/shard returns 400; missing collection returns 404" (doc-grounded
  endpoint_registry quote: "200 ok; 400 on invalid peer/shard; 404 for a missing
  collection", verified against the v-1-18-x api-reference
  update-collection-cluster page - not synthesis).

Faces exercised (G4 positive-negative pairing; peer id derived live from
GET /cluster, never hardcoded):
  negative (a): move_shard on a never-created collection -> exactly 404
                (regression probe for this session's R1 "200-on-unknown"
                wrong-disposition family on sibling per-collection endpoints);
  negative (b): move_shard with to_peer_id=424242 (a peer that cannot exist in a
                single-peer deployment) on an existing collection -> exactly 400;
  positive:     create_sharding_key on a collection created with
                sharding_method=custom (operation enum member from the contract
                parameter list) -> 200 accepted.

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (collection_cluster for POST /collections/{name}/cluster,
create_collection / cluster_status / healthz via setup_default-compatible
keys); literal paths forbidden; 2-tuple (status, raw). Transport-failure
branches re-check liveness via an inline safe_request("GET","healthz") probe
with a printed status (the probe call is directly visible in the branch).
Request URL derivation (R4 lesson): path_key collection_cluster resolves to
/collections/{name}/cluster = raw_knowledge api_endpoints[].url for
cluster+collection+update (chunk label NOT used as a route).
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
def safe_request(method, path_key, body=None, path_params=None, query_params=None):
    """All HTTP exits through this visible wrapper (R4 lesson: rt.request alone
    is invisible to the transport classifier); thin delegation, 2-tuple."""
    return rt.request(method, path_key, body=body, path_params=path_params,
                      query_params=query_params)


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
PREFIX = f"s5cu1_{TS}_"
COL_A = PREFIX + "col_auto"       # plain collection (400 face)
COL_C = PREFIX + "col_custom"     # custom-sharded collection (200 face)
GHOST = PREFIX + "no_such_collection"
COLLECTIONS = (COL_A, COL_C)


def cleanup():
    for name in COLLECTIONS:
        try:
            rt.drop_collection(name)
        except Exception:
            pass


def liveness_5xx(st, raw, context):
    """Inline 5xx triage: /healthz alive -> Type3 defect; dead -> SCRIPT_ERROR."""
    hs, hraw = safe_request("GET", "healthz")
    print(f"[5xx liveness] /healthz probe status={hs} raw={str(hraw)[:120]}")
    if hs != 200:
        script_error(f"{context}: got 5xx status {st} and /healthz probe not 200 (={hs}); no defect conclusion")
    defect("Type3_RuntimeFailure",
           f"{context}: documented disposition violated by server error {st} while "
           f"/healthz is 200 (alive); raw={raw[:200]}")


try:
    # ---- guard: make sure the ghost name really is free before probing ----
    try:
        rt.drop_collection(GHOST)
    except Exception:
        pass

    # ---- negative face (a): missing collection must be exactly 404 ----
    st, raw = safe_request("POST", "collection_cluster", {
        "operation": "move_shard",
        "shard_id": 0,
        "from_peer_id": 424242,
        "to_peer_id": 424242,
    }, path_params={"name": GHOST})
    print(f"move_shard on never-created collection '{GHOST}': status={st} raw={raw[:300]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure probing missing-collection face (status=0, /healthz={hs}); no defect conclusion")
    if 500 <= st <= 599:
        liveness_5xx(st, raw, "move_shard on missing collection")
    if 200 <= st < 300:
        defect("Type1_IllegalSuccess",
               f"assertion promises HTTP 404 for a missing collection; POST cluster op on "
               f"never-created '{GHOST}' got {st} with a success payload - the R1 "
               f"'200-on-unknown' disposition family on this endpoint; raw={raw[:200]}")
    if st != 404:
        defect("Type4_StateLogicViolation",
               f"assertion pins 404 for a missing collection; got unexpected status {st} "
               f"(wrong rejection class / doc drift); raw={raw[:200]}")

    # ---- setup: plain collection + peer discovery + custom-sharded collection ----
    ok, err = rt.setup_default(COL_A, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL_A}: {err}")
    SETUP_OK = True

    st, raw = safe_request("GET", "cluster_status")
    print(f"cluster status: status={st} raw={raw[:400]}")
    res = parse_result(raw)
    peer_id = res.get("peer_id") if isinstance(res, dict) else None
    if st != 200 or peer_id is None:
        script_error(f"cannot derive live peer_id from cluster status (status={st}); raw={raw[:200]}")
    print(f"derived live peer_id={peer_id}")

    st, raw = safe_request("PUT", "create_collection", {
        "vectors": {"size": 4, "distance": "Cosine"},
        "sharding_method": "custom",   # contract collections+create param: enum auto|custom (snake_case wire values)
    }, path_params={"name": COL_C})
    print(f"create custom-sharded collection '{COL_C}': status={st} raw={raw[:300]}")
    if st not in (200, 201):
        script_error(f"setup failed creating custom-sharded {COL_C}: {st} {raw[:300]}")

    # ---- negative face (b): invalid peer on an existing collection must be exactly 400 ----
    st, raw = safe_request("POST", "collection_cluster", {
        "operation": "move_shard",
        "shard_id": 0,
        "from_peer_id": peer_id,       # live-derived valid peer
        "to_peer_id": 424242,          # peer that cannot exist in a single-peer deployment
    }, path_params={"name": COL_A})
    print(f"move_shard with invalid to_peer_id on '{COL_A}': status={st} raw={raw[:300]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure probing invalid-peer face (status=0, /healthz={hs}); no defect conclusion")
    if 500 <= st <= 599:
        liveness_5xx(st, raw, "move_shard with invalid peer")
    if 200 <= st < 300:
        defect("Type1_IllegalSuccess",
               f"assertion promises HTTP 400 for an invalid peer; move_shard with "
               f"to_peer_id=424242 on existing '{COL_A}' was accepted with {st}; "
               f"raw={raw[:200]}")
    if st != 400:
        defect("Type4_StateLogicViolation",
               f"assertion pins 400 for an invalid peer; got unexpected status {st} "
               f"(wrong rejection class / doc drift); raw={raw[:200]}")

    # ---- positive face: documented-valid op on a custom-sharded collection must be 200 ----
    shard_key = PREFIX + "sk"
    st, raw = safe_request("POST", "collection_cluster", {
        "operation": "create_sharding_key",
        "shard_key": shard_key,
    }, path_params={"name": COL_C})
    print(f"create_sharding_key '{shard_key}' on '{COL_C}': status={st} raw={raw[:300]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        script_error(f"transport failure probing valid-op face (status=0, /healthz={hs}); no defect conclusion")
    if 500 <= st <= 599:
        liveness_5xx(st, raw, "create_sharding_key valid op")
    if st != 200:
        defect("Type1_IllegalRejection",
               f"assertion promises HTTP 200 for a valid cluster operation; "
               f"create_sharding_key on custom-sharded '{COL_C}' was wrongly rejected "
               f"with {st}: {raw[:300]}")
    try:
        env = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        env = {}
    if not isinstance(env, dict) or "result" not in env:
        defect("Type4_StateLogicViolation",
               f"200 acceptance must carry the standard result envelope (result.<field>); got: {raw[:300]}")

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
