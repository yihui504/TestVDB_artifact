# script_id: semantic_collections_create_017
# strategy: diagnosis_quality
# endpoint: collections+create
# Attack: qdrant_behavioral_collections_create_001 (invalid vectors config => 400 'Format error ... untagged enum VectorsConfig' family: 9 malformed shapes, each must be 400 — never 500/200 — and message must name the vectors field / expected variants; rubric < 2 => Type2)
# constraint_ids: qdrant_behavioral_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-01 Parameter Type Coercion Trust + BS-02 Error Message Negligence
# Block: chunk_collections+create-2of2
"""Documented behavioral assertion: invalid vectors config gives HTTP 400 with
'Format error in JSON body: data did not match any variant of untagged enum
VectorsConfig'. R1 semantic_003/004 covered scalar-type abuse of vectors.size
and the invalid-distance-enum message. This script sweeps the WHOLE malformed
shape family of the untagged enum (empty object / int / string / null / array
/ missing distance / missing size / string size / named map missing size):
- any 500 => Type3_RuntimeFailure (validator crash path);
- any 200 => Type1_IllegalSuccess (shape smuggled through);
- 400 with message that names neither 'vector' nor a variant/format hint
  => Type2_PoorDiagnostics (BS-02: untagged-enum errors collapse to noise).
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


# (label, vectors value) — all invalid shapes for the untagged VectorsConfig enum
SHAPES = [
    ("empty object", {}),
    ("integer", 5),
    ("string", "4"),
    ("null", None),
    ("array of floats", [1.0, 2.0, 3.0]),
    ("missing distance", {"size": 4}),
    ("string size", {"size": "4", "distance": "Cosine"}),
    ("missing size", {"distance": "Cosine"}),
    ("named map missing size", {"myvec": {"distance": "Dot"}}),
]

created = []
try:
    scores = []
    for i, (label, bad) in enumerate(SHAPES):
        coll = f"sem_vc{i}_{TS}"
        s, _, raw = safe_request("PUT", f"/collections/{coll}",
            {"vectors": bad})
        print(f"[{label}] vectors={json.dumps(bad)[:60]} -> {s} {raw[:300]}")
        if s in (200, 201):
            created.append(coll)
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
            print(f"malformed vectors config ({label}) accepted with 200")
            sys.exit(1)
        if 500 <= s or s in (0, -1):
            print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure)")
            print(f"malformed vectors config ({label}) crashed validation with {s}")
            sys.exit(1)
        if not (400 <= s < 500):
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} for shape '{label}'")
            sys.exit(2)
        msg = err_text(raw).lower()
        named = 1 if ("vector" in msg or "vectorsconfig" in msg) else 0
        fmt = 1 if any(h in msg for h in (
            "variant", "enum", "expected", "must be", "size", "distance",
            "valid", "type", "missing")) else 0
        act = 1 if any(h in msg for h in (
            "use", "try", "provide", "specify", "expected", "valid")) else 0
        sc = named + fmt + act
        scores.append(sc)
        print(f"    diag score {sc}/3 (named={named} hint={fmt} action={act})")
    avg = sum(scores) / len(scores)
    worst = min(scores)
    print(f"family diag: avg={avg:.2f} worst={worst}/3 over {len(SHAPES)} shapes")
    if worst == 0 or avg < 1.5:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        print("untagged-enum rejection messages carry no field/variant information "
              f"(worst {worst}/3, avg {avg:.2f}) — developer cannot tell 'vectors' is the bad field")
        sys.exit(1)
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    for c in created:
        cleanup(c)
