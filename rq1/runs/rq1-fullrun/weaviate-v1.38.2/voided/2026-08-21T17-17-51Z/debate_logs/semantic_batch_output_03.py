# Attack: batch output semantics + behavioral_contract (object lifecycle)
# batch delete with output=verbose must report exactly the actually-deleted objects; minimal must
# report counts consistent with a follow-up Aggregate count. Mis-counting or wrong IDs = Type4.
import os, sys, requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE = BASE.rstrip("/")
S = requests.Session()

CLS = "TSemBatch03"
try:
    S.delete(f"{BASE}/v1/schema/{CLS}")
except Exception:
    pass
r = S.post(f"{BASE}/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "cat", "dataType": ["string"]}]})
print("setup:", r.status_code)

ids = []
for i in range(1, 7):
    oid = f"{i:08d}-0000-0000-0000-{i:012d}"
    ids.append(oid)
    rr = S.post(f"{BASE}/v1/objects", json={"class": CLS, "id": oid, "properties": {"cat": "del" if i <= 4 else "keep"}})
    if rr.status_code not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — insert {i} failed: {rr.status_code} {rr.text[:150]}"); sys.exit(2)

# verbose delete of 4 matching objects
r = S.delete(f"{BASE}/v1/batch/objects", json={
    "match": {"class": CLS, "where": {"operator": "Equal", "path": ["cat"], "valueText": "del"}},
    "output": "verbose"})
print("verbose delete:", r.status_code, r.text[:600])
verbose_ids = set()
try:
    res = r.json().get("results", {})
    verbose_ids = {o.get("id") for o in res.get("objects", []) if isinstance(o, dict) and o.get("status") == "SUCCESS"}
    print("reported deleted:", len(verbose_ids), "matches:", res.get("matches", "n/a"))
except Exception as e:
    print("parse fail:", e)

expected = set(ids[:4])
# remaining count must be 2
rc = S.post(f"{BASE}/v1/graphql", json={"query": f"{{ Aggregate {{ {CLS} {{ meta {{ count }} }} }} }}"})
print("post-delete count:", rc.status_code, rc.text[:200])
count_ok = '"count":2' in rc.text.replace(" ", "")

defects = []
if not count_ok:
    defects.append(f"after deleting 4/6 objects Aggregate count != 2: {rc.text[:200]}")
if verbose_ids and verbose_ids != expected:
    defects.append(f"verbose output IDs {sorted(verbose_ids)} != actually-matching objects {sorted(expected)}")
if r.status_code >= 500:
    defects.append(f"batch delete verbose returned {r.status_code}")

# minimal output: matches count must equal actual deletions (2 remaining, delete 1 more)
r2 = S.delete(f"{BASE}/v1/batch/objects", json={
    "match": {"class": CLS, "where": {"operator": "Equal", "path": ["cat"], "valueText": "keep"}},
    "output": "minimal"})
print("minimal delete:", r2.status_code, r2.text[:300])
try:
    m = r2.json().get("results", {}).get("matches")
    if m is not None and m != 2:
        defects.append(f"minimal output matches={m} but 2 objects matched")
except Exception:
    pass

try:
    S.delete(f"{BASE}/v1/schema/{CLS}")
except Exception:
    pass

if defects:
    print("VERDICT: DEFECT_FOUND")
    for d in defects:
        print("DEFECT:", d)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
