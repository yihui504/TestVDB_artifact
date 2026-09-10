# Attack: search_correctness + metamorphic — nearVector ranking + distance semantics
# Insert origin/close/far vectors; nearVector with distance>0 must rank origin first and
# distance must be non-decreasing. Also verify limit + filter combination semantics.
import os, sys, requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE = BASE.rstrip("/")
S = requests.Session()

CLS = "TSemNear05"
try:
    S.delete(f"{BASE}/v1/schema/{CLS}")
except Exception:
    pass
r = S.post(f"{BASE}/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "grp", "dataType": ["string"]}]})
if r.status_code != 200:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)

vecs = {
    "origin": [1.0, 0.0, 0.0, 0.0],
    "close": [0.99, 0.141, 0.0, 0.0],   # ~cosine distance 0.0001
    "far": [0.0, 0.0, 0.0, 1.0],        # distance 2.0 vs origin
    "mid": [0.7071, 0.7071, 0.0, 0.0],  # distance ~0.29
}
for name, v in vecs.items():
    oid = {"origin": "aaaaaaa1-0000-0000-0000-000000000001",
           "close": "aaaaaaa1-0000-0000-0000-000000000002",
           "far": "aaaaaaa1-0000-0000-0000-000000000003",
           "mid": "aaaaaaa1-0000-0000-0000-000000000004"}[name]
    rr = S.post(f"{BASE}/v1/objects", json={"class": CLS, "id": oid,
        "properties": {"grp": "a" if name != "far" else "b"}, "vector": v})
    if rr.status_code not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — insert {name}: {rr.status_code} {rr.text[:150]}"); sys.exit(2)

def gql(query):
    rr = S.post(f"{BASE}/v1/graphql", json={"query": query})
    return rr.status_code, rr.text

defects = []
# 1. ranking correctness
q = ('{ Get { %s(nearVector: {vector: [1.0,0,0,0]}, limit: 4) '
     '{ _additional { id distance } grp } } }' % CLS)
st, tx = gql(q)
print("rank:", st, tx[:400])
try:
    items = __import__("json").loads(tx)["data"]["Get"][CLS]
    dists = [it["_additional"]["distance"] for it in items]
    if not items or items[0]["grp"] != "a" or abs(dists[0]) > 0.01:
        defects.append(f"origin not ranked first: {items[:2]}")
    if dists != sorted(dists):
        defects.append(f"distances not non-decreasing: {dists}")
except Exception as e:
    defects.append(f"parse/structure failure: {e} raw={tx[:200]}")

# 2. nearVector + where filter: filter grp=="b" must return only 'far'
q2 = ('{ Get { %s(nearVector: {vector: [1.0,0,0,0]}, limit: 4, '
      'where: {operator: Equal, path: ["grp"], valueText: "b"}) '
      '{ _additional { distance } grp } } }' % CLS)
st2, tx2 = gql(q2)
print("filter+near:", st2, tx2[:300])
try:
    items2 = __import__("json").loads(tx2)["data"]["Get"][CLS]
    if len(items2) != 1 or items2[0]["grp"] != "b":
        defects.append(f"nearVector+where grp==b should return exactly 1 far item, got {items2}")
except Exception as e:
    defects.append(f"parse failure filter case: {e} raw={tx2[:200]}")

# 3. metamorphic: distance vs certainty consistency (certainty=1-d)
q3 = ('{ Get { %s(nearVector: {vector: [1.0,0,0,0], certainty: 0.9999}, limit: 4) '
      '{ _additional { id } } } }' % CLS)
st3, tx3 = gql(q3)
print("certainty filter:", st3, tx3[:300])
if st3 != 200 or "errors" in tx3:
    defects.append(f"certainty 0.9999 query failed: {tx3[:200]}")
else:
    try:
        got = __import__("json").loads(tx3)["data"]["Get"][CLS]
        if any(it["_additional"]["id"].endswith("000000000003") for it in got):
            defects.append("certainty=0.9999 still returned far item (distance 2.0)")
    except Exception as e:
        defects.append(f"parse failure certainty: {e}")

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
