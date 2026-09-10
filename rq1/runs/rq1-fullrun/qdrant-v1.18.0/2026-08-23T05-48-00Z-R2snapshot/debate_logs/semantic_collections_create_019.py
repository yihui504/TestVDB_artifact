# script_id: semantic_collections_create_019
# strategy: search_correctness
# endpoint: collections+create
# Attack: qdrant_behavioral_collections_create_003 (Cosine = dot over normalized vectors, auto-normalized at upload [DOC collections]: stored vectors in a Cosine collection must have L2 norm ~1.0; Euclid control must store as-is; cosine scores must be metrically correct — identical ~1.0, orthogonal ~0.0)
# constraint_ids: qdrant_behavioral_collections_create_003
# source_url: https://qdrant.tech/documentation/concepts/collections/
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract (metric semantics fidelity)
# Block: chunk_collections+create-2of2
"""Documented behavior: in Cosine collections vectors are automatically
normalized during upload (stored unit-length); Cosine distance is dot-product
over the normalized vectors. Three semantic checks:
(a) Cosine collection: upsert [1,1,1,1] (norm 2.0) and [3,0,4,0] (norm 5.0);
    scroll with_vector=true must return stored vectors with L2 norm ~1.0.
    Returning the raw unnormalized vector = storage-side contract violation.
(b) Euclid control collection: [1,1,1,1] must stay norm 2.0 (normalizing
    there would corrupt Euclidean distances).
(c) Metric semantics in the Cosine collection: query identical vector ->
    score ~1.0; query orthogonal vector -> score ~0.0 (qdrant cosine score
    = 1 - cosine distance = similarity). Values matching raw dot/euclid
    instead => wrong-metric Type4.
Self-contained transport: qdrant REST via safe_request (no runtime module);
paths from contract: PUT /collections/{n}, PUT /collections/{n}/points,
POST /collections/{n}/points/scroll, POST /collections/{n}/points/query."""
import os, sys, time, math, json, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")
TS = str(int(time.time()))
EPS = 1e-3


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


def l2(v):
    return math.sqrt(sum(x * x for x in v))


def scroll_vectors(name, ids, retries=10):
    """Return {id: vector} for the given ids; retry briefly for async visibility."""
    want = set(ids)
    for _ in range(retries):
        s, _, raw = safe_request("POST", f"/collections/{name}/points/scroll",
            {"limit": 100, "with_vector": True, "with_payload": False})
        if s == 200:
            try:
                pts = json.loads(raw).get("result", {}).get("points", [])
                got = {}
                for p in pts:
                    if p.get("id") in want:
                        vec = p.get("vector")
                        if isinstance(vec, dict):  # named vectors defensive
                            vec = next(iter(vec.values()))
                        if isinstance(vec, list):
                            got[p["id"]] = vec
                if want <= set(got):
                    return got
            except Exception as e:
                print(f"parse note: {e}")
        time.sleep(0.5)
    return None


def query_score(name, qvec, limit=3):
    s, _, raw = safe_request("POST", f"/collections/{name}/points/query",
        {"query": qvec, "limit": limit})
    print(f"query {name} -> {s} {raw[:300]}")
    if s != 200:
        return None, None
    try:
        res = json.loads(raw).get("result", [])
        if not res:
            return None, None
        return res[0].get("id"), res[0].get("score")
    except Exception:
        return None, None


COS = f"sem_normcos_{TS}"
EUC = f"sem_normeuc_{TS}"
created = []
try:
    s, _, raw = safe_request("PUT", f"/collections/{COS}",
        {"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"setup Cosine -> {s} {raw[:200]}")
    if s not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — setup Cosine failed")
        sys.exit(2)
    created.append(COS)
    s, _, raw = safe_request("PUT", f"/collections/{EUC}",
        {"vectors": {"size": 4, "distance": "Euclid"}})
    print(f"setup Euclid -> {s} {raw[:200]}")
    if s not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — setup Euclid failed")
        sys.exit(2)
    created.append(EUC)

    # unnormalized uploads: norms 2.0 and 5.0
    s, _, raw = safe_request("PUT", f"/collections/{COS}/points",
        {"points": [{"id": 1, "vector": [1.0, 1.0, 1.0, 1.0]},
                    {"id": 2, "vector": [3.0, 0.0, 4.0, 0.0]}]})
    print(f"cosine upsert -> {s} {raw[:200]}")
    if s not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — cosine upsert failed")
        sys.exit(2)
    s, _, raw = safe_request("PUT", f"/collections/{EUC}/points",
        {"points": [{"id": 1, "vector": [1.0, 1.0, 1.0, 1.0]}]})
    print(f"euclid upsert -> {s} {raw[:200]}")
    if s not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — euclid upsert failed")
        sys.exit(2)

    # (a) Cosine storage normalization
    vecs = scroll_vectors(COS, [1, 2])
    if vecs is None:
        print("VERDICT: SCRIPT_ERROR — cosine points not scrollable")
        sys.exit(2)
    for pid, expect_orig in ((1, [1.0, 1.0, 1.0, 1.0]), (2, [3.0, 0.0, 4.0, 0.0])):
        n = l2(vecs[pid])
        print(f"cosine id={pid} stored={vecs[pid]} norm={n:.6f} (original norm {l2(expect_orig):.1f})")
        if abs(n - 1.0) > EPS:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Cosine collection stored vector id={pid} with norm {n:.6f} != 1.0 — "
                  "auto-normalization-at-upload contract violated")
            sys.exit(1)

    # (b) Euclid control: must NOT normalize
    vecs_e = scroll_vectors(EUC, [1])
    if vecs_e is None:
        print("VERDICT: SCRIPT_ERROR — euclid point not scrollable")
        sys.exit(2)
    n = l2(vecs_e[1])
    print(f"euclid id=1 stored={vecs_e[1]} norm={n:.6f} (expected 2.0)")
    if abs(n - 2.0) > EPS:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"Euclid collection stored normalized vector (norm {n:.6f} != 2.0) — "
              "normalization leaked into a non-Cosine metric")
        sys.exit(1)

    # (c) cosine metric semantics: identical -> score ~1.0
    top_id, sc = query_score(COS, [1.0, 1.0, 1.0, 1.0])
    if top_id is None:
        print("VERDICT: SCRIPT_ERROR — cosine query returned no result")
        sys.exit(2)
    print(f"identical query: top_id={top_id} score={sc}")
    if top_id != 1 or sc is None or abs(sc - 1.0) > EPS:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"query with identical vector must top out at id=1 score~1.0; got id={top_id} score={sc}")
        sys.exit(1)
    # orthogonal -> score ~0.0
    _, sc_orth = query_score(COS, [1.0, 1.0, -1.0, -1.0])
    if sc_orth is None:
        print("VERDICT: SCRIPT_ERROR — orthogonal query returned no result")
        sys.exit(2)
    print(f"orthogonal query score={sc_orth} (expect ~0.0)")
    if abs(sc_orth - 0.0) > EPS:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"cosine similarity of orthogonal vectors must be ~0.0, got {sc_orth} "
              "(metric semantics != Cosine)")
        sys.exit(1)
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    for c in created:
        cleanup(c)
