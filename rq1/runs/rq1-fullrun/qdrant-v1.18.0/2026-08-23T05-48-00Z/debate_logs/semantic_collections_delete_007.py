# script_id: semantic_collections_delete_007
# strategy: diagnosis_quality
# endpoint: collections+delete
# Attack: downstream diagnostics after delete (count/search/scroll/get_point on deleted collection:
#         404 errors must name the collection — BS-02 rubric; 5xx on well-formed request => Type3;
#         200 => zombie Type4) x qdrant_bc_collection_delete_isolation_001
# constraint_ids: qdrant_bc_collection_delete_isolation_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-02 Error Message Negligence
# Block: chunk_collections+delete
"""Type-2 diagnosis quality on the downstream face of deletion: after a
collection is dropped, every data-plane endpoint (count/search/scroll/point
get) must fail with a 404 whose message identifies the missing collection.
Generic 'internal error'/empty bodies score < 2/3 on the BS-02 rubric
(param_named + hint + actionable) => Type2. A 500 on these well-formed
requests is Type3; a 200 is a zombie-state Type4."""
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


def check_error_quality(body, expected_param):
    """Type-2 rubric: parameter_named(1) + format_hint(1) + actionable(1)."""
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    if expected_param.lower() in error_msg:
        score += 1
    format_hints = ["must be", "expected", "should be", "valid", "range",
                    "type", "not found", "doesn't exist", "does not exist",
                    "no collection", "unknown collection", "missing"]
    if any(h in error_msg for h in format_hints):
        score += 1
    action_hints = ["check", "verify", "list", "create", "use", "specify",
                    "provide", "exists", "try"]
    if any(h in error_msg for h in action_hints):
        score += 1
    return score


def cleanup(name):
    try:
        safe_request("DELETE", f"/collections/{name}")
    except Exception:
        pass


D = f"sem_del_down_{TS}"
try:
    s, _, raw = safe_request("PUT", f"/collections/{D}",
                             {"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"create: {s} {raw[:150]}")
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — create: {s}")
        sys.exit(2)
    s, _, raw = safe_request("PUT", f"/collections/{D}/points?wait=true",
                             {"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]})
    if s != 200:
        print(f"VERDICT: SCRIPT_ERROR — insert: {s}")
        sys.exit(2)
    s, _, raw = safe_request("DELETE", f"/collections/{D}")
    print(f"delete: {s} {raw[:150]}")
    if s != 200:
        print(f"VERDICT: SCRIPT_ERROR — delete returned {s}")
        sys.exit(2)

    probes = [
        ("count", "POST", f"/collections/{D}/points/count", {"exact": True}),
        ("search", "POST", f"/collections/{D}/points/search",
         {"vector": [0.1, 0.2, 0.3, 0.4], "limit": 3}),
        ("scroll", "POST", f"/collections/{D}/points/scroll", {"limit": 10}),
        ("get_point", "GET", f"/collections/{D}/points/1", None),
    ]
    min_score = 3
    scores = {}
    for label, method, path, jb in probes:
        s, body, raw = safe_request(method, path, jb)
        print(f"{label} on deleted: {s} {raw[:300]}")
        if s == 200:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"{label} returned 200 on deleted collection — zombie data plane")
            sys.exit(1)
        if s == -1 or 500 <= s <= 599:
            print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure)")
            print(f"{label} on deleted collection failed with {s} — server "
                  "error for a well-formed request against an absent resource")
            sys.exit(1)
        if s != 404:
            print(f"note: {label} returned {s} (expected 404); rubric still applied")
        sc = check_error_quality(body, D)
        scores[label] = sc
        min_score = min(min_score, sc)

    print(f"rubric scores per probe: {scores} (min {min_score}/3)")
    if min_score < 2:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        print(f"post-delete error diagnostics score {min_score}/3 — errors do "
              "not identify the missing collection (BS-02)")
        sys.exit(1)
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    cleanup(D)
