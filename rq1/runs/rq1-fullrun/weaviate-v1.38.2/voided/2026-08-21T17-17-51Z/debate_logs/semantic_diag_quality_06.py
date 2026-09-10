# Attack: diagnosis_quality (Type2) — invalid filter operator / sort on unknown property /
# aggregate on unknown property / nearVector dimension mismatch. Error messages must name the
# offending parameter and the true cause; misleading or absent diagnostics score low.
import os, sys, json, requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE = BASE.rstrip("/")
S = requests.Session()

CLS = "TSemDiag06"
try:
    S.delete(f"{BASE}/v1/schema/{CLS}")
except Exception:
    pass
r = S.post(f"{BASE}/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["string"]}, {"name": "score", "dataType": ["int"]}]})
if r.status_code != 200:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
S.post(f"{BASE}/v1/objects", json={"class": CLS, "id": "bbbbbbb1-0000-0000-0000-000000000001",
    "properties": {"name": "x", "score": 5}, "vector": [1.0, 0.0]})

def gql(q):
    rr = S.post(f"{BASE}/v1/graphql", json={"query": q})
    try:
        body = rr.json()
    except Exception:
        body = {"raw": rr.text}
    return rr.status_code, body

def quality(body, *needles):
    """score: 1 = mentions param/cause needles, 0 = absent or misleading"""
    msgs = []
    data = body.get("data") or {}
    if body.get("errors"):
        msgs = [e.get("message", "") for e in body["errors"]]
    else:
        # errors may be nested per-field in data
        for k, v in (data.get("Get") or {}).items():
            if v is None:
                continue
        msgs = [str(body)]
    low = " | ".join(msgs).lower()
    hit = sum(1 for n in needles if n.lower() in low)
    return (1 if hit == len(needles) else 0), " | ".join(msgs)[:250]

defects = []
cases = [
    ("invalid where operator",
     '{ Get { %s(where: {operator: Equals, path: ["name"], valueText: "x"}, limit: 1) { name } } }' % CLS,
     ("operator",)),
    ("where on unknown property",
     '{ Get { %s(where: {operator: Equal, path: ["nope"], valueText: "x"}, limit: 1) { name } } }' % CLS,
     ("nope",)),
    ("sort on unknown property",
     '{ Get { %s(limit: 1, sort: {path: ["nope"], order: asc}) { name } } }' % CLS,
     ("nope",)),
    ("aggregate on unknown property",
     '{ Aggregate { %s(groupBy: ["nope"]) { groupedBy { value } } } }' % CLS,
     ("nope",)),
    ("nearVector dimension mismatch (2-d class, 4-d query)",
     '{ Get { %s(nearVector: {vector: [1,0,0,0]}, limit: 1) { name } } }' % CLS,
     ("dimension",)),
]
for label, q, needles in cases:
    st, body = gql(q)
    sc, msg = quality(body, *needles)
    print(f"[{label}] status={st} score={sc} msg={msg}")
    if st == 200 and body.get("errors") is None:
        defects.append(f"{label}: invalid query accepted without error (score 0): {msg}")
    elif sc == 0:
        defects.append(f"{label}: error message does not identify true cause {needles}: {msg}")

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
