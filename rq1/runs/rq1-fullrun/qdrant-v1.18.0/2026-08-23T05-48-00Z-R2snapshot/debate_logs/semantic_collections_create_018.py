# script_id: semantic_collections_create_018
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_behavioral_collections_create_002 (success envelope contract: every 200 create response must be CollectionOperationResponse {result, status:"ok", time>=0} — verified across minimal, full-config, and named-vectors create bodies + one PATCH update response)
# constraint_ids: qdrant_behavioral_collections_create_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract (response envelope consistency)
# Block: chunk_collections+create-2of2
"""Explicit behavioral assertion: 200 on success returns
CollectionOperationResponse {result, status ok, time}. Semantic slice: the
envelope must hold for EVERY valid create body shape (minimal VectorParams,
loaded config with hnsw/wal/optimizer knobs, named-vectors map) and for the
PATCH update_collection success response. Missing 'status'/'result' key,
status != "ok", or a negative/absent 'time' => Type4 response-contract
violation (client SDKs branch on these fields).
Self-contained transport: qdrant REST via safe_request (no runtime module);
paths from contract: PUT/PATCH /collections/{collection_name}."""
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


def check_envelope(status, raw, ctx):
    """Return None if envelope OK, else defect description string."""
    print(f"{ctx} -> {status} {raw[:200]}")
    if status not in (200, 201):
        return f"{ctx}: expected 200 success, got {status} (legal body rejected?)"
    try:
        b = json.loads(raw)
    except Exception:
        return f"{ctx}: 200 response is not JSON"
    if not isinstance(b, dict):
        return f"{ctx}: 200 response is not a JSON object"
    if "result" not in b:
        return f"{ctx}: 'result' key missing from CollectionOperationResponse"
    st = b.get("status")
    if st != "ok":
        return f"{ctx}: status={st!r} != 'ok'"
    t = b.get("time")
    if not isinstance(t, (int, float)) or isinstance(t, bool) or t < 0:
        return f"{ctx}: time={t!r} is not a non-negative number"
    return None


created = []
try:
    bodies = [
        ("minimal", {"vectors": {"size": 4, "distance": "Cosine"}}),
        ("full-config", {"vectors": {"size": 4, "distance": "Dot"},
                         "shard_number": 1,
                         "on_disk_payload": False,
                         "hnsw_config": {"m": 8, "ef_construct": 64,
                                         "full_scan_threshold": 10},
                         "wal_config": {"wal_capacity_mb": 32},
                         "optimizers_config": {"default_segment_number": 2}}),
        ("named-vectors", {"vectors": {"v1": {"size": 4, "distance": "Euclid"}}}),
    ]
    for i, (label, body) in enumerate(bodies):
        coll = f"sem_env{i}_{TS}"
        s, _, raw = safe_request("PUT", f"/collections/{coll}", body)
        created.append(coll)
        bad = check_envelope(s, raw, f"create[{label}] {coll}")
        if bad:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(bad)
            sys.exit(1)

    # PATCH update success must use the same operation-response envelope
    s, _, raw = safe_request("PATCH", f"/collections/{created[0]}",
        {"optimizers_config": {"default_segment_number": 3}})
    bad = check_envelope(s, raw, "PATCH update_collection")
    if bad:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(bad)
        sys.exit(1)
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    for c in created:
        cleanup(c)
