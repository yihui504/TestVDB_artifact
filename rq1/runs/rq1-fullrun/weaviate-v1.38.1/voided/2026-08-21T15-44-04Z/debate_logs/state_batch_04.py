# state_batch_04: batch 部分失败 committed 状态 vs 上报状态
# Send batch with mix of valid objects + invalid (bad dataType); count committed vs reported
import os, sys, time, uuid, json
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
S = requests.Session()

def safe_request(method, path, **kw):
    try:
        r = S.request(method, BASE_URL + path, timeout=60, **kw)
    except Exception as e:
        return None, None, "EXC:" + str(e)
    try:
        return r.status_code, r.json(), r.text
    except Exception:
        return r.status_code, None, r.text

CLS = "StBatD"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass
safe_request("POST", "/v1/schema", json={"class": CLS, "vectorizer": "none",
    "properties": [{"name": "num", "dataType": ["int"]}]})

GOOD = 20
BAD = 5
objs = []
for i in range(GOOD):
    objs.append({"class": CLS, "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"bat-g{i}")),
                 "properties": {"num": i}})
for i in range(BAD):
    # invalid: string into int property + missing class on one
    o = {"class": CLS, "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"bat-b{i}")),
         "properties": {"num": "not-an-int-%d" % i}}
    if i == 0:
        o["class"] = "NoSuchClassX"
    objs.append(o)

st, body, raw = safe_request("POST", "/v1/batch/objects", json={"objects": objs})
print("batch status:", st)
results = body if isinstance(body, list) else []
def _st(r):
    if not isinstance(r, dict): return None
    if r.get("status"): return r["status"]
    return (r.get("result") or {}).get("status")
reported_ok = sum(1 for r in results if _st(r) == "SUCCESS")
reported_err = [r for r in results if _st(r) != "SUCCESS"]
print(f"batch reported: total={len(results)} success={reported_ok} errors={len(reported_err)}")
for r in reported_err[:3]:
    print("  err sample:", json.dumps(r)[:200])

time.sleep(2)

# count committed
q = {"query": "{ Aggregate { %s { meta { count } } } }" % CLS}
st, gbody, grow = safe_request("POST", "/v1/graphql", data=json.dumps(q),
                               headers={"Content-Type": "application/json"})
committed = None
try:
    committed = gbody["data"]["Aggregate"][CLS][0]["meta"]["count"]
except Exception:
    print("agg raw:", grow[:300])
print(f"committed count={committed} (reported success={reported_ok})")

defect = None
# per-class: reported success restricted to this CLS (other-class entries not committed here)
rep_ok_cls = sum(1 for r in results
                 if _st(r) == "SUCCESS" and r.get("class") == CLS)
# poll count up to 10s for convergence before comparing
if committed is not None and committed != rep_ok_cls:
    for _ in range(6):
        time.sleep(1.5)
        st, gb, gr = safe_request("POST", "/v1/graphql",
            data=json.dumps({"query": "{ Aggregate { %s { meta { count } } } }" % CLS}),
            headers={"Content-Type": "application/json"})
        try:
            committed = gb["data"]["Aggregate"][CLS][0]["meta"]["count"]
        except Exception:
            break
        if committed == rep_ok_cls:
            break
    print(f"after poll committed={committed} reported_ok_cls={rep_ok_cls}")
    if committed is not None and committed != rep_ok_cls:
        defect = f"committed={committed} != reported SUCCESS for class={rep_ok_cls}"

# cross-check ghost SUCCESS on nonexistent class
ghost_ok = [r for r in results if _st(r) == "SUCCESS" and r.get("class") != CLS]
for r in ghost_ok:
    st, _, rraw = safe_request("GET", f"/v1/objects/{r.get('class')}/{r.get('id')}")
    st2, sb, _ = safe_request("GET", "/v1/schema")
    names = [c.get("class") for c in (sb or {}).get("classes", [])] if isinstance(sb, dict) else []
    print(f"ghost-check class={r.get('class')} read={st} in_schema={r.get('class') in names}")
    if st == 200 or r.get("class") in names:
        defect = f"batch reports SUCCESS for class {r.get('class')} and object is stored despite class not existing"

# also check bad objects truly absent: query one bad id via Get with where
for i in range(BAD):
    bid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"bat-b{i}"))
    st, _, raw = safe_request("GET", f"/v1/objects/{CLS}/{bid}")
    if st == 200:
        defect = f"invalid object {bid} silently committed (reported failed but stored)"

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if defect:
    print(f"DEFECT: {defect}")
    print("VERDICT: DEFECT_FOUND"); sys.exit(1)
print("VERDICT: NO_DEFECT")
