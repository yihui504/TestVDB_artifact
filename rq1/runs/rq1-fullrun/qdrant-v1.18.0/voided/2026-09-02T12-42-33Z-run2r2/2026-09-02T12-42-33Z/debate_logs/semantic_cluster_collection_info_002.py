#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_collection_info_002
# strategy: behavioral_contract
# endpoint: cluster+collection+info
# constraint_ids: qdrant_type_cluster_collection_info_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - documented response field vs actually serialized payload)
"""
Attack: behavioral_contract x qdrant_type_cluster_collection_info_001 (chunk_cluster+collection+info; strategy 1, response-shape face of the type constraint)
Oracle: the 200 body's result object carries all six documented CollectionClusterInfo members with their documented shapes - peer_id integer, shard_count integer >= 0 (constraint pins "minimum 0"), local_shards/remote_shards/shard_transfers arrays, and resharding_operations present as an array per the constraint's "response contains ... resharding_operations"; a core member missing or mistyped is Type4_StateLogicViolation, and resharding_operations being absent from the payload on an idle deployment is reported as a Type4 documentation-drift finding (documented schema member conditionally omitted), for downstream adjudication against the constraint text (constraint qdrant_type_cluster_collection_info_001)

Type constraint qdrant_type_cluster_collection_info_001 (evidence_tier=explicit):
  assertion: "response contains peer_id, shard_count (minimum 0), local_shards,
  remote_shards, shard_transfers, resharding_operations"
  (CollectionClusterInfo schema, v-1-18-x api-reference
  distributed/collection-cluster-info).

Why the resharding_operations presence check is load-bearing (BS-05): the
constraint lists it as a contained member unconditionally. An implementation
that serializes it only when non-empty makes every spec-generated client that
dereferences the documented field break on the common idle case - exactly the
documentation-drift shape. The script measures presence/absence and reports the
absence branch as a distinct, precisely-framed finding so the judge can weigh
contract text vs implementation; presence (even as an empty array) is a pass.

Bounds discipline (G5/G7): peer_id/shard_count are checked as non-bool
integers; shard_count additionally >= 0 per the constraint's explicit bound;
the three collection members must be JSON arrays. Entry-level fields beyond
the six documented members are printed for evidence but carry no defect claim
(the constraint pins exactly these six).

Runtime protocol (agents/_target_api_reference.md, qdrant v2.3): all HTTP via
rt.request path_key (collection_cluster / create_collection via setup_default /
drop_collection / healthz); literal paths forbidden; 2-tuple (status, raw).
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

CORE_FIELDS = ("peer_id", "shard_count", "local_shards", "remote_shards", "shard_transfers")
DRIFT_FIELD = "resharding_operations"


# ---------------- helpers ----------------
def is_int(v):
    """Strict integer check (bool is an int subclass in Python - exclude it)."""
    return isinstance(v, int) and not isinstance(v, bool)


def parse_result(raw):
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    if isinstance(b, dict):
        return b.get("result")
    return None


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
PREFIX = f"s4ci2_{TS}_"
COL = PREFIX + "col"


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception:
        pass


try:
    # ---- setup + positive control: existing collection must answer 200 ----
    ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
    if not ok:
        script_error(f"setup failed creating {COL}: {err}")
    SETUP_OK = True
    st, raw = rt.request("GET", "collection_cluster", path_params={"name": COL})
    print(f"cluster info of '{COL}': status={st} raw={raw[:600]}")
    v = rt.judge_200(st, raw, setup_ok=SETUP_OK)
    if v == "SCRIPT_ERROR":
        alive = liveness_ok()
        script_error(f"cluster info unavailable for an existing collection (status={st}, server alive={alive}); no defect conclusion")
    if v == "DEFECT_FOUND":
        defect("Type1_IllegalRejection",
               f"legal GET cluster info of existing collection '{COL}' rejected: status={st} "
               f"(assertion face 'existing collection: HTTP 200'); raw={raw[:300]}")

    res = parse_result(raw)
    if not isinstance(res, dict):
        defect("Type4_StateLogicViolation",
               f"200 response must carry the CollectionClusterInfo object under the result envelope; "
               f"got: {raw[:300]}")

    # ---- (1) core members: presence + documented shape ----
    for f in CORE_FIELDS:
        if f not in res:
            defect("Type4_StateLogicViolation",
                   f"documented CollectionClusterInfo member '{f}' missing from the 200 payload "
                   f"(constraint: response contains peer_id, shard_count, local_shards, remote_shards, "
                   f"shard_transfers, resharding_operations); raw={raw[:300]}")
    if not is_int(res.get("peer_id")):
        defect("Type4_StateLogicViolation",
               f"peer_id must serialize as an integer, got {res.get('peer_id')!r} ({type(res.get('peer_id')).__name__})")
    if not is_int(res.get("shard_count")):
        defect("Type4_StateLogicViolation",
               f"shard_count must serialize as an integer, got {res.get('shard_count')!r} "
               f"({type(res.get('shard_count')).__name__})")
    if is_int(res.get("shard_count")) and res["shard_count"] < 0:
        defect("Type4_StateLogicViolation",
               f"constraint pins shard_count minimum 0, got {res['shard_count']}")
    for f in ("local_shards", "remote_shards", "shard_transfers"):
        if not isinstance(res.get(f), list):
            defect("Type4_StateLogicViolation",
                   f"documented array member '{f}' has non-array shape: {res.get(f)!r}")
    for entry in res["local_shards"]:
        if not isinstance(entry, dict):
            defect("Type4_StateLogicViolation",
                   f"local_shards entries must be objects, got {entry!r}")
    # evidence-only observation (no claim pinned by the constraint text)
    print(f"observed topology: peer_id={res['peer_id']} shard_count={res['shard_count']} "
          f"local={len(res['local_shards'])} remote={len(res['remote_shards'])} "
          f"transfers={len(res['shard_transfers'])} local_shard_ids="
          f"{sorted(e.get('shard_id') for e in res['local_shards'] if isinstance(e, dict))}")

    # ---- (2) drift member: resharding_operations presence per the constraint text ----
    if DRIFT_FIELD not in res:
        defect("Type4_StateLogicViolation",
               f"documented CollectionClusterInfo member '{DRIFT_FIELD}' is absent from the 200 payload "
               f"of an idle (no-resharding-in-flight) collection, while the explicit-tier constraint "
               f"states the response contains it - documented-schema-field conditionally omitted "
               f"(documentation drift; spec-generated clients dereferencing the documented field break "
               f"on the common idle case); raw={raw[:300]}")
    if not isinstance(res.get(DRIFT_FIELD), list):
        defect("Type4_StateLogicViolation",
               f"'{DRIFT_FIELD}' is documented as an array of resharding operations, got "
               f"{res.get(DRIFT_FIELD)!r}")
    print(f"{DRIFT_FIELD} present with {len(res[DRIFT_FIELD])} entries (constraint-conformant serialization)")

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()
