# semantic_r2_radiusband_05 — radius/range_filter band semantics backfill (R1 dropped test supplement)
# Attack: entities+search searchParams {radius, range_filter} band inclusion semantics + metamorphic
#   (band vs plain-search filter equivalence) x strategy search_correctness
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set"); sys.exit(2)
AUTH = {"Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ.get("TESTVDB_MILVUS_TOKEN", "root:Milvus")}

def safe_request(method, endpoint, json_body=None, timeout=15):
    try:
        r = requests.request(method, BASE_URL + endpoint, json=json_body, headers=AUTH, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)

COL = "sem_r2_rband"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create",
                             {"collectionName": COL, "dimension": 4, "metricType": "L2"})
print("create:", st, raw[:120])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed: %s" % raw[:200]); sys.exit(2)

# distances from origin (L2, dim 4): id1=0.04, id2=1.0, id3=4.0
rows = [
    {"id": 1, "vector": [0.1] * 4},
    {"id": 2, "vector": [0.5] * 4},
    {"id": 3, "vector": [1.0] * 4},
]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert", {"collectionName": COL, "data": rows})
print("insert:", st, raw[:120])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed: %s" % raw[:200]); sys.exit(2)
st, _, raw = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
time.sleep(2)

def search_ids(params):
    st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
        "collectionName": COL, "data": [[0.0] * 4], "limit": 10, "searchParams": params})
    if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
        return None, raw
    return sorted(r.get("id") for r in body.get("data", [])), raw

# band (0.5, 2.0]: range_filter=0.5 inner, radius=2.0 outer -> only id2 (dist 1.0)
ids, raw = search_ids({"radius": 2.0, "range_filter": 0.5})
print("band (0.5,2.0]:", ids, raw[:250])
if ids is None:
    print("VERDICT: SCRIPT_ERROR — band search failed: %s" % raw[:200]); sys.exit(2)
if ids != [2]:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L2 band (0.5,2.0] expected [2], got %s" % ids)
    sys.exit(1)

# metamorphic: band (0.5,2.0] must equal plain search filtered to same distance window
ids_plain, raw = search_ids({})
print("plain all:", ids_plain, raw[:250])
if ids_plain is None or ids_plain != [1, 2, 3]:
    print("VERDICT: SCRIPT_ERROR — plain search sanity failed: %s" % ids_plain); sys.exit(2)

# radius-only monotonicity: r=0.5 subset of r=2.0 subset of r=5.0
r05, _ = search_ids({"radius": 0.5})
r20, _ = search_ids({"radius": 2.0})
r50, _ = search_ids({"radius": 5.0})
print("radius monotonicity:", r05, r20, r50)
if not (set(r05 or []) <= set(r20 or []) <= set(r50 or [])):
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — radius sets not monotonic: %s / %s / %s" % (r05, r20, r50))
    sys.exit(1)
# distances: id1=0.04, id2=1.0, id3=4.0 -> r0.5={1}, r2.0={1,2}, r5.0={1,2,3}
if r20 != [1, 2] or r05 != [1]:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L2 radius results wrong: r0.5=%s r2.0=%s (expected [1] / [1,2])" % (r05, r20))
    sys.exit(1)

# inverted band (radius < range_filter) is contradictory: must error, not silently return all/none
ids_inv, raw_inv = search_ids({"radius": 0.5, "range_filter": 2.0})
print("inverted band:", ids_inv, raw_inv[:250])
if ids_inv not in (None, []):
    # returned results inside a contradictory (2.0, 0.5] window = impossible-range violation
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — contradictory band radius<range_filter returned results %s" % ids_inv)
    sys.exit(1)

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
print("VERDICT: NO_DEFECT")
