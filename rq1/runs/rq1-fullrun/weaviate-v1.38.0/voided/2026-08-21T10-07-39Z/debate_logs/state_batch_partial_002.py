# state_batch_partial_002 — batch/objects partial failure: committed-vs-reported consistency
# + DELETE /batch/objects error semantics
# Attack: batch_partial_consistency / delete_consistency
# Blindspot: partial commit detection (BS-03 family)
# Observed probes: batch response = top-level JSON array of per-object results;
# DELETE /batch/objects requires {"match":{...}} body.
import os, sys, time, requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE = BASE.rstrip("/") + "/v1"
S = requests.Session()

def safe_request(method, path, body=None):
    try:
        r = S.request(method, BASE + path, json=body, timeout=60)
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, r.text
    except Exception as e:
        return -1, None, str(e)

CLS = "StB002"
CLS_BODY = {"class": CLS, "vectorizer": "none",
            "properties": [{"name": "name", "dataType": ["text"]},
                           {"name": "num", "dataType": ["int"]}]}
safe_request("DELETE", f"/schema/{CLS}")
time.sleep(1)
s, b, raw = safe_request("POST", "/schema", CLS_BODY)
print("create:", s); assert s in (200, 201)

def mk(i, num):
    return {"class": CLS, "id": f"22222222-2222-2222-2222-{i:012d}",
            "properties": {"name": f"obj{i}", "num": num}, "vector": [0.1, 0.2]}

batch = [mk(1, 1), mk(2, "not_an_int"), mk(3, 3)]
s, b, raw = safe_request("POST", "/batch/objects", {"objects": batch})
print("batch status:", s)
results = b if isinstance(b, list) else (b or {}).get("objects", [])
reported = [(i + 1, (r or {}).get("result", {}).get("status")) for i, r in enumerate(results)]
print("per-object reported status:", reported)

committed = []
for i in (1, 2, 3):
    gs, gb, graw = safe_request("GET", f"/objects/{CLS}/22222222-2222-2222-2222-{i:012d}")
    committed.append((i, gs))
    print(f"obj{i} GET: {gs}", graw[:100])

defect = False
for (i, st), (j, gs) in zip(reported, committed):
    if st == "SUCCESS" and gs != 200:
        print(f"DEFECT Type4: obj{i} reported SUCCESS but GET={gs}"); defect = True
    if st == "FAILED" and gs == 200:
        print(f"DEFECT Type4: obj{i} reported FAILED but object committed (GET 200)"); defect = True

# DELETE /batch/objects with match clause (authoritative bulk delete)
del_body = {"match": {"class": CLS, "where": {"operator": "And", "operands": [
    {"path": ["num"], "operator": "GreaterThan", "valueInt": 0}]}}}
s, b, raw = safe_request("DELETE", "/batch/objects", del_body)
print("match batch delete:", s, raw[:150])
time.sleep(1.5)
for i in (1, 3):
    gs, _, graw = safe_request("GET", f"/objects/{CLS}/22222222-2222-2222-2222-{i:012d}")
    print(f"post-batch-delete obj{i} GET (expect 404): {gs}")
    if gs == 200:
        print(f"DEFECT Type4: obj{i} still present after 200 batch delete"); defect = True

# error semantics: objects-array body (no match clause) -> expect 400-class, flag 500
s, b, raw = safe_request("DELETE", "/batch/objects",
    {"objects": [{"class": CLS, "id": mk(1, 1)["id"]}]})
print("objects-array body DELETE /batch/objects:", s, raw[:150])
if s == 500:
    print("DEFECT Type3/RuntimeFailure-diagnostic: validation error (empty match clause) returned as 500, expect 400/422")
    defect = True

try:
    safe_request("DELETE", f"/schema/{CLS}")
except Exception:
    pass

print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
