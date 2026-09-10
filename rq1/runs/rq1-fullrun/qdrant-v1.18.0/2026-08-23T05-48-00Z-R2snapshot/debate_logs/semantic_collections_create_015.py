# script_id: semantic_collections_create_015
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_range_collections_create_004 (strict_mode_config.max_resident_memory_percent legal bounds 1 and 100 accepted on create AND persisted verbatim in describe readback; silent drop of the deprecated field recorded but not judged)
# constraint_ids: qdrant_range_collections_create_004
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract (deprecated-field persistence fidelity)
# Block: chunk_collections+create-2of2
"""Behavioral contract: strict_mode_config.max_resident_memory_percent in
[1,100]. boundary_06 proved accept/reject status (1 and 100 allowed, 0/101/
float/string rejected; null-accept defect already reported there). Semantic
slice NOT covered: if the server answers 200, describe-collection must read
back the exact value under result.config.strict_mode_config. The field is
deprecated (-> node-wide /quotas, removal 1.21) so a missing node is recorded
as silent-drop note (by-design risk) — but a PRESENT node with a different
value is judged Type4 (config persistence violation).
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


def readback_smr(name):
    """Return (node_present, value) from result.config.strict_mode_config."""
    s, _, raw = safe_request("GET", f"/collections/{name}")
    print(f"describe {name} -> {s} {raw[:400]}")
    if s != 200:
        return None, None
    try:
        node = json.loads(raw).get("result", {}).get("config", {}) \
            .get("strict_mode_config")
    except Exception as e:
        print(f"parse note: {e}")
        return None, None
    if not isinstance(node, dict):
        return False, None
    return True, node.get("max_resident_memory_percent")


created = []
silent_drop = 0
try:
    # legal inclusive bounds: 1 (min) and 100 (max) — integer u8 per spec
    for val in (1, 100):
        coll = f"sem_smr{val}_{TS}"
        s, _, raw = safe_request("PUT", f"/collections/{coll}",
            {"vectors": {"size": 4, "distance": "Cosine"},
             "strict_mode_config": {"enabled": True,
                                    "max_resident_memory_percent": val}})
        print(f"create max_resident_memory_percent={val} -> {s} {raw[:250]}")
        if s in (200, 201):
            created.append(coll)
        elif 400 <= s < 500:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
            print(f"legal max_resident_memory_percent={val} (in [1,100]) wrongly rejected with {s}")
            sys.exit(1)
        else:
            print(f"VERDICT: SCRIPT_ERROR — unexpected create status {s}")
            sys.exit(2)
        present, got = readback_smr(coll)
        if present is None:
            print("VERDICT: SCRIPT_ERROR — describe unreadable")
            sys.exit(2)
        if not present:
            silent_drop += 1
            print(f"note: strict_mode_config node absent in describe for {coll} "
                  "(deprecated field silent-drop; recorded, not judged)")
            continue
        if got != val:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"max_resident_memory_percent={val} accepted with 200 but describe "
                  f"reads back {got!r} — strict-mode cap not persisted as configured")
            sys.exit(1)
    if silent_drop == 2:
        print("note: strict_mode_config consistently absent from describe — "
              "deprecated-field silent drop observed on both bounds")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    for c in created:
        cleanup(c)
