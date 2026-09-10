# Attack: batch import partial failure error reporting precision
# Target: weaviate v1.38.0 | Endpoint: POST /v1/batch/objects | Strategy: diagnosis_quality / behavioral_contract
# Contract: weaviate_behavioral_objects_post_001
# Blindspot: BS-02 Error Message Negligence
# SKIPPED by-design: unknown-property objects succeed via autoSchema (schema auto-extended) — per autoschema docs.
import os, sys, json, uuid
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
BASE = BASE.rstrip("/")
CLS = "SemBatch04"

def safe_request(method, path, json_body=None, data=None):
    headers = {"Content-Type": "application/json"}
    try:
        r = requests.request(method, BASE + path, json=json_body, data=data, headers=headers, timeout=30)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, str(e)

safe_request("DELETE", f"/v1/schema/{CLS}")
schema = {"class": CLS, "vectorizer": "none",
          "properties": [{"name": "name", "dataType": ["text"]},
                         {"name": "score", "dataType": ["number"]}]}
status, _, raw = safe_request("POST", "/v1/schema", json_body=schema)
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create class failed:", status, raw[:300]); sys.exit(2)

good1 = str(uuid.uuid4())
good2 = str(uuid.uuid4())
dup = str(uuid.uuid4())
batch = [
    {"class": CLS, "id": good1, "properties": {"name": "ok1", "score": 1}, "vector": [1.0, 0.0]},          # ok (idx 0)
    {"class": CLS, "id": str(uuid.uuid4()), "properties": {"name": "badType", "score": "not-a-number"}},  # type error (idx 1)
    {"class": CLS, "id": "not-a-valid-uuid", "properties": {"name": "badId"}},                             # invalid id (idx 2)
    {"class": CLS, "id": dup, "properties": {"name": "dup1", "score": 3}},                                 # dup first (idx 3, ok)
    {"class": CLS, "id": dup, "properties": {"name": "dup2", "score": 4}},                                 # dup second (idx 4, should fail)
    {"class": CLS, "id": good2, "properties": {"name": "ok2", "score": 2}, "vector": [0.0, 1.0]},          # ok (idx 5)
]
status, body, raw = safe_request("POST", "/v1/batch/objects", json_body={"objects": batch})
print("batch status:", status)
print("raw:", raw[:1500])

failures = []
if status != 200:
    print("OBS: entire batch rejected with single status", status)
    failures.append(("batch-level generic rejection", status, raw[:300]))
else:
    results = body if isinstance(body, list) else None
    if not isinstance(results, list):
        failures.append(("unexpected response shape", type(body).__name__, raw[:300]))
    else:
        if len(results) != len(batch):
            failures.append(("result array not index-aligned", len(results), raw[:300]))
        errs = []
        for i, r in enumerate(results):
            res = r.get("result", {})
            if res.get("errors") or res.get("status") == "FAILED":
                errs.append((i, json.dumps(res.get("errors", {}))[:200]))
        print("errors at indices:", errs)
        # Expect: idx1 (type err), idx2 (bad uuid), idx4 (dup) fail; 0,3,5 succeed
        err_idx = sorted(i for i, _ in errs)
        if err_idx != [1, 2, 4]:
            failures.append(("wrong error positions", err_idx, errs))
        msgs = " ".join(m for _, m in errs)
        # Criterion: bad-uuid error must mention uuid/id; dup error must mention duplicate/conflict/exists
        if 2 in err_idx and not any(t in msgs.lower() for t in ["uuid", "id", "invalid"]):
            failures.append(("bad-id error lacks id/uuid mention", msgs[:250], ""))
        if 4 in err_idx and not any(t in msgs.lower() for t in ["exist", "duplicate", "conflict", "already", "id"]):
            failures.append(("dup error lacks cause mention", msgs[:250], ""))

# partial failure must not abort successes
for oid, nm in [(good1, "ok1"), (good2, "ok2")]:
    st, b, rw = safe_request("GET", f"/v1/objects/{CLS}/{oid}")
    print(f"GET {nm}:", st, rw[:120])
    if st != 200:
        failures.append((f"valid object {nm} lost by partial batch failure", st, rw[:200]))

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if failures:
    print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
    for f in failures: print("FAIL:", f)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
