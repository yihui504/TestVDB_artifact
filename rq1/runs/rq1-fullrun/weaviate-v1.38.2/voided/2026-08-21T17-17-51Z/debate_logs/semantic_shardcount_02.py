# Attack: behavioral_contract x weaviate_range_sharding_desired_count_001 + state_invariant
# weaviate_state_collection_creation_001 ("Collection exists in GET /schema after POST /schema")
# desiredCount negative: create returns 200 but collection is never actually created (silent
# phantom success). Contract says desiredCount >= 1; rejection should be 4xx at create time.
import os, sys, time, requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE = BASE.rstrip("/")
S = requests.Session()

def try_collection(name, desired):
    try:
        S.delete(f"{BASE}/v1/schema/{name}")
    except Exception:
        pass
    r = S.post(f"{BASE}/v1/schema", json={
        "class": name, "vectorizer": "none",
        "shardingConfig": {"desiredCount": desired},
        "properties": [{"name": "t", "dataType": ["string"]}]})
    return r.status_code, r.text

defects = []
for desired in [0, -1, -5]:
    name = f"TSemShard{str(desired).replace('-', 'n')}"
    st, tx = try_collection(name, desired)
    print(f"[desiredCount={desired}] create status={st} body={tx[:180]}")
    if st == 200:
        time.sleep(2)  # allow schema propagation
        g = S.get(f"{BASE}/v1/schema/{name}")
        print(f"  GET schema status={g.status_code}")
        if g.status_code != 200:
            defects.append(
                f"desiredCount={desired}: POST /schema returned 200 but collection '{name}' "
                f"never became visible (GET /schema/{name} -> {g.status_code}); silent phantom success "
                f"violates state invariant weaviate_state_collection_creation_001")
    try:
        S.delete(f"{BASE}/v1/schema/{name}")
    except Exception:
        pass

if defects:
    print("VERDICT: DEFECT_FOUND")
    for d in defects:
        print("DEFECT:", d)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
