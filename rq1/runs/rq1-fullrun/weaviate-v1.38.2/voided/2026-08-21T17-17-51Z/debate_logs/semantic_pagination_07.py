# Attack: pagination semantics — offset+limit union must equal full result set (no dup/loss);
# after-cursor page must be disjoint from first page. Type4 if violated.
import os, sys, json, requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE = BASE.rstrip("/")
S = requests.Session()

CLS = "TSemPage07"
try:
    S.delete(f"{BASE}/v1/schema/{CLS}")
except Exception:
    pass
r = S.post(f"{BASE}/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "idx", "dataType": ["int"]}]})
if r.status_code != 200:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
for i in range(1, 8):
    rr = S.post(f"{BASE}/v1/objects", json={"class": CLS,
        "id": f"ccccccc{i:01d}-0000-0000-0000-00000000000{i:01d}", "properties": {"idx": i}})
    if rr.status_code not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — insert {i}: {rr.status_code}"); sys.exit(2)

def get_ids(**kwargs):
    parts = []
    if "offset" in kwargs:
        parts.append(f"offset: {kwargs['offset']}")
    if "after" in kwargs:
        parts.append(f'after: "{kwargs["after"]}"')
    q = f'{{ Get {{ {CLS}(limit: {kwargs.get("limit", 10)}{", " + ", ".join(parts) if parts else ""}) {{ idx _additional {{ id }} }} }} }}'
    rr = S.post(f"{BASE}/v1/graphql", json={"query": q})
    try:
        items = rr.json()["data"]["Get"][CLS] or []
        return [it["_additional"]["id"] for it in items]
    except Exception:
        print("raw:", rr.text[:250])
        return []

defects = []
full = get_ids(limit=10)
p1 = get_ids(limit=3, offset=0)
p2 = get_ids(limit=3, offset=3)
p3 = get_ids(limit=3, offset=6)
print(f"full={len(full)} p1={len(p1)} p2={len(p2)} p3={len(p3)}")
union = p1 + p2 + p3
if sorted(union) != sorted(full):
    defects.append(f"offset pagination union != full set: union={sorted(union)} full={sorted(full)}")
if len(set(union)) != len(union):
    defects.append(f"duplicate ids across offset pages: {union}")

# after-cursor: page after last id of p1 must be disjoint from p1 and match full[3:]
a1 = get_ids(limit=3)
after_first_page = get_ids(limit=3, after=a1[-1] if a1 else None)
print(f"after-page={after_first_page}")
if after_first_page:
    if set(after_first_page) & set(a1):
        defects.append(f"after-cursor page overlaps first page: {after_first_page} vs {a1}")
    if sorted(after_first_page) != sorted(full[3:6]):
        defects.append(f"after-cursor page != expected slice: {after_first_page} vs {full[3:6]}")

# offset beyond size must return empty (not wrap/error)
over = get_ids(limit=3, offset=100)
if over:
    defects.append(f"offset=100 beyond 7 objects returned results: {over}")

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
