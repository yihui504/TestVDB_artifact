# Attack: nearVector distance ordering + distance threshold semantics (v1.38: use `distance`, not `certainty`)
# Target: weaviate v1.38.0 | Endpoint: POST /v1/graphql | Strategy: search_correctness
# Contract: weaviate_behavioral_graphql_query_001
# SKIPPED by-design: certainty vs distance numeric mismatch (certainty = 1 - distance/2 normalization for cosine)
import os, sys, json, uuid
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
BASE = BASE.rstrip("/")
CLS = "SemNearVector02"

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
          "properties": [{"name": "name", "dataType": ["text"]}],
          "vectorIndexConfig": {"distance": "cosine"}}
status, body, raw = safe_request("POST", "/v1/schema", json_body=schema)
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create class failed:", status, raw[:300]); sys.exit(2)

pts = [
    ("origin", [1.0, 0.0]),
    ("close", [0.999, 0.0447]),   # cos dist ~0.001
    ("medium", [0.7071, 0.7071]), # cos dist ~0.2929
    ("far", [0.0, 1.0]),          # cos dist 1.0
]
for name, vec in pts:
    status, _, raw = safe_request("POST", "/v1/objects",
        json_body={"class": CLS, "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, CLS + name)),
                   "properties": {"name": name}, "vector": vec})
    if status not in (200, 201):
        print("VERDICT: SCRIPT_ERROR - insert failed:", status, raw[:300]); sys.exit(2)

import time; time.sleep(1)

def near_query(limit=4, distance=None):
    nv = 'nearVector: {vector: [1.0, 0.0]'
    if distance is not None:
        nv += f', distance: {distance}'
    nv += '}'
    args = f'{nv}, limit: {limit}'
    q = '{ Get { %s(%s) { name _additional { distance } } } }' % (CLS, args)
    status, body, raw = safe_request("POST", "/v1/graphql", data=json.dumps({"query": q}))
    results = []
    if body and (body.get("data") or {}).get("Get", {}).get(CLS):
        for o in body["data"]["Get"][CLS]:
            results.append((o["name"], (o.get("_additional") or {}).get("distance")))
    errs = body.get("errors") if isinstance(body, dict) else None
    return status, results, errs, raw

failures = []

# T1: ordering — origin(0) first, far(1.0) last; distance monotonically non-decreasing
st, res, errs, raw = near_query()
print("T1 ordering:", st, res)
names = [r[0] for r in res]
if errs:
    failures.append(("T1 query error", errs, raw[:200]))
else:
    if names[:1] != ["origin"] or names[-1:] != ["far"]:
        failures.append(("T1 ordering", names, raw[:300]))
    dists = [r[1] for r in res if r[1] is not None]
    if len(dists) == len(res) and any(dists[i+1] < dists[i] - 1e-9 for i in range(len(dists)-1)):
        failures.append(("T1 distance monotonicity", dists, raw[:300]))
    # origin exact match must have distance ~0
    if res and abs(res[0][1]) > 1e-6:
        failures.append(("T1 exact-match distance nonzero", res[0], raw[:300]))

# T2: distance=0.01 -> only origin(0) and close(~0.001)
st, res, errs, raw = near_query(distance=0.01)
got = set(r[0] for r in res)
print("T2 distance<=0.01:", st, got)
if not errs and (got - {"origin", "close"} or "origin" not in got):
    failures.append(("T2 distance threshold", sorted(got), raw[:300]))

# T3: distance=0.3 boundary — medium(0.2929) must be included, far excluded
st, res, errs, raw = near_query(distance=0.3)
got = set(r[0] for r in res)
print("T3 distance<=0.3:", st, got)
if not errs and ("medium" not in got or "far" in got):
    failures.append(("T3 distance 0.3 boundary", sorted(got), raw[:300]))

# T4: distance=1.0 boundary — far(cos dist exactly 1.0) must be included (<= semantics)
st, res, errs, raw = near_query(distance=1.0)
got = set(r[0] for r in res)
print("T4 distance<=1.0:", st, got)
if not errs and "far" not in got:
    failures.append(("T4 distance=1.0 excludes exact-boundary match", sorted(got), raw[:300]))

# T5: limit=2 truncation — exactly 2, top-2 by similarity
st, res, errs, raw = near_query(limit=2)
print("T5 limit=2:", st, res)
if not errs and (len(res) != 2 or set(r[0] for r in res) != {"origin", "close"}):
    failures.append(("T5 limit truncation", res, raw[:300]))

# T6: metamorphic — nearObject on origin must match nearVector ordering
q = '{ Get { %s(nearObject: {id: "%s"}, limit: 4) { name _additional { distance } } } }' % (
    CLS, str(uuid.uuid5(uuid.NAMESPACE_DNS, CLS + "origin")))
st, body, raw = safe_request("POST", "/v1/graphql", data=json.dumps({"query": q}))
res2 = []
if body and (body.get("data") or {}).get("Get", {}).get(CLS):
    res2 = [(o["name"], (o.get("_additional") or {}).get("distance")) for o in body["data"]["Get"][CLS]]
errs2 = body.get("errors") if isinstance(body, dict) else None
print("T6 nearObject:", st, res2, json.dumps(errs2)[:150] if errs2 else "")
if not errs2 and [r[0] for r in res2] != names:
    failures.append(("T6 nearObject vs nearVector ordering mismatch", res2, names))

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if failures:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    for f in failures: print("FAIL:", f)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
