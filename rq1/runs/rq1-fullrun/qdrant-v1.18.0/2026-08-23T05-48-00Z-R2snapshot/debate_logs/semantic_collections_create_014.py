# script_id: semantic_collections_create_014
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_range_collections_create_003 (full_scan_threshold rule fork: >=0 valid in HnswConfig on create AND persisted; HnswConfigDiff on PATCH update must enforce the stricter >=10 — 0..9 legal at create, illegal in diff)
# constraint_ids: qdrant_range_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract (create/diff rule asymmetry + persistence)
# Block: chunk_collections+create-2of2
"""Behavioral contract fork: full_scan_threshold >= 0 on create (HnswConfig)
but >= 10 on update (HnswConfigDiff). Three checks:
(a) create with 0 (legal minimum at create) accepted AND describe reads back 0
    — silently raising it to default 10000 flips exact-search behavior;
(b) PATCH update with 5 (legal at create, ILLEGAL in diff) must be rejected 4xx;
(c) PATCH update with 10 (diff minimum) accepted AND persisted.
Self-contained transport: qdrant REST via safe_request (no runtime module);
paths from contract: PUT/GET/PATCH /collections/{collection_name}."""
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


def readback_fst(name):
    s, _, raw = safe_request("GET", f"/collections/{name}")
    print(f"describe {name} -> {s} {raw[:300]}")
    if s != 200:
        return None
    try:
        return json.loads(raw).get("result", {}).get("config", {}) \
            .get("hnsw_config", {}).get("full_scan_threshold")
    except Exception as e:
        print(f"parse note: {e}")
        return None


COLL_A = f"sem_fst0_{TS}"
COLL_B = f"sem_fstpatch_{TS}"
created = []
try:
    # (a) create-time minimum 0 accepted + persisted
    s, _, raw = safe_request("PUT", f"/collections/{COLL_A}",
        {"vectors": {"size": 4, "distance": "Cosine"},
         "hnsw_config": {"full_scan_threshold": 0}})
    print(f"create full_scan_threshold=0 -> {s} {raw[:200]}")
    if s in (200, 201):
        created.append(COLL_A)
    elif 400 <= s < 500:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
        print("full_scan_threshold=0 is legal on create (>=0) but was rejected")
        sys.exit(1)
    else:
        print(f"VERDICT: SCRIPT_ERROR — unexpected create status {s}")
        sys.exit(2)
    got = readback_fst(COLL_A)
    if got is None:
        print("VERDICT: SCRIPT_ERROR — describe unreadable")
        sys.exit(2)
    if got != 0:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"full_scan_threshold=0 accepted but describe reads back {got!r} "
              "(silent coercion to default 10000 changes exact-vs-indexed search semantics)")
        sys.exit(1)

    # (b)+(c) diff rule on PATCH update_collection
    s, _, raw = safe_request("PUT", f"/collections/{COLL_B}",
        {"vectors": {"size": 4, "distance": "Cosine"}})
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — setup create: {s} {raw[:200]}")
        sys.exit(2)
    created.append(COLL_B)

    s, _, raw = safe_request("PATCH", f"/collections/{COLL_B}",
        {"hnsw_config": {"full_scan_threshold": 5}})
    print(f"PATCH diff full_scan_threshold=5 -> {s} {raw[:300]}")
    if s in (200, 201):
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
        print("HnswConfigDiff rejects full_scan_threshold<10 (contract), but PATCH accepted 5")
        sys.exit(1)
    if not (400 <= s < 500):
        print(f"VERDICT: SCRIPT_ERROR — unexpected PATCH status {s}")
        sys.exit(2)

    s, _, raw = safe_request("PATCH", f"/collections/{COLL_B}",
        {"hnsw_config": {"full_scan_threshold": 10}})
    print(f"PATCH diff full_scan_threshold=10 -> {s} {raw[:200]}")
    if s not in (200, 201):
        print("VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
        print(f"full_scan_threshold=10 is the diff minimum, PATCH returned {s}")
        sys.exit(1)
    got = readback_fst(COLL_B)
    if got != 10:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"PATCH accepted 200 but describe reads back {got!r} != 10")
        sys.exit(1)
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    for c in created:
        cleanup(c)
