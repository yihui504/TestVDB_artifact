# TestVDB semantic attack — weaviate v1.38.2
# Attack: behavioral_contract + diagnosis_quality x weaviate_type_batch_delete_match_001
# DELETE /batch/objects with missing match (or match.where / match.class) must be 4xx per docs(required);
# a 500 means unhandled nil deref channel (GT issue #12041 family).
import os, sys, json, requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE = BASE.rstrip("/")
S = requests.Session()

CLS = "TSemMatch01"
try:
    S.delete(f"{BASE}/v1/schema/{CLS}")
except Exception:
    pass
r = S.post(f"{BASE}/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "cat", "dataType": ["string"]}]})
print("setup:", r.status_code, r.text[:200])
S.post(f"{BASE}/v1/objects", json={"class": CLS, "id": "11111111-1111-1111-1111-111111111111",
    "properties": {"cat": "a"}})
S.post(f"{BASE}/v1/objects", json={"class": CLS, "id": "22222222-2222-2222-2222-222222222222",
    "properties": {"cat": "b"}})

def batch_delete(payload):
    rr = S.delete(f"{BASE}/v1/batch/objects", json=payload)
    return rr.status_code, rr.text

cases = {
    "match_missing_entirely": {},  # no match key at all
    "match_where_missing": {"match": {"class": CLS}},
    "match_class_missing": {"match": {"where": {"operator": "Equal", "path": ["cat"], "valueText": "a"}}},
    "match_null": {"match": None},
    "match_empty": {"match": {}},
}
defects = []
for name, payload in cases.items():
    st, tx = batch_delete(payload)
    print(f"[{name}] status={st} body={tx[:250]}")
    if st >= 500:
        defects.append((name, st, tx[:150]))

# diagnosis quality for the clearest 4xx case
st, tx = batch_delete({"match": {"class": CLS}})
low = tx.lower()
score = sum([1 if "match" in low else 0,
             1 if any(h in low for h in ["must", "required", "expected", "valid", "missing"]) else 0,
             1 if any(h in low for h in ["provide", "specify", "use", "correct"]) else 0])
print(f"diagnosis_quality_score(match.where missing): {score}/3")

if defects:
    print("VERDICT: DEFECT_FOUND")
    print("DEFECT: batch delete with malformed match returned 5xx (unhandled validation gap) for: "
          + "; ".join(d[0] for d in defects))
    sys.exit(1)
print("VERDICT: NO_DEFECT")
