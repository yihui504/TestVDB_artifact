# script_id: semantic_collections_create_013
# strategy: diagnosis_quality
# endpoint: collections+create
# Attack: qdrant_range_collections_create_002 (Type-2 diagnosis quality when ef_construct=3 / 0 rejected: error must name the parameter and hint the >=4 minimum)
# constraint_ids: qdrant_range_collections_create_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-02 Error Message Negligence
# Block: chunk_collections+create-2of2
"""Type-2 rubric test. Contract: hnsw_config.ef_construct >= 4.
boundary_05 proved 3/0 are rejected with 4xx (status only). Semantic slice:
does the 400 body actually tell the developer WHICH nested field is wrong and
what the minimum is? Untagged-enum serde errors frequently collapse to a
generic "data did not match any variant" that names nothing about
ef_construct. Rubric: param_named(1) + format/range hint(1) + actionable(1);
worst sample score < 2 => Type2_PoorDiagnostics.
Self-contained transport: qdrant REST via safe_request (no runtime module);
path from contract: PUT /collections/{collection_name}."""
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
    """Extract error message from qdrant error body {"status":{"error":...}} defensively."""
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


def score_diag(msg, param):
    m = (msg or "").lower()
    pts = []
    pts.append(1 if param.lower() in m else 0)                      # param named
    fmt = ["must be", "expected", "should be", "valid", "range", "minimum",
           "at least", ">=", "greater", "variant", "type"]
    pts.append(1 if any(h in m for h in fmt) else 0)                # format/range hint
    act = ["use", "try", "set ", "provide", "specify", "change", "correct", "at least"]
    pts.append(1 if any(h in m for h in act) else 0)                # actionable
    return sum(pts), pts


created = []
try:
    worst = 3
    worst_case = None
    for ef in (3, 0):
        coll = f"sem_efcdiag{ef}_{TS}"
        s, _, raw = safe_request("PUT", f"/collections/{coll}",
            {"vectors": {"size": 4, "distance": "Cosine"},
             "hnsw_config": {"ef_construct": ef}})
        print(f"create ef_construct={ef} -> {s} {raw[:400]}")
        if s in (200, 201):
            created.append(coll)
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
            print(f"ef_construct={ef} (<4) accepted with 200 — range violation")
            sys.exit(1)
        if 500 <= s or s in (0, -1):
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} for illegal value")
            sys.exit(2)
        if not (400 <= s < 500):
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} for illegal value")
            sys.exit(2)
        msg = err_text(raw)
        sc, pts = score_diag(msg, "ef_construct")
        print(f"ef_construct={ef} diag score {sc}/3 (named={pts[0]} hint={pts[1]} action={pts[2]}): {msg[:200]}")
        if sc < worst:
            worst, worst_case = sc, (ef, msg)
    if worst < 2:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        print(f"rejection of ef_construct={worst_case[0]} scores {worst}/3 — message: {worst_case[1][:200]}")
        sys.exit(1)
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    for c in created:
        cleanup(c)
