# state_concurrent_insert_07: 并发写一致性 — 并发 POST objects + 并发 DELETE 交错，最终计数
import os, sys, time, uuid, json, threading
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
CLS = "StConG"
NT = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))
PER = 20

def make_sess():
    return requests.Session()

def safe_request(S, method, path, **kw):
    try:
        r = S.request(method, BASE_URL + path, timeout=30, **kw)
    except Exception as e:
        return None, None, "EXC:" + str(e)
    try:
        return r.status_code, r.json(), r.text
    except Exception:
        return r.status_code, None, r.text

S0 = make_sess()
try:
    safe_request(S0, "DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass
safe_request(S0, "POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "name", "dataType": ["text"]}]})

ok_count = [0] * NT
errors = []
lock = threading.Lock()

def writer(tid):
    S = make_sess()
    for i in range(PER):
        oid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"con-{tid}-{i}"))
        st, _, raw = safe_request(S, "POST", "/v1/objects", json={
            "class": CLS, "id": oid, "properties": {"name": f"t{tid}i{i}"}})
        if st in (200, 201):
            ok_count[tid] += 1
        else:
            with lock:
                errors.append((tid, i, st, raw[:120]))
        # interleaved deletes of earlier objects
        if i % 5 == 4:
            did = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"con-{tid}-{i-4}"))
            st, _, raw = safe_request(S, "DELETE", f"/v1/objects/{CLS}/{did}")
            if st == 500:
                with lock:
                    errors.append((tid, "del", st, raw[:120]))
                # compensate so expectation stays computable
                ok_count[tid] -= 1
            elif st in (200, 204):
                ok_count[tid] -= 1

ts = [threading.Thread(target=writer, args=(t,)) for t in range(NT)]
for t in ts: t.start()
for t in ts: t.join()

expected = sum(ok_count)
print(f"writers done: expected committed={expected}, unexpected errors={len(errors)}")
for e in errors[:5]:
    print("  ", e)

time.sleep(3)
q = {"query": "{ Aggregate { %s { meta { count } } } }" % CLS}
st, body, raw = safe_request(S0, "POST", "/v1/graphql", data=json.dumps(q),
                             headers={"Content-Type": "application/json"})
count = None
try:
    count = body["data"]["Aggregate"][CLS][0]["meta"]["count"]
except Exception:
    print("agg raw:", raw[:300])
print(f"final count={count} expected={expected}")

defect = None
server_errors = [e for e in errors if e[2] == 500]
if server_errors:
    defect = f"{len(server_errors)} HTTP 500 during concurrent write/delete: {server_errors[0]}"
if count is not None and count != expected:
    defect = f"final COUNT={count} != expected committed={expected}"

try:
    safe_request(S0, "DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if defect:
    print(f"DEFECT: {defect}")
    print("VERDICT: DEFECT_FOUND"); sys.exit(1)
print("VERDICT: NO_DEFECT")
