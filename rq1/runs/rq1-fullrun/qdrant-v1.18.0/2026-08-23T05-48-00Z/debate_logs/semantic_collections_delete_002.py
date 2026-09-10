# script_id: semantic_collections_delete_002
# strategy: diagnosis_quality
# endpoint: collections+delete
# Attack: qdrant_state_collections_delete_001 404-branch diagnostics (DELETE missing collection:
#         error must name the collection / state not-found; rubric parameter_named + hint + actionable)
# constraint_ids: qdrant_state_collections_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-02 Error Message Negligence
# Block: chunk_collections+delete
"""Type-2 diagnosis quality: the contract's missing-branch (DELETE missing =>
404) is only half the contract — the error must also be diagnosable. Rubric
(3 pts): (1) parameter/collection named, (2) not-found/format hint,
(3) actionable suggestion. Score < 2 => Type2_PoorDiagnostics.
Self-contained transport: qdrant REST via safe_request."""
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


def check_error_quality(status, body, expected_param):
    """Type-2 rubric: parameter_named(1) + format_hint(1) + actionable(1)."""
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    details = []
    if expected_param.lower() in error_msg:
        score += 1
        details.append("param_named")
    format_hints = ["must be", "expected", "should be", "valid", "range",
                    "type", "not found", "doesn't exist", "does not exist",
                    "no collection", "unknown collection", "missing"]
    if any(h in error_msg for h in format_hints):
        score += 1
        details.append("format_hint")
    action_hints = ["check", "verify", "list", "create", "use", "specify",
                    "provide", "exists", "try"]
    if any(h in error_msg for h in action_hints):
        score += 1
        details.append("actionable")
    return score, details


X = f"sem_del_diag_{TS}_never_exists"
try:
    s, body, raw = safe_request("DELETE", f"/collections/{X}")
    print(f"DELETE missing collection: {s} {raw[:400]}")
    if s == 0 or 500 <= s <= 599:
        print(f"VERDICT: SCRIPT_ERROR — transport/server error {s}")
        sys.exit(2)
    if s == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
        print("DELETE of never-existing collection returned 200 — contract "
              "explicitly asserts DELETE missing => 404")
        sys.exit(1)
    if s != 404:
        # non-404 4xx (e.g. 400) still violates the explicit status contract,
        # but rubric scoring below only applies to the 404 contract branch
        print(f"note: status {s} != contract 404; judging diagnostics anyway")

    score, details = check_error_quality(s, body, X)
    print(f"rubric score: {score}/3 ({', '.join(details) or 'no criteria met'})")

    # a generic empty/garbage body cannot diagnose anything
    msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    if len(msg) < 15:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        print(f"error body effectively empty/generic ({msg!r}) — cannot "
              "identify which collection was not found")
        sys.exit(1)
    if score < 2:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        print(f"404 error for missing collection scores {score}/3 — fails "
              "BS-02 rubric (needs collection named + not-found hint)")
        sys.exit(1)
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    try:
        safe_request("DELETE", f"/collections/{X}")
    except Exception:
        pass
