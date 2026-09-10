# semantic_r2b_nprobe_diag_05 — searchParams illegal-key diagnosis quality (Type2, blind R2b)
# Attack: entities+search searchParams with illegal key / structural junk -> error must name key & valid domain
import os, sys, time, json, requests

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

COL = "sem_r2b_spdiag"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create",
                             {"collectionName": COL, "dimension": 4, "metricType": "L2"})
print("create:", st, raw[:120])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed: %s" % raw[:200]); sys.exit(2)
rows = [{"id": i, "vector": [i * 0.1] * 4} for i in range(50)]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert", {"collectionName": COL, "data": rows})
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed: %s" % raw[:200]); sys.exit(2)
st, _, _ = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
time.sleep(2)

def run(params):
    st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
        "collectionName": COL, "data": [[0.0] * 4], "limit": 3, "searchParams": params})
    ok = st == 200 and isinstance(body, dict) and body.get("code") == 0
    return ok, body, raw

def quality(expected_param, body):
    msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    if expected_param.lower() in msg:
        score += 1
    if any(h in msg for h in ["must be", "expected", "should be", "valid", "range", "type", "positive", "non-zero", "unknown", "unsupported", "not support"]):
        score += 1
    if any(h in msg for h in ["correct", "try", "use", "change", "specify", "provide", "supported keys", "allowed"]):
        score += 1
    return score

total, max_total = 0, 0
report = []
# case 1: unknown key (typo of nprobe)
ok, body, raw = run({"nprobes": 4})
print("unknown key 'nprobes': ok=%s raw=%s" % (ok, raw[:200]))
max_total += 3; s = quality("nprobe", body if not ok else {"m": raw}); total += s
report.append(("nprobes", ok, s))

# case 2: empty-string nprobe value
ok, body, raw = run({"nprobe": ""})
print("nprobe='': ok=%s raw=%s" % (ok, raw[:200]))
max_total += 3; s = quality("nprobe", body if not ok else {"m": raw}); total += s
report.append(("nprobe empty string", ok, s))

if total < max_total / 2:
    print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — searchParams error quality %d/%d: %s" % (total, max_total, report))
    sys.exit(1)
print("VERDICT: NO_DEFECT")
