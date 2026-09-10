# script_id: semantic_aliases_collection_list_003
# strategy: diagnosis_quality
# endpoint: aliases+collection+list
# constraint_ids: qdrant_behavioral_aliases_collection_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/aliases/get-collection-aliases
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: diagnosis_quality x qdrant_behavioral_aliases_collection_list_001 (Type2: the 404 branch's error text must name the queried collection value and state the cause, per the Type-2 scoring rubric)
Oracle: the rejection for an unknown collection names the queried collection value AND states the cause (score >= 2/3 on the Type-2 rubric: value-named + state-hint); an empty/'internal error'-only message that names neither is Type2_PoorDiagnostics

Type-2 diagnostic-quality evaluation of the negative branch of assertion
qdrant_behavioral_aliases_collection_list_001 (unknown collection -> 404).

The error-message STRUCTURE is implementation detail (by-design per threat model),
so this test scores only the diagnostic CONTENT with an explicit rubric:
  c1 (value named):   the queried collection value (a distinctive token) appears
                      in the error text - the user learns WHICH input was wrong;
  c2 (state hint):    the text states the cause/expected state ('not found',
                      'doesn't exist', 'unknown', 'no collection', ...);
  c3 (actionable, bonus): an actionable hint ('create', 'check', 'existing', ...).

Quality floor for NO_DEFECT: c1 + c2 >= 2. A rejection message that names
neither the input value nor the cause (e.g. bare 'Internal error', or an
error about some unrelated entity) is Type2_PoorDiagnostics.

Path templates are derived from the contract api_endpoints:
  aliases+collection+list -> GET /collections/{collection_name}/aliases
"""
import os
import sys
import json
import time
import requests

# --- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)


def resolve_contract_target():
    t = os.environ.get("TESTVDB_TARGET")
    if t:
        return t
    start = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.dirname(os.path.abspath(__file__))
    cur = os.path.abspath(start)
    while True:
        cand = os.path.join(cur, "structured_contract.json")
        if os.path.exists(cand):
            try:
                with open(cand, encoding="utf-8") as fh:
                    return json.load(fh).get("target")
            except Exception:
                return None
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


TARGET = resolve_contract_target()
if TARGET is not None and TARGET != "qdrant":
    print(f"VERDICT: SCRIPT_ERROR - contract target mismatch (expected qdrant, got {TARGET})")
    sys.exit(2)


def safe_request(method, endpoint, json=None, timeout=20):
    """Authoritative wrapper from agents/_target_api_reference.md; returns (status, body, raw)."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.request(method=method, url=url, json=json, headers=headers, timeout=timeout)
        raw_text = resp.text
        try:
            body = resp.json()
        except Exception:
            body = raw_text
        return resp.status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def liveness_ok():
    for ep in ("/readyz", "/livez", "/"):
        try:
            st, _, _ = safe_request("GET", ep, timeout=5)
            if st == 200:
                return True
        except Exception:
            continue
    return False


def extract_error_text(body, raw_text):
    """Error content may live in body['status']['error'] / body['error'] or only
    in the raw text (structure is not contract); fall back to the raw response."""
    if isinstance(body, dict):
        st_obj = body.get("status")
        if isinstance(st_obj, dict) and isinstance(st_obj.get("error"), str) and st_obj["error"]:
            return st_obj["error"]
        if isinstance(body.get("error"), str) and body["error"]:
            return body["error"]
    return raw_text or ""


TS = str(int(time.time()))
UNKNOWN = f"s3_aclist_no_such_{TS}"

LIST_ALIASES_REL = "/collections/{name}/aliases"

# --- Type-2 rubric ---
STATE_HINTS = ["not found", "doesn't exist", "does not exist", "not exist", "unknown", "no collection", "missing"]
ACTION_HINTS = ["create", "check", "existing", "valid", "rename", "use"]


def cleanup():
    try:
        safe_request("DELETE", f"/collections/{UNKNOWN}", timeout=15)
    except Exception:
        pass


try:
    st, body, raw = safe_request("GET", LIST_ALIASES_REL.format(name=UNKNOWN))
    print(f"list aliases of unknown '{UNKNOWN}': status={st}")
    print(f"raw response: {raw[:500]}")

    if st == -1:
        alive = liveness_ok()
        print(f"VERDICT: SCRIPT_ERROR - transport failure (server alive={alive}), no defect conclusion")
        sys.exit(2)
    if 200 <= st < 300:
        # The 404 promise itself is broken; that status anomaly is reported by
        # semantic_aliases_collection_list_002 - no error text exists to score here.
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
        print(f"unknown collection returned HTTP {st} instead of the asserted 404; the diagnostic branch does not exist")
        sys.exit(1)
    if st >= 500:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure)")
        print(f"unknown collection should be rejected with 404; got server error {st}: {raw[:400]}")
        sys.exit(1)

    # st is a 4xx (expected 404): score the diagnostics of the rejection text
    msg = extract_error_text(body, raw)
    msg_l = msg.lower()
    print(f"error text scored: {msg[:400]!r}")

    c1 = 1 if UNKNOWN in msg else 0          # criterion 1: the queried value is named
    c2 = 1 if any(h in msg_l for h in STATE_HINTS) else 0   # criterion 2: cause/state hint
    c3 = 1 if any(h in msg_l for h in ACTION_HINTS) else 0  # criterion 3: actionable hint (bonus)
    score = c1 + c2 + c3
    print(f"Type-2 rubric score: {score}/3 (value-named={c1}, state-hint={c2}, actionable={c3})")

    if not msg.strip() or (c1 + c2) < 2:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        print(f"rejection text names neither the queried collection value ({UNKNOWN}) nor the cause; expected >= 2/3 on value-named+state-hint, got {c1 + c2}/2")
        sys.exit(1)

    print("VERDICT: NO_DEFECT")
finally:
    cleanup()

