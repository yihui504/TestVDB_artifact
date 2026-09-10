# script_id: semantic_collections_create_012
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_range_collections_create_002 (ef_construct legal-value persistence roundtrip: create with spec-minimum 4 / 5 / 128, describe must read back the exact value, not the default 100)
# constraint_ids: qdrant_range_collections_create_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract (config persistence fidelity)
# Block: chunk_collections+create-2of2
"""Behavioral contract: hnsw_config.ef_construct >= 4 (spec minimum).
Boundary round already proved 3/0/-1 rejected and 4 accepted (boundary_05,
NO_DEFECT). Semantic slice NOT covered: a legal accepted value must be
PERSISTED — describe-collection must read back exactly what was set.
Silently coercing ef_construct=4 up to the default 100 (doc default) would be
a Type4 config-persistence violation: user's index-build budget ignored.
Self-contained transport: qdrant REST via safe_request (no runtime module);
paths from contract: PUT/GET /collections/{collection_name}."""
import os, sys, time, json, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")
TS = str(int(time.time()))


def safe_request(method, path, json_body=None, timeout=30):
    """(status, body, raw_text) triple — spec-mandated wrapper."""
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers,
                                json=json_body, timeout=timeout)
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return resp.status_code, body, resp.text
    except Exception as e:
        return -1, str(e), str(e)


def cleanup(name):
    try:
        safe_request("DELETE", f"/collections/{name}")
    except Exception:
        pass


def readback_ef(name):
    """Return result.config.hnsw_config.ef_construct from describe, or None."""
    s, _, raw = safe_request("GET", f"/collections/{name}")
    print(f"describe {name} -> {s} {raw[:300]}")
    if s != 200:
        return None
    try:
        cfg = json.loads(raw).get("result", {}).get("config", {})
        return cfg.get("hnsw_config", {}).get("ef_construct")
    except Exception as e:
        print(f"parse note: {e}")
        return None


created = []
try:
    # legal values: 4 (spec minimum), 5, 128 — all must be accepted AND persisted
    for ef in (4, 5, 128):
        coll = f"sem_efc{ef}_{TS}"
        s, _, raw = safe_request("PUT", f"/collections/{coll}",
            {"vectors": {"size": 4, "distance": "Cosine"},
             "hnsw_config": {"ef_construct": ef}})
        print(f"create ef_construct={ef} -> {s} {raw[:200]}")
        if s in (200, 201):
            created.append(coll)
        elif 400 <= s < 500:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
            print(f"legal ef_construct={ef} (>=4) wrongly rejected with {s}")
            sys.exit(1)
        else:
            print(f"VERDICT: SCRIPT_ERROR — unexpected create status {s}")
            sys.exit(2)
        got = readback_ef(coll)
        if got is None:
            print("VERDICT: SCRIPT_ERROR — describe unreadable, cannot verify persistence")
            sys.exit(2)
        if got != ef:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"ef_construct={ef} accepted with 200 but describe reads back {got!r} "
                  "(silent coercion to default = user config not persisted)")
            sys.exit(1)

    # informational contrast: no hnsw_config -> default ef_construct=100 (doc: hnsw defaults)
    ctrl = f"sem_efcdef_{TS}"
    s, _, raw = safe_request("PUT", f"/collections/{ctrl}",
        {"vectors": {"size": 4, "distance": "Cosine"}})
    if s in (200, 201):
        created.append(ctrl)
        print(f"info: default ef_construct readback = {readback_ef(ctrl)!r} (doc says 100)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    for c in created:
        cleanup(c)
