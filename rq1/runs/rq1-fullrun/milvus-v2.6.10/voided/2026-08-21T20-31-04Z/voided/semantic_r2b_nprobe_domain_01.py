# semantic_r2b_nprobe_domain_01 — searchParams.nprobe numeric-domain semantics (blind R2b)
# Attack: entities+search searchParams.nprobe {float, negative, zero, huge} -> Type1_IllegalSuccess on silent accept
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set"); sys.exit(2)
AUTH = {"Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ.get("TESTVDB_MILVUS_TOKEN", "root:Milvus")}

def safe_request(method, endpoint, json_body=None, timeout=20):
    try:
        r = requests.request(method, BASE_URL + endpoint, json=json_body, headers=AUTH, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)

COL = "sem_r2b_nprobe_dom"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create",
                             {"collectionName": COL, "dimension": 8, "metricType": "L2"})
print("create:", st, raw[:120])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed: %s" % raw[:200]); sys.exit(2)

rows = [{"id": i, "vector": [i * 0.01] * 8} for i in range(300)]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert", {"collectionName": COL, "data": rows})
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed: %s" % raw[:200]); sys.exit(2)
st, _, raw = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
print("load:", st, raw[:80])
time.sleep(2)

def search_ids(nprobe):
    st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
        "collectionName": COL, "data": [[0.0] * 8], "limit": 5,
        "searchParams": {"nprobe": nprobe}})
    ok = st == 200 and isinstance(body, dict) and body.get("code") == 0
    ids = [r.get("id") for r in body.get("data", [])] if ok else None
    return ok, ids, raw

ok0, base_ids, raw0 = search_ids(4)
print("baseline nprobe=4 top5:", base_ids)
if not ok0:
    print("VERDICT: SCRIPT_ERROR — baseline search failed: %s" % raw0[:200]); sys.exit(2)

cases = [4.5, -1, 0, 2147483647]
defects = []
for v in cases:
    ok, ids, raw = search_ids(v)
    print("nprobe=%r -> ok=%s top5=%s raw=%s" % (v, ok, ids, raw[:160]))
    if ok:
        defects.append((v, ids))

if defects:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — out-of-domain nprobe values silently accepted: %s" % defects)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
