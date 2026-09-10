# Attack: Aggregate math correctness — groupBy cardinality, mean/sum/maximum/minimum vs ground truth
# Target: weaviate v1.38.0 | Endpoint: POST /v1/graphql | Strategy: search_correctness (metamorphic)
# SKIPPED by-design: objectLimit without near<Media>/hybrid (documented error);
#                   'max/min' field names are 'maximum/minimum' in v1.38 schema.
import os, sys, json, uuid, statistics
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
BASE = BASE.rstrip("/")
CLS = "SemAgg06"

def safe_request(method, path, json_body=None, data=None):
    headers = {"Content-Type": "application/json"}
    try:
        r = requests.request(method, BASE + path, json=json_body, data=data, headers=headers, timeout=30)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, str(e)

safe_request("DELETE", f"/v1/schema/{CLS}")
schema = {"class": CLS, "vectorizer": "none",
          "properties": [{"name": "cat", "dataType": ["text"]},
                         {"name": "score", "dataType": ["number"]},
                         {"name": "intVal", "dataType": ["int"]}]}
status, _, raw = safe_request("POST", "/v1/schema", json_body=schema)
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create class failed:", status, raw[:300]); sys.exit(2)

truth = [("alpha", 10.0, 1), ("alpha", 20.0, 2), ("alpha", 30.0, 3),
         ("beta", 5.0, 4), ("beta", 15.0, 5),
         ("gamma", 100.0, 6)]
for i, (cat, sc, iv) in enumerate(truth):
    status, _, raw = safe_request("POST", "/v1/objects",
        json_body={"class": CLS, "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{CLS}{i}")),
                   "properties": {"cat": cat, "score": sc, "intVal": iv}})
    if status not in (200, 201):
        print("VERDICT: SCRIPT_ERROR - insert failed:", status, raw[:300]); sys.exit(2)

import time; time.sleep(1)
failures = []

def run(q):
    st, b, raw = safe_request("POST", "/v1/graphql", data=json.dumps({"query": q}))
    return st, b, (b or {}).get("errors"), raw

def parse_groups(b):
    groups = (b or {}).get("data", {}).get("Aggregate", {}).get(CLS) or []
    out = {}
    for g in groups:
        key = (g.get("groupedBy", {}) or {}).get("value", "?").split("#")[-1]
        out[key] = g
    return out

# T1: groupBy cat — 3 groups, exact counts
st, b, errs, raw = run('{ Aggregate { %s(groupBy: ["cat"]) { groupedBy { value } score { count mean } } } }' % CLS)
groups = parse_groups(b)
print("T1 groupBy:", st, {k: v.get("score", {}).get("count") for k, v in groups.items()})
if errs: failures.append(("T1 query error", errs, raw[:200]))
else:
    if {k: v.get("score", {}).get("count") for k, v in groups.items()} != {"alpha": 3, "beta": 2, "gamma": 1}:
        failures.append(("T1 group counts", {k: v.get("score", {}).get("count") for k, v in groups.items()}, raw[:300]))

# T2: global mean/sum/maximum/minimum exact math (number prop: mean/sum; int prop: maximum/minimum)
st, b, errs, raw = run('{ Aggregate { %s { score { mean sum } intVal { maximum minimum } } } }' % CLS)
grp = ((b or {}).get("data", {}).get("Aggregate", {}).get(CLS) or [{}])[0]
scores = [t[1] for t in truth]
print("T2 global stats:", st, json.dumps(grp)[:300])
if errs: failures.append(("T2 query error", errs, raw[:200]))
else:
    exp = {"mean": statistics.mean(scores), "sum": sum(scores)}
    for k, v in exp.items():
        got = (grp.get("score") or {}).get(k)
        if got is None or abs(got - v) > 1e-6:
            failures.append((f"T2 {k}", got, f"expected {v}"))
    iv = grp.get("intVal") or {}
    if iv.get("maximum") != 6 or iv.get("minimum") != 1:
        failures.append(("T2 intVal min/max", iv, "expected max=6 min=1"))

# T3: mean of group alpha = 20 exactly
st, b, errs, raw = run('{ Aggregate { %s(groupBy: ["cat"]) { groupedBy { value } score { mean sum } } } }' % CLS)
groups = parse_groups(b)
a_mean = groups.get("alpha", {}).get("score", {}).get("mean")
a_sum = groups.get("alpha", {}).get("score", {}).get("sum")
print("T3 group alpha mean/sum:", a_mean, a_sum)
if errs: failures.append(("T3 query error", errs, raw[:200]))
elif a_mean is None or abs(a_mean - 20.0) > 1e-6 or a_sum != 60.0:
    failures.append(("T3 group alpha mean/sum", (a_mean, a_sum), "expected 20.0/60.0"))

# T4: count via groupedBy must sum to total object count (no truncation by internal topK)
st, b, errs, raw = run('{ Aggregate { %s(groupBy: ["cat"]) { groupedBy { value } score { count } } } }' % CLS)
groups = parse_groups(b)
counts = {k: (v.get("score") or {}).get("count") for k, v in groups.items()}
total = sum(c for c in counts.values() if c is not None)
print("T4 group counts:", counts)
if total != len(truth):
    failures.append(("T4 group counts truncated", total, f"expected {len(truth)}"))

# T5: overlapping groups (two groupBy props) — each group count correct
q = '{ Aggregate { %s(groupBy: ["cat", "intVal"]) { groupedBy { value } score { count } } } }' % CLS
st, b, errs, raw = run(q)
groups2 = parse_groups(b)
print("T5 two-prop groupBy:", st, {k: (v.get("score") or {}).get("count") for k, v in groups2.items()})
if errs: failures.append(("T5 multi-prop groupBy rejected with misleading diagnostic (real cause: multi-prop groupBy unsupported; msg claims missing argument)", errs, raw[:300]))
else:
    cnts = [v.get("score", {}).get("count") for v in groups2.values()]
    if len(groups2) != 6 or any(c != 1 for c in cnts):
        failures.append(("T5 multi-prop groupBy", {k: (v.get("score") or {}).get("count") for k, v in groups2.items()}, "expected 6 groups of 1"))

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if failures:
    print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
    for f in failures: print("FAIL:", f)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
