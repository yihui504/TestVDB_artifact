# script_id: semantic_collections_create_016
# strategy: diagnosis_quality
# endpoint: collections+create
# Attack: qdrant_state_collections_create_001 (duplicate-name create semantics: identical-body re-PUT must STILL conflict — create must not act as idempotent update; conflicting-body re-PUT must not mutate existing config; conflict error diagnosis quality rubric)
# constraint_ids: qdrant_state_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-02 Error Message Negligence (+ create-as-update mutation risk)
# Block: chunk_collections+create-2of2
"""State constraint (inferred tier, runtime-observed 409 family): PUT with an
existing collection_name => HTTP 4xx. state_collections_create_001/002/005
covered the conflict + races + data-intact angles. Semantic slices NOT yet
covered:
(a) re-PUT with a byte-identical body must ALSO be 4xx — PUT idempotency must
    not turn create into a silent success on the second call;
(b) re-PUT with a DIFFERENT vectors config must not mutate the live
    collection (create acting as update = Type4);
(c) Type-2 rubric on the conflict message: names the collection(1) +
    'already exist'/conflict hint(1) + actionable(1); score < 2 => Type2.
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


def err_text(raw):
    try:
        b = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(b, dict):
            st = b.get("status")
            if isinstance(st, dict) and isinstance(st.get("error"), str):
                return st["error"]
            if isinstance(b.get("error"), str):
                return b["error"]
        return raw if isinstance(raw, str) else json.dumps(b)
    except Exception:
        return str(raw)


def describe_size(name):
    s, _, raw = safe_request("GET", f"/collections/{name}")
    if s != 200:
        return None
    try:
        return json.loads(raw).get("result", {}).get("config", {}) \
            .get("params", {}).get("vectors", {}).get("size")
    except Exception:
        return None


COLL = f"sem_dup_{TS}"
created = False
try:
    s, _, raw = safe_request("PUT", f"/collections/{COLL}",
        {"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"setup create -> {s} {raw[:200]}")
    if s not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — setup failed")
        sys.exit(2)
    created = True

    # (a) identical-body re-PUT must conflict (not idempotent-success)
    s1, _, raw1 = safe_request("PUT", f"/collections/{COLL}",
        {"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"re-PUT identical body -> {s1} {raw1[:300]}")
    if s1 in (200, 201):
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("PUT on existing collection name with identical body returned 200 — "
              "contract: existing name must fail 4xx (create is not an idempotent update)")
        sys.exit(1)

    # (b) conflicting-body re-PUT must conflict AND not mutate size 4 -> 8
    s2, _, raw2 = safe_request("PUT", f"/collections/{COLL}",
        {"vectors": {"size": 8, "distance": "Dot"}})
    print(f"re-PUT conflicting body (size 8) -> {s2} {raw2[:300]}")
    if s2 in (200, 201):
        size = describe_size(COLL)
        print(f"post-re-PUT describe size={size!r}")
        if size == 8:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print("re-PUT with different config returned 200 AND mutated live collection "
                  "(create acting as destructive update)")
            sys.exit(1)
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("re-PUT on existing name returned 200 (config unchanged) — "
              "contract requires 4xx conflict")
        sys.exit(1)

    for label, st in (("identical", s1), ("conflicting", s2)):
        if not (400 <= st < 500):
            print(f"VERDICT: SCRIPT_ERROR — {label}-body re-PUT status {st} not 4xx")
            sys.exit(2)

    # (c) diagnosis quality on the conflict message
    msg = err_text(raw2)
    m = msg.lower()
    named = 1 if COLL.lower() in m else 0
    hint = 1 if any(h in m for h in ("exist", "already", "conflict", "duplicate", "taken")) else 0
    action = 1 if any(h in m for h in ("use", "try", "choose", "delete", "remove", "rename", "check")) else 0
    sc = named + hint + action
    print(f"conflict diag score {sc}/3 (named={named} hint={hint} action={action}): {msg[:250]}")
    if sc < 2:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        print(f"409-conflict message does not identify the conflicting collection "
              f"or the cause: {msg[:200]}")
        sys.exit(1)
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    if created:
        cleanup(COLL)
